"""network/game_client.py - 联机游戏 Client（加入方）端。

Client 负责：
  - 接收 Host 同步的游戏状态
  - 将 P2（自己）的操作发送给 Host
  - 不运行 state_machine，只渲染
"""
from __future__ import annotations

import socket
import threading
import time
from typing import Any, Optional

from network.protocol import make_message, parse_message, GAME_STATE, PLAYER_ACTION


class GameClient:
    """联机游戏客户端。

    用法：
        client = GameClient(host_socket)
        # 在游戏主循环中：
        state = client.get_latest_state()   # 获取最新状态
        client.send_action("play_card", {...})  # 发送操作
        client.close()
    """

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._sock.setblocking(False)

        # 最新状态
        self._latest_state: dict[str, Any] = {}
        self._lock = threading.Lock()

        # 接收线程
        self._running = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    def _recv_loop(self) -> None:
        """后台接收 Host 的状态同步。"""
        buf = b""
        while self._running:
            try:
                chunk = self._sock.recv(65536)
                if not chunk:
                    print("[GameClient] Host 断开连接")
                    break
                buf += chunk
                # 可能一次收到多条消息，只保留最新的
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    parsed = parse_message(line.decode("utf-8"))
                    if parsed:
                        msg_type, payload = parsed
                        if msg_type == GAME_STATE:
                            with self._lock:
                                self._latest_state = payload
            except BlockingIOError:
                time.sleep(0.016)
            except ConnectionResetError:
                print("[GameClient] 连接被 Host 重置")
                break
            except OSError as e:
                if self._running:
                    print(f"[GameClient] 接收异常: {e}")
                break
            except Exception as e:
                if self._running:
                    print(f"[GameClient] 未知异常: {e}")
                break

    def get_latest_state(self) -> dict[str, Any] | None:
        """获取最新的游戏状态。

        Returns:
            状态字典（非空），或 None（未收到任何状态）。
        """
        with self._lock:
            if self._latest_state and self._latest_state.get("phase"):
                return dict(self._latest_state)
            return None

    def send_action(self, action: str, data: dict[str, Any] | None = None) -> None:
        """发送操作给 Host。

        Args:
            action: 操作类型（play_card / finish_turn / play_card_remedy）
            data: 操作数据（如卡牌 ID 等）
        """
        payload = {"action": action}
        if data:
            payload.update(data)
        msg = make_message(PLAYER_ACTION, payload)
        try:
            self._sock.sendall(msg.encode("utf-8"))
        except Exception:
            pass

    def close(self) -> None:
        """关闭连接。"""
        self._running = False
        try:
            self._sock.close()
        except Exception:
            pass
