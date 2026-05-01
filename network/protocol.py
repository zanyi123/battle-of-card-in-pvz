"""network/protocol.py - 联机通信协议定义。

消息格式：JSON 字符串，以换行符 \\n 分隔。

所有消息结构：
  {
    "type": "消息类型",
    "payload": { ... }
  }

消息类型：
  ┌─────────────────────┬───────────────────────────────────────┐
  │ type                │ 用途                                  │
  ├─────────────────────┼───────────────────────────────────────┤
  │ DISCOVER            │ 局域网广播：发现玩家                   │
  │ DISCOVER_RESP       │ 响应发现：返回自己信息                 │
  │ INVITE              │ 邀请对局                              │
  │ INVITE_ACCEPT       │ 接受邀请                              │
  │ INVITE_REJECT       │ 拒绝邀请                              │
  │ GAME_STATE          │ Host → Client 同步完整游戏状态         │
  │ PLAYER_ACTION       │ Client → Host 发送玩家操作             │
  │ GAME_OVER           │ 游戏结束                              │
  │ CHAT                │ 聊天消息（预留）                       │
  │ HEARTBEAT           │ 心跳检测                              │
  │ GOODBYE             │ 断开连接                              │
  └─────────────────────┴───────────────────────────────────────┘
"""
from __future__ import annotations

import json
from typing import Any

# ── 消息类型常量 ─────────────────────────────────────────────

DISCOVER        = "DISCOVER"
DISCOVER_RESP   = "DISCOVER_RESP"
INVITE          = "INVITE"
INVITE_ACCEPT   = "INVITE_ACCEPT"
INVITE_REJECT   = "INVITE_REJECT"
GAME_STATE      = "GAME_STATE"
PLAYER_ACTION   = "PLAYER_ACTION"
GAME_OVER       = "GAME_OVER"
CHAT            = "CHAT"
HEARTBEAT       = "HEARTBEAT"
GOODBYE         = "GOODBYE"

# ── 局域网配置 ───────────────────────────────────────────────

LAN_PORT = 9988            # 通信端口
BROADCAST_PORT = 9989      # 广播发现端口
BROADCAST_INTERVAL = 2.0   # 广播间隔（秒）
DISCOVER_TIMEOUT = 3.0     # 发现超时（秒）


def make_message(msg_type: str, payload: dict[str, Any] | None = None) -> str:
    """构造 JSON 消息（带换行符结尾）。"""
    msg = {"type": msg_type, "payload": payload or {}}
    return json.dumps(msg, ensure_ascii=False) + "\n"


def parse_message(data: str) -> tuple[str, dict[str, Any]] | None:
    """解析 JSON 消息。

    Returns:
        (type, payload) 或 None（解析失败）
    """
    data = data.strip()
    if not data:
        return None
    try:
        msg = json.loads(data)
        return msg.get("type", ""), msg.get("payload", {})
    except (json.JSONDecodeError, AttributeError):
        return None
