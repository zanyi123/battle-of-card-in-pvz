"""network/lan_discovery.py - 局域网玩家发现模块。

工作原理：
  1. 每个玩家启动后，周期性 UDP 广播自己的信息（ID、名字、IP）
  2. 同时监听 UDP 广播，收集其他在线玩家
  3. 收到广播后回复自己的信息

无需中心服务器，纯 UDP 广播。
"""
from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any, Callable

from network.protocol import (
    BROADCAST_PORT,
    LAN_PORT,
    BROADCAST_INTERVAL,
    make_message,
    parse_message,
)
from core.player_profile import get_player_id, get_player_name


class LanDiscovery:
    """局域网玩家发现服务。

    用法：
        discovery = LanDiscovery()
        discovery.start()
        # ... 随时调用 discovery.get_online_players() 获取在线列表
        discovery.stop()
    """

    def __init__(self) -> None:
        self._running: bool = False
        self._thread_broadcast: threading.Thread | None = None
        self._thread_listen: threading.Thread | None = None
        self._lock = threading.Lock()

        # 在线玩家缓存 {player_id: {"name": str, "ip": str, "last_seen": float}}
        self._players: dict[str, dict[str, Any]] = {}

        # 本机信息
        self._my_id = get_player_id()
        self._my_name = get_player_name()
        self._my_ip = self._get_local_ip()

        # 超时剔除阈值（秒）
        self._timeout = 6.0

    @staticmethod
    def _get_local_ip() -> str:
        """获取本机局域网 IP。"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def get_local_ip(self) -> str:
        """返回本机局域网 IP。"""
        return self._my_ip

    def get_subnet_name(self) -> str:
        """返回局域网子网标识（简单用 IP 前三段）。"""
        parts = self._my_ip.split(".")
        if len(parts) >= 3:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.x"
        return self._my_ip

    def start(self) -> None:
        """启动广播和监听线程。"""
        if self._running:
            return
        self._running = True
        self._thread_broadcast = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._thread_listen = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread_broadcast.start()
        self._thread_listen.start()

    def stop(self) -> None:
        """停止广播和监听。"""
        self._running = False
        # 等待线程结束
        if self._thread_broadcast:
            self._thread_broadcast.join(timeout=2.0)
        if self._thread_listen:
            self._thread_listen.join(timeout=2.0)

    def get_online_players(self) -> list[dict[str, Any]]:
        """获取当前在线玩家列表（排除自己，剔除超时）。"""
        now = time.time()
        with self._lock:
            # 剔除超时
            expired = [
                pid for pid, info in self._players.items()
                if now - info.get("last_seen", 0) > self._timeout
            ]
            for pid in expired:
                del self._players[pid]
            return [
                {"player_id": pid, "name": info["name"], "ip": info["ip"]}
                for pid, info in self._players.items()
                if pid != self._my_id
            ]

    def _broadcast_loop(self) -> None:
        """周期性 UDP 广播本机信息。"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        msg = make_message("DISCOVER", {
            "player_id": self._my_id,
            "player_name": self._my_name,
            "ip": self._my_ip,
        })

        while self._running:
            try:
                sock.sendto(msg.encode("utf-8"), ("<broadcast>", BROADCAST_PORT))
            except Exception:
                pass
            time.sleep(BROADCAST_INTERVAL)

        sock.close()

    def _listen_loop(self) -> None:
        """监听 UDP 广播，收集其他玩家。"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", BROADCAST_PORT))
        sock.settimeout(1.0)

        while self._running:
            try:
                data, addr = sock.recvfrom(4096)
                parsed = parse_message(data.decode("utf-8"))
                if parsed is None:
                    continue
                msg_type, payload = parsed
                if msg_type == "DISCOVER":
                    pid = payload.get("player_id", "")
                    if pid and pid != self._my_id:
                        with self._lock:
                            self._players[pid] = {
                                "name": payload.get("player_name", "未知"),
                                "ip": payload.get("ip", addr[0]),
                                "last_seen": time.time(),
                            }
            except socket.timeout:
                continue
            except Exception:
                continue

        sock.close()
