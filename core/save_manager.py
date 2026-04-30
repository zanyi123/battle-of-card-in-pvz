"""core/save_manager.py - 存档管理器（成就 + 统计）。

完全基于 save_data.json 文件持久化，无数据库依赖。
- 加载/保存逻辑包裹 try-except，文件损坏时自动重置为空结构。
- used_card_ids 跨局累加，永不重置（静态开关）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils.path_utils import get_save_data_path


# ── 默认存档结构 ──────────────────────────────────────────────────
_SAVE_FILE: Path = get_save_data_path()

_DEFAULT_ACHIEVEMENTS: dict[str, bool] = {
    "first_win": False,        # 初战告捷
    "endurance_20": False,     # 坚韧不拔（>=20回合获胜）
    "card_master": False,      # 卡牌大师（54张全用过）
    "desperate_survival": False,  # 绝境逢生（补救翻盘且获胜）
    "speed_run_10": False,     # 速战速决（<=10回合获胜）
}

_DEFAULT_STATS: dict[str, Any] = {
    "used_card_ids": [],       # 静态开关：用过的卡牌ID永久保留
    "current_game_rounds": 0,  # 本局存活回合数（每局重置）
    "remedy_flipped": False,   # 本局是否补救成功并翻盘（每局重置）
}

_DEFAULT_SAVE_DATA: dict[str, Any] = {
    "achievements": dict(_DEFAULT_ACHIEVEMENTS),
    "stats": dict(_DEFAULT_STATS),
}

# ── 成就定义（id → 显示名）─────────────────────────────────────────
ACHIEVEMENT_NAMES: dict[str, str] = {
    "first_win": "初战告捷",
    "endurance_20": "坚韧不拔",
    "card_master": "卡牌大师",
    "desperate_survival": "绝境逢生",
    "speed_run_10": "速战速决",
}

ACHIEVEMENT_DESCRIPTIONS: dict[str, str] = {
    "first_win": "首次赢得对战",
    "endurance_20": "在20回合或以上后获胜",
    "card_master": "累计使用过全部54种卡牌",
    "desperate_survival": "在补救回合中翻盘并最终获胜",
    "speed_run_10": "在10回合或以内击败对手",
}


def load_save_data() -> dict[str, Any]:
    """加载存档数据。文件不存在或损坏时返回默认结构。"""
    if not _SAVE_FILE.exists():
        return _deep_copy_default()
    try:
        raw_text = _SAVE_FILE.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[SaveManager] 存档文件损坏，自动重置: {exc}")
        return _deep_copy_default()

    # 确保结构完整（向后兼容：缺少的字段用默认值补齐）
    if not isinstance(data, dict):
        return _deep_copy_default()
    if "achievements" not in data or not isinstance(data["achievements"], dict):
        data["achievements"] = dict(_DEFAULT_ACHIEVEMENTS)
    else:
        for key, default_val in _DEFAULT_ACHIEVEMENTS.items():
            data["achievements"].setdefault(key, default_val)
    if "stats" not in data or not isinstance(data["stats"], dict):
        data["stats"] = dict(_DEFAULT_STATS)
    else:
        for key, default_val in _DEFAULT_STATS.items():
            data["stats"].setdefault(key, default_val)

    # used_card_ids 必须是列表
    if not isinstance(data["stats"].get("used_card_ids"), list):
        data["stats"]["used_card_ids"] = []
    # current_game_rounds 必须是整数
    data["stats"]["current_game_rounds"] = int(data["stats"].get("current_game_rounds", 0))
    # remedy_flipped 必须是布尔
    data["stats"]["remedy_flipped"] = bool(data["stats"].get("remedy_flipped", False))

    return data


def save_save_data(data: dict[str, Any]) -> None:
    """将存档数据持久化到 save_data.json。"""
    try:
        _SAVE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"[SaveManager] 存档写入失败: {exc}")


def reset_per_game_stats(data: dict[str, Any]) -> None:
    """每局开始时重置本局统计数据（不重置 achievements 和 used_card_ids）。"""
    data["stats"]["current_game_rounds"] = 0
    data["stats"]["remedy_flipped"] = False


def create_fresh_game_stats() -> dict[str, Any]:
    """创建本局独立的运行时 stats（引用 save_data 中的 used_card_ids）。"""
    return {
        "used_card_ids": [],       # 每局独立引用，结算时合并回 save_data
        "current_game_rounds": 0,
        "remedy_flipped": False,
    }


def merge_game_stats_to_save(
    game_stats: dict[str, Any],
    save_data: dict[str, Any],
) -> None:
    """将本局运行时 stats 合并回 save_data（used_card_ids 去重追加）。

    - used_card_ids: 去重追加，永不覆盖或清空
    - current_game_rounds / remedy_flipped: 直接覆写（下一局会重置）
    """
    save_stats = save_data["stats"]
    # 去重追加 used_card_ids
    existing_ids: set[int] = set(save_stats.get("used_card_ids", []))
    new_ids = game_stats.get("used_card_ids", [])
    for cid in new_ids:
        int_cid = int(cid)
        if int_cid not in existing_ids:
            save_stats.setdefault("used_card_ids", []).append(int_cid)
            existing_ids.add(int_cid)
    # 本局数据覆写
    save_stats["current_game_rounds"] = int(game_stats.get("current_game_rounds", 0))
    save_stats["remedy_flipped"] = bool(game_stats.get("remedy_flipped", False))


def check_achievements(state: dict[str, Any], save_data: dict[str, Any]) -> list[str]:
    """判定本局成就，返回新解锁列表。

    仅在 P1 获胜时调用。解锁后立即写入 save_data。
    """
    unlocked: list[str] = []
    ach = save_data["achievements"]
    stats = state.get("stats", {})

    # 1. 初战告捷
    if not ach.get("first_win", False):
        ach["first_win"] = True
        unlocked.append("初战告捷")

    rounds = int(stats.get("current_game_rounds", 0))

    # 2. 速战速决（≤10回合）
    if not ach.get("speed_run_10", False) and rounds <= 10:
        ach["speed_run_10"] = True
        unlocked.append("速战速决")

    # 3. 坚韧不拔（≥20回合）
    if not ach.get("endurance_20", False) and rounds >= 20:
        ach["endurance_20"] = True
        unlocked.append("坚韧不拔")

    # 4. 绝境逢生（补救成功且获胜）
    if not ach.get("desperate_survival", False) and stats.get("remedy_flipped", False):
        ach["desperate_survival"] = True
        unlocked.append("绝境逢生")

    # 5. 卡牌大师（54张全用过，含 save_data 中的历史记录）
    all_used = set(save_data["stats"].get("used_card_ids", []))
    game_used = stats.get("used_card_ids", [])
    for cid in game_used:
        all_used.add(int(cid))
    if not ach.get("card_master", False) and len(all_used) >= 54:
        ach["card_master"] = True
        unlocked.append("卡牌大师")

    return unlocked


def _deep_copy_default() -> dict[str, Any]:
    """返回默认存档结构的深拷贝。"""
    import copy
    return copy.deepcopy(_DEFAULT_SAVE_DATA)
