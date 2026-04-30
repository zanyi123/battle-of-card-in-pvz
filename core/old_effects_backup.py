# ⚠️ 已废弃，备份于新系统实现前
# 新系统请使用：core/effect_registry.py + core/skill_registry.py + core/effect_executor.py
# 本文件仅作历史存档，勿在新功能中引用。

"""core/effects.py - 特殊技能与效果系统（一级注册表）。

架构说明：
  - EFFECT_REGISTRY：效果处理函数字典，键为 effect_id 前缀（全大写）。
  - 每个函数签名：apply_xxx(state, player_key, card, effect_id, logs) -> None
  - 函数直接修改 state["players"][player_key]["buffs"]（列表结构）并向 logs 追加记录。
  - Buff 数据结构：{"type": str, "value": int, "duration": int, "icon_code": str}
      - duration=-1 → 护盾类，永久直到耗尽（每次伤害计算后扣减）
      - duration=1+ → 其他类，每回合结束递减 1，归零移除
  - icon_code：buff 类型缩写（shield/shield/heal/dmg_reduce/mana_up），用于渲染图标匹配
  - 触发时机：卡牌成功打出后立即调用，不等待结算阶段。
  - 编码前缀映射：
      FA / MAGE  → 法师效果（EFF_MAGE_BURN_*）
      SH / ARCHER → 射手效果
      TK / TANK   → 坦克效果
      FU / SUPPORT → 辅助效果（HEAL_*、SHIELD_*、MANA_UP_*、DMG_REDUCE_*）
  - 与伤害计算集成：
      - 护盾：_apply_damage 从 buffs 列表中聚合所有 type=="shield" 的 value 后扣减
      - 减伤：_apply_damage 从 buffs 列表中聚合所有 type=="dmg_reduce" 的 value 后乘算
"""
from __future__ import annotations

from typing import Any, Callable


# ── Buff 辅助函数 ─────────────────────────────────────────────────

def _get_player(state: dict[str, Any], player_key: str) -> dict[str, Any]:
    """安全获取玩家状态字典，不存在则初始化。"""
    return state.setdefault("players", {}).setdefault(
        player_key,
        {"hp": 10, "max_hp": 10, "max_mana": 5, "current_mana": 5, "buffs": []},
    )


def _ensure_buffs_list(player_state: dict[str, Any]) -> list[dict[str, Any]]:
    """确保 buffs 字段为列表结构（兼容旧版字典格式）。"""
    raw = player_state.get("buffs", [])
    if isinstance(raw, list):
        return raw
    # 兼容旧版字典格式 {"shield": 3, "heal_over_time": 0}
    converted: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        if int(raw.get("shield", 0)) > 0:
            converted.append({
                "type": "shield",
                "value": int(raw["shield"]),
                "duration": -1,
                "icon_code": "shield",
            })
        if int(raw.get("heal_over_time", 0)) > 0:
            converted.append({
                "type": "heal_over_time",
                "value": int(raw["heal_over_time"]),
                "duration": 1,
                "icon_code": "heal",
            })
    player_state["buffs"] = converted
    return converted


def _add_buff(
    player_state: dict[str, Any],
    buff_type: str,
    value: int,
    duration: int,
    icon_code: str,
) -> None:
    """向玩家 buffs 列表中追加一条 Buff。"""
    buffs = _ensure_buffs_list(player_state)
    buffs.append({
        "type": buff_type,
        "value": value,
        "duration": duration,
        "icon_code": icon_code,
    })


def _parse_value_from_effect_id(effect_id: str, card: Any, fallback_attr: str = "atk") -> int:
    """从 effect_id 末尾的数字解析效果数值，无数字则读取 card.fallback_attr。

    例：effect_id="heal_5"  → 5
        effect_id="SHIELD"  → card.atk
    """
    parts = effect_id.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    if isinstance(card, dict):
        return int(card.get(fallback_attr, 0))
    return int(getattr(card, fallback_attr, 0))


def _card_id(card: Any) -> int:
    """安全获取 card 的 id 字段。"""
    if isinstance(card, dict):
        return int(card.get("id", -1))
    return int(getattr(card, "id", -1))


# ── 4个基础效果函数 ───────────────────────────────────────────────

def apply_shield(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    effect_id: str,
    logs: list[dict[str, Any]],
) -> None:
    """SHIELD：为玩家添加护盾值 Buff（duration=-1，永久直到耗尽）。"""
    player_state = _get_player(state, player_key)
    value = _parse_value_from_effect_id(effect_id, card)
    if value <= 0:
        return
    _add_buff(player_state, "shield", value, duration=-1, icon_code="shield")
    logs.append({
        "player": player_key,
        "action": "gain_shield",
        "value": value,
        "reason": f"effect:{effect_id}",
    })


def apply_heal(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    effect_id: str,
    logs: list[dict[str, Any]],
) -> None:
    """HEAL：直接增加玩家当前 HP（不超过 max_hp），立即生效不进 Buff 列表。"""
    player_state = _get_player(state, player_key)
    value = _parse_value_from_effect_id(effect_id, card)
    if value <= 0:
        return
    current_hp = int(player_state.get("hp", 0))
    max_hp = int(player_state.get("max_hp", 10))
    new_hp = min(max_hp, current_hp + value)
    player_state["hp"] = new_hp
    actual_healed = new_hp - current_hp
    logs.append({
        "player": player_key,
        "action": "heal",
        "value": actual_healed,
        "reason": f"effect:{effect_id}",
    })


def apply_mana_up(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    effect_id: str,
    logs: list[dict[str, Any]],
) -> None:
    """MANA_UP：提高玩家 max_mana 上限并同步增加 current_mana（硬顶 10）。"""
    player_state = _get_player(state, player_key)
    value = _parse_value_from_effect_id(effect_id, card)
    if value <= 0:
        return
    MANA_HARD_CAP = 10
    old_max = int(player_state.get("max_mana", 5))
    new_max = min(old_max + value, MANA_HARD_CAP)
    gain = new_max - old_max
    player_state["max_mana"] = new_max
    current_mana = int(player_state.get("current_mana", 0))
    player_state["current_mana"] = min(new_max, current_mana + gain)
    logs.append({
        "player": player_key,
        "action": "mana_up",
        "value": gain,
        "reason": f"effect:{effect_id}",
    })


def apply_dmg_reduce(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    effect_id: str,
    logs: list[dict[str, Any]],
) -> None:
    """DMG_REDUCE：添加减伤 Buff（duration=1，本回合结束自动清理）。

    value 表示减伤百分比，例如 20 → 受到伤害 × (1 - 0.20) = 80%。
    """
    player_state = _get_player(state, player_key)
    value = _parse_value_from_effect_id(effect_id, card)
    if value <= 0:
        return
    _add_buff(player_state, "dmg_reduce", value, duration=1, icon_code="dmg_reduce")
    logs.append({
        "player": player_key,
        "action": "gain_dmg_reduce",
        "value": value,
        "reason": f"effect:{effect_id}",
    })


def apply_burn(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    effect_id: str,
    logs: list[dict[str, Any]],
) -> None:
    """BURN：法师灼烧效果，为对手添加持续伤害 debuff。"""
    opponent = "P2" if player_key == "P1" else "P1"
    opponent_state = _get_player(state, opponent)
    value = _parse_value_from_effect_id(effect_id, card, "atk")
    if value <= 0:
        value = 2  # 默认灼烧伤害
    _add_buff(opponent_state, "burn", value, duration=1, icon_code="burn")
    logs.append({
        "player": opponent,
        "action": "gain_burn",
        "value": value,
        "reason": f"effect:{effect_id}",
    })


# ── 效果注册表 ────────────────────────────────────────────────────

EffectFunc = Callable[
    [dict[str, Any], str, Any, str, list[dict[str, Any]]],
    None,
]

#: 键为 effect_id 前缀（全大写或小写），值为对应处理函数。
EFFECT_REGISTRY: dict[str, EffectFunc] = {}

# 核心效果（大写）
EFFECT_REGISTRY["SHIELD"] = apply_shield
EFFECT_REGISTRY["HEAL"] = apply_heal
EFFECT_REGISTRY["MANA_UP"] = apply_mana_up
EFFECT_REGISTRY["DMG_REDUCE"] = apply_dmg_reduce
EFFECT_REGISTRY["BURN"] = apply_burn

# 小写兼容（cards.json 中 "heal_5"、"shield_3" 等）
EFFECT_REGISTRY["heal"] = apply_heal
EFFECT_REGISTRY["shield"] = apply_shield
EFFECT_REGISTRY["mana_up"] = apply_mana_up
EFFECT_REGISTRY["dmg_reduce"] = apply_dmg_reduce
EFFECT_REGISTRY["burn"] = apply_burn

# 新编码前缀兼容（FA/SH/TK/FU → 对应阵营效果）
EFFECT_REGISTRY["EFF_MAGE_BURN"] = apply_burn        # EFF_MAGE_BURN_001 → 灼烧
EFFECT_REGISTRY["EFF_ARCHER_PIERCE"] = apply_burn     # EFF_ARCHER_PIERCE_001 → 穿透灼烧


# ── 统一调用入口 ──────────────────────────────────────────────────

def dispatch_effect(
    effect_id: str,
    state: dict[str, Any],
    player_key: str,
    card: Any,
    logs: list[dict[str, Any]],
) -> bool:
    """根据 effect_id 前缀查找注册表并调用对应函数。

    匹配策略：
      1. 完整 effect_id 作为 key
      2. 下划线分割的第一段（如 "heal_5" → "heal"）
      3. 连续下划线前缀（如 "EFF_MAGE_BURN_001" → 逐级尝试 "EFF_MAGE_BURN"、"EFF_MAGE"、"EFF"）

    返回 True 表示成功匹配并执行，False 表示未找到注册处理函数。
    """
    if not effect_id:
        return False

    # 先尝试完整 key
    if effect_id in EFFECT_REGISTRY:
        EFFECT_REGISTRY[effect_id](state, player_key, card, effect_id, logs)
        return True

    # 尝试多级前缀匹配
    parts = effect_id.split("_")
    for i in range(len(parts) - 1, 0, -1):
        prefix = "_".join(parts[:i])
        if prefix in EFFECT_REGISTRY:
            EFFECT_REGISTRY[prefix](state, player_key, card, effect_id, logs)
            return True
        prefix_upper = prefix.upper()
        if prefix_upper in EFFECT_REGISTRY:
            EFFECT_REGISTRY[prefix_upper](state, player_key, card, effect_id, logs)
            return True

    # 最后尝试单段前缀
    first = parts[0]
    if first in EFFECT_REGISTRY:
        EFFECT_REGISTRY[first](state, player_key, card, effect_id, logs)
        return True
    if first.upper() in EFFECT_REGISTRY:
        EFFECT_REGISTRY[first.upper()](state, player_key, card, effect_id, logs)
        return True

    return False


# ── Buff 查询辅助（供 resolution_engine 使用）─────────────────────

def sum_buff_value(player_state: dict[str, Any], buff_type: str) -> int:
    """聚合玩家 buffs 列表中所有指定类型的 value 之和。"""
    buffs = _ensure_buffs_list(player_state)
    return sum(int(b.get("value", 0)) for b in buffs if b.get("type") == buff_type)


def consume_shield(player_state: dict[str, Any], damage: int) -> tuple[int, int]:
    """用护盾吸收伤害，就地修改 buffs 列表，返回 (absorbed, remaining_damage)。"""
    buffs = _ensure_buffs_list(player_state)
    absorbed = 0
    remaining = damage
    for buff in buffs:
        if buff.get("type") != "shield" or remaining <= 0:
            continue
        shield_val = int(buff.get("value", 0))
        take = min(remaining, shield_val)
        buff["value"] = shield_val - take
        absorbed += take
        remaining -= take
    # 清除已耗尽的护盾
    player_state["buffs"] = [b for b in buffs if not (b.get("type") == "shield" and int(b.get("value", 0)) <= 0)]
    return absorbed, remaining


def tick_buffs(player_state: dict[str, Any]) -> list[dict[str, Any]]:
    """回合结束时递减所有 duration > 0 的 Buff，清除 duration 归零的过期 Buff。

    规则：
      - duration=-1 → 永久类（护盾），不递减
      - duration=1 → 递减后归零，移除
      - duration>1 → 递减 1，保留

    返回本次清理掉的 Buff 列表（用于日志）。
    """
    buffs = _ensure_buffs_list(player_state)
    expired: list[dict[str, Any]] = []
    surviving: list[dict[str, Any]] = []

    for buff in buffs:
        duration = int(buff.get("duration", 0))
        buff_type = buff.get("type", "")

        if duration == -1:
            # 永久类（护盾），不递减
            surviving.append(buff)
            continue

        if duration <= 0:
            # duration=0 且非永久 → 安全回退，保留
            surviving.append(buff)
            continue

        new_duration = duration - 1
        if new_duration <= 0:
            expired.append(buff)
        else:
            buff["duration"] = new_duration
            surviving.append(buff)

    player_state["buffs"] = surviving
    return expired
