"""core/player_profile.py - 玩家档案管理（本地 JSON 存储，无数据库）。

功能：
  - 首次启动自动生成 UUID4 作为 player_id
  - 首次启动弹出注册界面让玩家输入名字
  - 档案存储在用户数据目录（打包后 ~/.pvz_card_game/，开发模式项目根目录）
  - 提供加载 / 保存 / 检测是否已注册 等接口
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from utils.path_utils import get_user_data_dir


def _get_profile_file() -> Path:
    """返回档案文件路径（用户数据目录下，跨版本持久化）。"""
    return get_user_data_dir() / "player_profile.json"


def get_profile_path() -> Path:
    """返回档案文件路径。"""
    return _get_profile_file()


def load_profile() -> dict[str, Any]:
    """加载玩家档案，文件不存在则返回空字典。"""
    p = _get_profile_file()
    if not p.exists():
        return {}
    try:
        raw = p.read_text(encoding="utf-8")
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def save_profile(profile: dict[str, Any]) -> None:
    """保存玩家档案到 JSON 文件。"""
    _get_profile_file().write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_registered() -> bool:
    """检查玩家是否已注册（有 id 和 name）。"""
    p = load_profile()
    return bool(p.get("player_id")) and bool(p.get("player_name"))


def create_profile(player_name: str) -> dict[str, Any]:
    """创建新玩家档案（UUID4 + 名字）。

    Returns:
        新创建的档案字典
    """
    profile: dict[str, Any] = {
        "player_id": str(uuid.uuid4()),
        "player_name": player_name.strip(),
    }
    save_profile(profile)
    return profile


def get_player_id() -> str:
    """获取当前玩家 ID（未注册返回空字符串）。"""
    return load_profile().get("player_id", "")


def get_player_name() -> str:
    """获取当前玩家名字（未注册返回空字符串）。"""
    return load_profile().get("player_name", "")


def get_display_id() -> str:
    """获取用于显示的短 ID（UUID 前 8 位）。"""
    full_id = get_player_id()
    if not full_id:
        return ""
    return full_id[:8].upper()
