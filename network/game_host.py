"""network/game_host.py - 联机游戏 Host（房主）端。

Host 负责：
  - 运行完整 state_machine 逻辑
  - 接收 Client 的操作指令（出牌、结束出牌等）
  - 每帧同步游戏状态给 Client
  - Host 作为 P1，Client 作为 P2
"""
from __future__ import annotations

import json
import socket
import threading
from typing import Any, Optional

from network.protocol import make_message, parse_message, GAME_STATE, PLAYER_ACTION


class GameHost:
    """联机游戏房主。

    用法：
        host = GameHost(client_socket)
        # 在游戏主循环中：
        actions = host.poll_actions()       # 获取 Client 操作
        host.send_state(state_dict)         # 同步状态给 Client
        host.close()                        # 游戏结束
    """

    def __init__(self, client_sock: socket.socket) -> None:
        self._sock = client_sock
        self._sock.setblocking(False)

        # 操作队列（线程安全）
        self._action_queue: list[dict[str, Any]] = []
        self._lock = threading.Lock()

        # 接收线程
        self._running = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    def _recv_loop(self) -> None:
        """后台接收 Client 消息。"""
        buf = b""
        while self._running:
            try:
                chunk = self._sock.recv(8192)
                if not chunk:
                    print("[GameHost] Client 断开连接")
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    parsed = parse_message(line.decode("utf-8"))
                    if parsed:
                        msg_type, payload = parsed
                        if msg_type == PLAYER_ACTION:
                            with self._lock:
                                self._action_queue.append(payload)
            except BlockingIOError:
                import time
                time.sleep(0.016)
            except ConnectionResetError:
                print("[GameHost] 连接被 Client 重置")
                break
            except OSError as e:
                if self._running:
                    print(f"[GameHost] 接收异常: {e}")
                break
            except Exception as e:
                if self._running:
                    print(f"[GameHost] 未知异常: {e}")
                break

    def poll_actions(self) -> list[dict[str, Any]]:
        """获取并清空 Client 操作队列。

        Returns:
            操作列表 [{"action": "play_card"/"finish_turn"/..., ...}]
        """
        with self._lock:
            actions = list(self._action_queue)
            self._action_queue.clear()
            return actions

    def send_state(self, state: dict[str, Any]) -> None:
        """将游戏状态同步给 Client。

        只发送渲染所需的数据，过滤不可序列化的对象。
        """
        try:
            serializable = self._serialize_state(state)
            msg = make_message(GAME_STATE, serializable)
            self._sock.sendall(msg.encode("utf-8"))
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[GameHost] send_state 失败: {e}")

    def _serialize_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """将 state dict 序列化为可 JSON 化的结构。"""
        import pygame

        result: dict[str, Any] = {}

        try:
            # 基础字段
            phase_val = state.get("phase")
            if hasattr(phase_val, "name"):
                result["phase"] = str(phase_val.name)
            else:
                result["phase"] = str(phase_val) if phase_val else ""
        except Exception:
            result["phase"] = ""

        result["time_left"] = state.get("time_left", 90)
        result["winner"] = state.get("winner")
        result["round_count"] = state.get("round_count", 0)

        try:
            # 玩家数据
            players = state.get("players", {})
            result["players"] = {}
            for key in ("P1", "P2"):
                p = players.get(key, {})
                result["players"][key] = {
                    "hp": p.get("hp", 10),
                    "max_hp": p.get("max_hp", 10),
                    "max_mana": p.get("max_mana", 5),
                    "current_mana": p.get("current_mana", 5),
                }
        except Exception:
            result["players"] = {"P1": {"hp": 10}, "P2": {"hp": 10}}

        try:
            # 手牌 — 只发送 Client（P2）的完整信息，Host（P1）只发数量
            hands = state.get("hands", {})
            result["hands"] = {
                "P1": _serialize_card_list(hands.get("P1", []), hide=True),   # 隐藏对手手牌
                "P2": _serialize_card_list(hands.get("P2", [])),              # 自己手牌完整
            }
        except Exception:
            result["hands"] = {"P1": [], "P2": []}

        try:
            # 出牌
            played = state.get("played_cards", {})
            result["played_cards"] = {
                "P1": _serialize_card_list(played.get("P1", [])),
                "P2": _serialize_card_list(played.get("P2", [])),
            }
        except Exception:
            result["played_cards"] = {"P1": [], "P2": []}

        try:
            # 预出牌
            pending = state.get("pending_play", {})
            result["pending_play"] = {
                "P1": _serialize_card_list(pending.get("P1", [])),
                "P2": _serialize_card_list(pending.get("P2", [])),
            }
        except Exception:
            result["pending_play"] = {"P1": [], "P2": []}

        # 牌堆数量
        try:
            deck = state.get("deck")
            result["deck_size"] = len(deck.cards) if hasattr(deck, "cards") else state.get("deck_size", 0)
        except Exception:
            result["deck_size"] = 0

        # Toasts
        result["toasts"] = state.get("toasts", [])

        # 战报
        result["floating_texts"] = state.get("floating_texts", [])

        # 临时状态（沉默等）
        try:
            temp = state.get("temp", {})
            result["temp"] = {k: v for k, v in temp.items() if isinstance(v, (str, int, float, bool))}
        except Exception:
            result["temp"] = {}

        return result

    def close(self) -> None:
        """关闭连接。"""
        self._running = False
        try:
            self._sock.close()
        except Exception:
            pass


def _serialize_card_list(cards: list[Any], hide: bool = False) -> list[dict[str, Any]]:
    """序列化卡牌列表。

    Args:
        cards: Card 对象列表
        hide: 是否隐藏详情（对手手牌只显示数量）
    """
    if hide:
        return [{"hidden": True} for _ in cards]

    result = []
    for c in cards:
        if hasattr(c, "__dict__"):
            result.append({
                "id": getattr(c, "id", 0),
                "name": getattr(c, "name", ""),
                "cost": getattr(c, "cost", 0),
                "atk": getattr(c, "atk", 0),
                "faction": getattr(c, "faction", ""),
                "type": getattr(c, "type", ""),
                "limit_flag": getattr(c, "limit_flag", False),
                "effect_id": getattr(c, "effect_id", ""),
                "description": getattr(c, "description", ""),
                "image_file": getattr(c, "image_file", ""),
            })
        elif isinstance(c, dict):
            result.append(c)
        else:
            result.append({"id": 0, "name": str(c)})
    return result
