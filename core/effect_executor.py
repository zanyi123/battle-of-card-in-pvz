"""core/effect_executor.py - 三级技能系统：三级执行引擎。

架构说明：
  三级架构：
    一级  ── effect_registry.py：EFFECT_CATEGORIES，14个效果大类
    二级  ── skill_registry.py：SKILL_REGISTRY，effect_id → 类别+参数
    三级（本文件）── EffectExecutor，根据 handler_key 执行具体游戏逻辑

本文件职责：
  - 提供统一的 execute(state, player_key, card, logs) 入口
  - 根据 skill_id → handler_key → 具体执行函数的三级派发链
  - 所有执行函数直接修改 state，并向 logs 追加记录
  - 与旧系统（core/effects.py）完全隔离，不混用

执行函数签名统一为：
    _exec_xxx(
        state: dict,
        player_key: str,
        card: Any,
        skill_data: dict,
        logs: list
    ) -> None

兼容性说明：
  - 本模块可独立运行，不依赖 core/effects.py（旧系统）
  - state["players"][player_key]["buffs"] 列表结构与旧系统一致
  - 同时提供 dispatch_effect_new() 供 resolution_engine 使用
"""
from __future__ import annotations

import random
from typing import Any, Callable

import pygame

from core.effect_registry import EFFECT_CATEGORIES
from core.skill_registry import SKILL_REGISTRY, get_skill_data


# ── 内部辅助函数 ──────────────────────────────────────────────────

def _get_player_state(state: dict[str, Any], player_key: str) -> dict[str, Any]:
    """安全获取玩家状态，不存在时初始化默认值。"""
    return state.setdefault("players", {}).setdefault(
        player_key,
        {"hp": 10, "max_hp": 10, "max_mana": 5, "current_mana": 5, "buffs": []},
    )


def _ensure_buffs(player_state: dict[str, Any]) -> list[dict[str, Any]]:
    """确保 buffs 字段为列表，兼容旧版字典格式。"""
    raw = player_state.get("buffs", [])
    if isinstance(raw, list):
        return raw
    # 兼容旧版字典格式
    converted: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        if int(raw.get("shield", 0)) > 0:
            converted.append({
                "type": "shield", "value": int(raw["shield"]),
                "duration": -1, "icon_code": "shield",
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
    """向玩家 buffs 列表追加一条 Buff。"""
    buffs = _ensure_buffs(player_state)
    buffs.append({
        "type": buff_type,
        "value": value,
        "duration": duration,
        "icon_code": icon_code,
    })


def _get_opponent_key(player_key: str) -> str:
    """返回对手的 player_key。"""
    return "P2" if player_key == "P1" else "P1"


def _card_val(card: Any, key: str, default: Any = 0) -> Any:
    """安全读取卡牌字段，兼容 dict 和对象两种格式。"""
    if isinstance(card, dict):
        return card.get(key, default)
    return getattr(card, key, default)


def _get_hp(state: dict[str, Any], player_key: str) -> int:
    """获取玩家当前 HP。"""
    ps = _get_player_state(state, player_key)
    return int(ps.get("hp", 10))


def _set_hp(state: dict[str, Any], player_key: str, hp: int) -> None:
    """设置玩家 HP（不做范围限制，由调用方保证）。"""
    ps = _get_player_state(state, player_key)
    ps["hp"] = int(hp)


def _clamp_hp(state: dict[str, Any], player_key: str, hp: int) -> int:
    """将 HP 钳制在 [0, max_hp]，并写入 state，返回最终值。"""
    ps = _get_player_state(state, player_key)
    max_hp = int(ps.get("max_hp", 10))
    clamped = max(0, min(max_hp, hp))
    ps["hp"] = clamped
    return clamped


def _log(
    logs: list[dict[str, Any]],
    player: str,
    action: str,
    value: int | float,
    reason: str,
) -> None:
    """向 logs 追加一条记录。"""
    logs.append({"player": player, "action": action, "value": value, "reason": reason})


def _push_toast(state: dict[str, Any], text: str) -> None:
    """向战报播报队列推送一条消息。"""
    toasts = state.setdefault("toasts", [])
    toasts.append({"text": text, "time": pygame.time.get_ticks()})


# ── 各 handler_key 对应的执行函数 ────────────────────────────────

def _exec_block_one_turn(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """SHIELD_TURN：为玩家添加"本回合完全免疫一次伤害"的护盾标记。

    实现：添加一个 type="block_turn" 的 Buff（duration=1，本回合结束自动清除）。
    伤害结算时，resolution_engine 检查此 Buff，若存在则跳过该次伤害计算。
    """
    ps = _get_player_state(state, player_key)
    _add_buff(ps, "block_turn", 1, duration=1, icon_code="block")
    _log(logs, player_key, "gain_block_turn", 1, "effect:SHIELD_TURN")


def _exec_discard_by_faction(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """DISCARD_FA：从对手手牌中随机弃置指定阵营的一张牌。

    skill_data["faction_filter"] 指定目标阵营（如 "法"）。
    """
    opponent_key = _get_opponent_key(player_key)
    faction_filter = str(skill_data.get("faction_filter", ""))

    hands = state.get("hands", {})
    opponent_hand: list[Any] = list(hands.get(opponent_key, []))

    # 筛选目标阵营的牌
    candidates = [
        (idx, c) for idx, c in enumerate(opponent_hand)
        if _card_val(c, "faction", "") == faction_filter
    ]

    if not candidates:
        _log(logs, player_key, "discard_no_target", 0, f"faction:{faction_filter}")
        return

    idx, target_card = random.choice(candidates)
    opponent_hand.pop(idx)

    # 更新 state 中对手手牌
    if isinstance(hands, dict):
        hands[opponent_key] = opponent_hand
    else:
        state["hands"] = {**state.get("hands", {}), opponent_key: opponent_hand}

    card_name = str(_card_val(target_card, "name", "未知"))
    _log(logs, opponent_key, "discard_card", 1, f"discard_fa:{card_name}")
    _log(logs, player_key, "discard_effect_success", 1, f"faction:{faction_filter}")
    _push_toast(state, f"🗑️ 对方的 {card_name} 被作废！")


def _exec_gain_mana(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """MANA_N：增加精力上限 N 点（硬顶10）。"""
    gain = int(skill_data.get("value", 0))
    if gain <= 0:
        return
    ps = _get_player_state(state, player_key)
    old_max = int(ps.get("max_mana", 5))
    new_max = min(10, old_max + gain)
    actual = new_max - old_max
    ps["max_mana"] = new_max
    ps["current_mana"] = new_max  # 同步回满
    _add_buff(ps, "mana_boost", actual, duration=-1, icon_code="mana")
    card_name = str(_card_val(card, "name", "未知"))
    _log(logs, player_key, "gain_mana", actual, f"effect:MANA_{gain}")
    _push_toast(state, f"✨ {card_name} 精力上限 +{actual}（{old_max}→{new_max}）")


def _exec_add_shield(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """SHIELD_6：为玩家添加指定数值护盾（duration=-1，永久直到耗尽）。"""
    value = int(skill_data.get("value", 0))
    if value <= 0:
        return
    ps = _get_player_state(state, player_key)
    _add_buff(ps, "shield", value, duration=-1, icon_code="shield")
    _log(logs, player_key, "gain_shield", value, "effect:SHIELD_6")


def _exec_heal_to_value(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """HEAL_8：将血量恢复至指定目标值（若当前血量低于该值则恢复，否则不变）。"""
    target_hp = int(skill_data.get("value", 8))
    ps = _get_player_state(state, player_key)
    current_hp = int(ps.get("hp", 0))
    max_hp = int(ps.get("max_hp", 10))

    new_hp = min(max_hp, max(current_hp, target_hp))
    actual_healed = new_hp - current_hp
    ps["hp"] = new_hp

    _log(logs, player_key, "heal_to_value", actual_healed, "effect:HEAL_8")
    _log(logs, player_key, "set_hp", new_hp, "after_heal_to_value")


def _exec_heal_flat(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """HEAL_FLAT：恢复固定点数生命值（如HEAL_3=回血+3）。"""
    heal_amount = int(skill_data.get("value", 0))
    ps = _get_player_state(state, player_key)
    current_hp = int(ps.get("hp", 0))
    max_hp = int(ps.get("max_hp", 10))

    new_hp = min(max_hp, current_hp + heal_amount)
    actual_healed = new_hp - current_hp
    ps["hp"] = new_hp

    card_name = str(_card_val(card, "name", "未知"))
    _log(logs, player_key, "heal_flat", actual_healed, f"effect:HEAL_{heal_amount}")
    _push_toast(state, f"💚 {card_name} 恢复了 {actual_healed} 点生命")


def _exec_disable_atk(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """ATK_DISABLE：使对方本回合出牌攻击值失效（atk 被置为 0）。

    实现：在 state["temp"] 中标记对手的攻击被禁用，
    resolution_engine 在伤害计算前检查此标记。
    """
    opponent_key = _get_opponent_key(player_key)
    temp = state.setdefault("temp", {})
    temp[f"{opponent_key}_atk_disabled"] = True
    _log(logs, opponent_key, "atk_disabled", 1, "effect:ATK_DISABLE")


def _exec_silence_opponent(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """SILENCE：该回合对手无法打出任何卡牌。

    实现：在 state["temp"] 中标记对手被沉默。
    state_machine.play_card 检查此标记，若存在则拒绝出牌。
    """
    opponent_key = _get_opponent_key(player_key)
    temp = state.setdefault("temp", {})
    temp[f"{opponent_key}_silenced"] = True
    _log(logs, opponent_key, "silenced", 1, "effect:SILENCE")


def _exec_armor_pierce(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """ARMOR_PIERCE：破甲，本回合攻击无视对手护盾。

    实现：在 state["temp"] 中标记己方破甲，
    resolution_engine 在护盾吸收步骤前检查此标记，跳过护盾计算。
    """
    temp = state.setdefault("temp", {})
    temp[f"{player_key}_armor_pierce"] = True
    _log(logs, player_key, "armor_pierce", 1, "effect:ARMOR_PIERCE")


# 阵营克制关系：键阵营克制值阵营（循环克制，辅助无克制）
# 法师(FA) → 克制 → 射手(SH)
# 射手(SH) → 克制 → 坦克(TK)
# 坦克(TK) → 克制 → 法师(FA)
_FACTION_COUNTER: dict[str, str] = {
    "法": "射",   # 法师克制射手
    "射": "坦",   # 射手克制坦克
    "坦": "法",   # 坦克克制法师
    "辅": "",    # 辅助无克制
}


def _get_main_card_faction(state: dict[str, Any], player_key: str, played_cards: list[Any] | None = None) -> str | None:
    """获取玩家本回合打出的主卡阵营。"""
    # 优先使用传入的 played_cards 参数
    if played_cards:
        for c in played_cards:
            if _card_val(c, "type", "") == "主":
                return str(_card_val(c, "faction", ""))
    # 从 state["played_cards"] 中查找（resolve_clash 使用的 key）
    played = state.get("played_cards", {})
    cards = played.get(player_key, [])
    for c in cards:
        if _card_val(c, "type", "") == "主":
            return str(_card_val(c, "faction", ""))
    return None


def _exec_counter_atk_zero(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """COUNTER_ATK_ZERO：洋蓟（射手）克制法师，被法师攻击时对方atk清0。

    本卡阵营：射（SH）；法师克制射手，但洋蓟反制：能克制它的阵营（法师）攻击时atk清0。
    """
    card_id = int(_card_val(card, "id", -1))
    
    # 仅对飞镖洋蓟（ID:32）生效
    if card_id != 32:
        return
    
    my_faction = str(_card_val(card, "faction", ""))
    if my_faction != "射":
        return
    
    opponent_key = _get_opponent_key(player_key)
    opponent_faction = _get_main_card_faction(state, opponent_key)

    # 法师克制射手 → 被法师攻击时触发，对方atk清0
    if opponent_faction == "法":
        temp = state.setdefault("temp", {})
        temp[f"{opponent_key}_main_atk_zero"] = True
        card_name = str(_card_val(card, "name", "未知"))
        _log(logs, opponent_key, "counter_atk_zero", 1, "effect:COUNTER_ATK_ZERO(fa_attacks_dart) ")
        _push_toast(state, f"🛡️ {card_name} 发动克制：法师阵营攻击清0！")
    else:
        _log(logs, player_key, "counter_atk_zero_skip", 0,
             f"opponent_faction:{opponent_faction} != 法")


def _exec_counter_dmg_multiplier(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """COUNTER_DMG_X3：攻击坦克阵营时，基础伤害×3，叠加溢出伤害（西瓜投手专用）。

    本卡（射手）克制坦克阵营；若攻击坦克，则本卡伤害×3，并计算溢出伤害。
    """
    multiplier = int(skill_data.get("value", 3))
    my_faction = str(_card_val(card, "faction", ""))
    card_id = int(_card_val(card, "id", -1))
    
    # 仅对西瓜投手（ID:33）生效
    if card_id != 33:
        return
    
    if my_faction != "射":
        return
    
    opponent_key = _get_opponent_key(player_key)
    opponent_faction = _get_main_card_faction(state, opponent_key)

    # 当攻击坦克阵营时触发
    if opponent_faction == "坦":
        temp = state.setdefault("temp", {})
        current_mult = float(temp.get(f"{player_key}_dmg_multiplier", 1.0))
        temp[f"{player_key}_dmg_multiplier"] = current_mult * multiplier
        # 标记为克制攻击，用于计算溢出伤害
        temp[f"{player_key}_countering"] = True
        temp[f"{player_key}_countering_faction"] = "坦"
        card_name = str(_card_val(card, "name", "未知"))
        _log(logs, player_key, "counter_dmg_multiplier", multiplier,
             f"effect:COUNTER_DMG_X3(opponent=tank)")
        _push_toast(state, f"🎯 {card_name} 克制坦克阵营，伤害×{multiplier}！")
    else:
        _log(logs, player_key, "counter_dmg_skip", 0,
             f"opponent_faction:{opponent_faction} != tank")


def _exec_dmg_buff_2x(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """NO_COUNTER_DMG_X2：毁灭菇（法师），被坦克克制；对方不是坦克时伤害×2。

    毁灭菇是法师阵营，坦克克制法师。当对方不是克制它的阵营（非坦克）时，伤害×2。
    """
    multiplier = int(skill_data.get("value", 2))
    my_faction = str(_card_val(card, "faction", ""))
    card_id = int(_card_val(card, "id", -1))
    
    # 仅对毁灭菇（ID:34）生效
    if card_id != 34:
        return
    
    if my_faction != "法":
        return
    
    opponent_key = _get_opponent_key(player_key)
    opponent_faction = _get_main_card_faction(state, opponent_key)

    # 当对方不是克制毁灭菇的阵营（非坦克）时触发
    if opponent_faction != "坦":
        temp = state.setdefault("temp", {})
        current_mult = float(temp.get(f"{player_key}_dmg_multiplier", 1.0))
        temp[f"{player_key}_dmg_multiplier"] = current_mult * multiplier
        # 标记为克制攻击，用于计算溢出伤害
        temp[f"{player_key}_countering"] = True
        temp[f"{player_key}_countering_faction"] = opponent_faction
        card_name = str(_card_val(card, "name", "未知"))
        _log(logs, player_key, "dmg_buff_2x", multiplier,
             f"effect:DMG_BUFF_2X(opponent={opponent_faction})")
        _push_toast(state, f"💥 {card_name} 攻击{opponent_faction}阵营，伤害×{multiplier}！")
    else:
        _log(logs, player_key, "dmg_buff_2x_skip", 0,
             f"opponent_faction:{opponent_faction} == 坦, no_multiplier")


def _exec_steal_random_card(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """STEAL_CARD：从对手手牌中随机抽一张，加入己方手牌。"""
    opponent_key = _get_opponent_key(player_key)
    hands = state.get("hands", {})
    opponent_hand: list[Any] = list(hands.get(opponent_key, []))
    my_hand: list[Any] = list(hands.get(player_key, []))

    if not opponent_hand:
        _log(logs, player_key, "steal_no_target", 0, "opponent_hand_empty")
        return

    idx = random.randrange(len(opponent_hand))
    stolen = opponent_hand.pop(idx)
    my_hand.append(stolen)

    new_hands = dict(state.get("hands", {}))
    new_hands[opponent_key] = opponent_hand
    new_hands[player_key] = my_hand
    state["hands"] = new_hands

    card_name = str(_card_val(stolen, "name", "未知"))
    _log(logs, player_key, "steal_card", 1, f"stolen:{card_name}")
    _log(logs, opponent_key, "card_stolen", 1, f"by:{player_key}:{card_name}")
    _push_toast(state, f"🃏 您偷到了对方的 {card_name}！")


def _exec_steal_by_faction(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """STEAL_SH：从对手手牌中随机偷一张指定阵营的牌加入己方。"""
    opponent_key = _get_opponent_key(player_key)
    faction_filter = str(skill_data.get("faction_filter", ""))
    hands = state.get("hands", {})
    opponent_hand: list[Any] = list(hands.get(opponent_key, []))
    my_hand: list[Any] = list(hands.get(player_key, []))

    candidates = [
        (idx, c) for idx, c in enumerate(opponent_hand)
        if _card_val(c, "faction", "") == faction_filter
    ]

    if not candidates:
        _log(logs, player_key, "steal_no_target", 0, f"faction:{faction_filter}")
        return

    idx, stolen = random.choice(candidates)
    opponent_hand.pop(idx)
    my_hand.append(stolen)

    new_hands = dict(state.get("hands", {}))
    new_hands[opponent_key] = opponent_hand
    new_hands[player_key] = my_hand
    state["hands"] = new_hands

    card_name = str(_card_val(stolen, "name", "未知"))
    _log(logs, player_key, "steal_faction_card", 1, f"faction:{faction_filter}:{card_name}")
    _log(logs, opponent_key, "card_stolen_faction", 1, f"by:{player_key}:{card_name}")
    _push_toast(state, f"🃏 您偷到了对方的 {card_name}！")


def _exec_cost_to_heal_combo(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """COST_TO_HEAL：将同回合同出牌的费用值之和转为等量血量回复。

    "同出牌"指同一玩家本回合 state["played"][player_key] 中除本卡外的所有牌。
    """
    played = state.get("played", {})
    my_played: list[Any] = list(played.get(player_key, []))
    this_card_id = int(_card_val(card, "id", -1))

    # 排除本卡，累加其他出牌的费用
    total_cost = sum(
        int(_card_val(c, "cost", 0))
        for c in my_played
        if int(_card_val(c, "id", -2)) != this_card_id
    )

    if total_cost <= 0:
        _log(logs, player_key, "cost_to_heal_zero", 0, "no_other_played_cards")
        return

    ps = _get_player_state(state, player_key)
    current_hp = int(ps.get("hp", 0))
    max_hp = int(ps.get("max_hp", 10))
    new_hp = min(max_hp, current_hp + total_cost)
    actual_healed = new_hp - current_hp
    ps["hp"] = new_hp

    _log(logs, player_key, "cost_to_heal", actual_healed, f"effect:COST_TO_HEAL(total_cost={total_cost})")
    _log(logs, player_key, "set_hp", new_hp, "after_cost_to_heal")


def _exec_cost_to_heal_self(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """COST_TO_HEAL_SELF：本卡自身的费用值 = 血量回复值。"""
    cost = int(_card_val(card, "cost", 0))

    if cost <= 0:
        _log(logs, player_key, "cost_to_heal_self_zero", 0, "cost_is_zero")
        return

    ps = _get_player_state(state, player_key)
    current_hp = int(ps.get("hp", 0))
    max_hp = int(ps.get("max_hp", 10))
    new_hp = min(max_hp, current_hp + cost)
    actual_healed = new_hp - current_hp
    ps["hp"] = new_hp

    _log(logs, player_key, "cost_to_heal_self", actual_healed, f"effect:COST_TO_HEAL_SELF(cost={cost})")
    _log(logs, player_key, "set_hp", new_hp, "after_cost_to_heal_self")


def _exec_atk_to_heal_opponent(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """ATK_TO_HEAL：将对方本回合出牌的攻击值之和转化为己方回复血量。

    读取对方 played_cards 中所有牌的 atk 值求和，作为回血量。
    若对方未出牌则不回血。
    """
    opponent_key = _get_opponent_key(player_key)
    opponent_played: list[Any] = state.get("played_cards", {}).get(opponent_key, [])

    total_atk = sum(int(_card_val(c, "atk", 0)) for c in opponent_played)

    if total_atk <= 0:
        _log(logs, player_key, "atk_to_heal_zero", 0, "opponent_no_played_cards")
        return

    ps = _get_player_state(state, player_key)
    current_hp = int(ps.get("hp", 0))
    max_hp = int(ps.get("max_hp", 10))
    new_hp = min(max_hp, current_hp + total_atk)
    actual_healed = new_hp - current_hp
    ps["hp"] = new_hp

    _log(logs, player_key, "atk_to_heal", actual_healed,
         f"effect:ATK_TO_HEAL(opp_played_atk={total_atk})")
    _log(logs, player_key, "set_hp", new_hp, "after_atk_to_heal")


def _exec_reflect_attack(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """REFLECT_ATK：将对方的攻击伤害完整反弹给对方。

    实现：在 state["temp"] 中标记己方启用反弹。
    resolution_engine 在伤害计算阶段检查此标记：
      - 若本方有 reflect_atk=True，则对手的伤害不作用于本方，
        而是按同等数值作用于对手自身。
    """
    temp = state.setdefault("temp", {})
    temp[f"{player_key}_reflect_atk"] = True
    _log(logs, player_key, "gain_reflect_atk", 1, "effect:REFLECT_ATK")


def _exec_boost_atk_and_heal(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """BOOST_ATK_HEAL：增加同回合出牌伤害+value，同时回复+value2生命。"""
    atk_boost = int(skill_data.get("value", 2))
    heal_val = int(skill_data.get("value2", 2))

    # 攻击增益：在 temp 中累加
    temp = state.setdefault("temp", {})
    current_boost = int(temp.get(f"{player_key}_atk_boost", 0))
    temp[f"{player_key}_atk_boost"] = current_boost + atk_boost
    _log(logs, player_key, "atk_boost", atk_boost, "effect:BOOST_ATK_HEAL")

    # 即时回血
    if heal_val > 0:
        ps = _get_player_state(state, player_key)
        current_hp = int(ps.get("hp", 0))
        max_hp = int(ps.get("max_hp", 10))
        new_hp = min(max_hp, current_hp + heal_val)
        actual_healed = new_hp - current_hp
        ps["hp"] = new_hp
        _log(logs, player_key, "heal", actual_healed, "effect:BOOST_ATK_HEAL_part2")
        _log(logs, player_key, "set_hp", new_hp, "after_boost_atk_heal")


def _exec_reduce_dmg_flat(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """REDUCE_DMG_2：对对手每张出牌减少固定点数伤害。

    实现：在 state["temp"] 中记录己方的平坦减伤值。
    resolution_engine 在计算对手造成的总伤害时，减去该值×对手出牌张数。
    """
    flat_reduce = int(skill_data.get("value", 2))
    temp = state.setdefault("temp", {})
    current_reduce = int(temp.get(f"{player_key}_flat_dmg_reduce", 0))
    temp[f"{player_key}_flat_dmg_reduce"] = current_reduce + flat_reduce
    _log(logs, player_key, "flat_dmg_reduce", flat_reduce, "effect:REDUCE_DMG_2")


def _exec_mana_up(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """MANA_UP：提高精力上限（max_mana），硬顶 10。

    同时增加等量 current_mana，确保立刻可用。
    修改直接写入 state["players"][player_key]["max_mana"]，跨回合持久化。
    """
    MANA_HARD_CAP = 10
    value = int(skill_data.get("value", 1))
    if value <= 0:
        return

    ps = _get_player_state(state, player_key)
    old_max = int(ps.get("max_mana", 5))
    new_max = min(old_max + value, MANA_HARD_CAP)
    gain = new_max - old_max

    ps["max_mana"] = new_max
    # 同步增加当前精力
    current_mana = int(ps.get("current_mana", 0))
    ps["current_mana"] = min(new_max, current_mana + gain)

    _log(logs, player_key, "mana_up", gain, f"effect:MANA_UP({old_max}→{new_max})")
    _push_toast(state, f"☀️ 精力上限提升 {gain} 点（{old_max} → {new_max}）")


# 向日葵/阳光菇系列卡牌 ID → 精力提升值映射（effect_id 为空时的兜底）
_SUNFLOWER_MANA_MAP: dict[int, int] = {
    1: 1,   # 向日葵：精力+1（cost=1，主卡，无effect_id）
    27: 1,  # 阳光菇：精力+1（cost=2，主卡，无effect_id）
    42: 1,  # 向日葵歌手：精力+1（cost=2，限制卡，无effect_id）
}

# 莲小蓬系列：辅助增伤（effect_id 为空时的兜底）
_SPECIAL_SUPPORT_BUFF_MAP: dict[int, dict[str, Any]] = {
    30: {"handler": "support_dmg_multiplier", "value": 3},
    # 莲小蓬：有辅助时伤害×3
}


def _exec_support_dmg_multiplier(
    state: dict[str, Any],
    player_key: str,
    card: Any,
    skill_data: dict[str, Any],
    logs: list[dict[str, Any]],
) -> None:
    """SUPPORT_DMG_MULTIPLIER：若同回合有辅助卡同出，伤害×multiplier。

    实现：检查 played_cards 中是否有 type="辅" 的卡，
    若有则在 temp 中设置 dmg_multiplier。
    """
    multiplier = int(skill_data.get("value", 3))
    played = state.get("played_cards", {})
    my_played: list[Any] = list(played.get(player_key, []))

    has_support = any(str(_card_val(c, "type", "")) == "辅" for c in my_played)

    if has_support:
        temp = state.setdefault("temp", {})
        current_mult = float(temp.get(f"{player_key}_dmg_multiplier", 1.0))
        temp[f"{player_key}_dmg_multiplier"] = current_mult * multiplier
        card_name = str(_card_val(card, "name", "未知"))
        _log(logs, player_key, "support_dmg_multiplier", multiplier,
             f"effect:SUPPORT_DMG_MULTIPLIER({card_name}×{multiplier})")
        _push_toast(state, f"🌟 {card_name} 有辅助支援，伤害×{multiplier}！")
    else:
        card_name = str(_card_val(card, "name", "未知"))
        _log(logs, player_key, "support_dmg_skip", 0,
             f"effect:SUPPORT_DMG_MULTIPLIER({card_name}:无辅助)")


# ── 执行器派发表 ──────────────────────────────────────────────────

#: handler_key → 执行函数映射表
_HANDLER_TABLE: dict[str, Callable[
    [dict[str, Any], str, Any, dict[str, Any], list[dict[str, Any]]],
    None,
]] = {
    "block_one_turn":           _exec_block_one_turn,
    "discard_by_faction":       _exec_discard_by_faction,
    "gain_mana":                 _exec_gain_mana,
    "add_shield":               _exec_add_shield,
    "heal_to_value":            _exec_heal_to_value,
    "heal_flat":                 _exec_heal_flat,
    "disable_atk":              _exec_disable_atk,
    "silence_opponent":         _exec_silence_opponent,
    "armor_pierce":             _exec_armor_pierce,
    "counter_atk_zero":         _exec_counter_atk_zero,
    "counter_dmg_multiplier":   _exec_counter_dmg_multiplier,
    "dmg_buff_2x":              _exec_dmg_buff_2x,
    "steal_random_card":        _exec_steal_random_card,
    "steal_by_faction":         _exec_steal_by_faction,
    "cost_to_heal_combo":       _exec_cost_to_heal_combo,
    "cost_to_heal_self":        _exec_cost_to_heal_self,
    "atk_to_heal_opponent":     _exec_atk_to_heal_opponent,
    "reflect_attack":           _exec_reflect_attack,
    "boost_atk_and_heal":       _exec_boost_atk_and_heal,
    "reduce_dmg_flat":          _exec_reduce_dmg_flat,
    "mana_up":                  _exec_mana_up,
    "support_dmg_multiplier":   _exec_support_dmg_multiplier,
}


# ── 主执行引擎类 ──────────────────────────────────────────────────

class EffectExecutor:
    """三级效果执行器。

    使用方式：
        from core.effect_executor import EffectExecutor

        logs: list = []
        success = EffectExecutor.execute(state, "P1", card, logs)

    或通过模块级函数：
        from core.effect_executor import dispatch_effect_new
        dispatch_effect_new(effect_id, state, player_key, card, logs)
    """

    @staticmethod
    def execute(
        state: dict[str, Any],
        player_key: str,
        card: Any,
        logs: list[dict[str, Any]],
    ) -> bool:
        """执行卡牌技能效果（向后兼容的旧方法）。

        三级派发链：
          card.effect_id → SKILL_REGISTRY[effect_id] → handler_key → _HANDLER_TABLE[handler_key]

        支持 effect_id 为字符串或列表两种格式（向后兼容）。

        Args:
            state:      游戏状态字典
            player_key: 出牌方（"P1"/"P2"）
            card:       卡牌对象（dict 或 Card 对象均可）
            logs:       日志列表，就地追加记录

        Returns:
            True 表示至少找到并执行了一个技能，False 表示 effect_id 为空或全部未注册。
            
        @deprecated: 建议使用阶段执行方法 execute_effect_by_phase
        """
        raw_eid = _card_val(card, "effect_id", "")

        # 支持列表和字符串两种格式
        if isinstance(raw_eid, list):
            effect_ids: list[str] = [str(e).strip() for e in raw_eid if str(e).strip()]
        else:
            single = str(raw_eid).strip()
            effect_ids = [single] if single else []

        if not effect_ids:
            # ── 向日葵系列兜底：effect_id 为空但卡牌 ID 在 _SUNFLOWER_MANA_MAP 中 ──
            card_id = int(_card_val(card, "id", -1))
            mana_value = _SUNFLOWER_MANA_MAP.get(card_id)
            if mana_value:
                _exec_mana_up(state, player_key, card, {"value": mana_value}, logs)
                return True
            # ── 特殊技能兜底：effect_id 为空但卡牌 ID 在 _SPECIAL_SUPPORT_BUFF_MAP 中 ──
            special = _SPECIAL_SUPPORT_BUFF_MAP.get(card_id)
            if special:
                handler_fn = _HANDLER_TABLE.get(special["handler"])
                if handler_fn:
                    handler_fn(state, player_key, card, {"value": special["value"]}, logs)
                    return True
            return False

        any_dispatched = False
        for effect_id in effect_ids:
            skill_data = get_skill_data(effect_id)
            if skill_data is None:
                _log(logs, player_key, "effect_unregistered", 0, f"effect_id:{effect_id}")
                continue

            handler_key = str(skill_data.get("handler_key", ""))
            handler_fn = _HANDLER_TABLE.get(handler_key)

            if handler_fn is None:
                _log(logs, player_key, "handler_not_found", 0,
                     f"effect_id:{effect_id} handler_key:{handler_key}")
                continue

            handler_fn(state, player_key, card, skill_data, logs)
            any_dispatched = True

        return any_dispatched

    @staticmethod
    def get_skill_info(effect_id: str) -> str:
        """返回技能的人类可读描述，用于 UI 提示。"""
        if not effect_id:
            return ""
        data = get_skill_data(effect_id)
        if data is None:
            return f"未知技能({effect_id})"
        return str(data.get("desc", effect_id))

    @staticmethod
    def list_all_handlers() -> list[str]:
        """返回所有已注册的 handler_key 列表，用于调试和验证。"""
        return list(_HANDLER_TABLE.keys())
    
    # ==================== 阶段执行方法 ====================
    
    @staticmethod
    def execute_effect_by_phase(
        state: dict[str, Any],
        player_key: str,
        card: Any,
        effect_id: str,
        phase: int,
        logs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """按阶段执行效果（新方法）。
        
        根据阶段（1-6）筛选并执行对应的效果。
        
        Args:
            state: 游戏状态字典
            player_key: 出牌方
            card: 卡牌对象
            effect_id: 效果ID
            phase: 阶段编号（1-6）
            logs: 日志列表
            
        Returns:
            执行的日志记录列表
        """
        phase_logs: list[dict[str, Any]] = []
        
        # 获取技能数据
        skill_data = get_skill_data(effect_id)
        if skill_data is None:
            return phase_logs
            
        handler_key = str(skill_data.get("handler_key", ""))
        handler_fn = _HANDLER_TABLE.get(handler_key)
        
        if handler_fn is None:
            return phase_logs
            
        # 执行效果
        try:
            handler_fn(state, player_key, card, skill_data, phase_logs)
            return phase_logs
        except Exception as exc:
            phase_logs.append({
                "player": player_key,
                "action": "effect_error",
                "value": 0,
                "reason": f"{effect_id}: {exc}"
            })
            return phase_logs
    
    @staticmethod
    def execute_counter_effect(
        state: dict[str, Any],
        player_key: str,
        opponent_key: str,
        card: Any,
        effect_id: str,
        logs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """执行阵营克制效果（阶段3专用）。
        
        Args:
            state: 游戏状态字典
            player_key: 出牌方
            opponent_key: 对手
            card: 卡牌对象
            effect_id: 效果ID
            logs: 日志列表
            
        Returns:
            执行的日志记录列表
        """
        # 克制效果已经在现有方法中处理，直接调用
        EffectExecutor.execute(state, player_key, card, logs)
        return logs
    
    @staticmethod
    def execute_interaction_effect(
        state: dict[str, Any],
        player_key: str,
        opponent_key: str,
        card: Any,
        effect_id: str,
        logs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """执行卡牌交互效果（阶段5专用）。
        
        包括：弃牌、偷牌、转化等需要对手信息的技能。
        
        Args:
            state: 游戏状态字典
            player_key: 出牌方
            opponent_key: 对手
            card: 卡牌对象
            effect_id: 效果ID
            logs: 日志列表
            
        Returns:
            执行的日志记录列表
        """
        # 交互效果已经在现有方法中处理，直接调用
        EffectExecutor.execute(state, player_key, card, logs)
        return logs
    
    @staticmethod
    def execute_control_effect(
        state: dict[str, Any],
        player_key: str,
        opponent_key: str,
        card: Any,
        effect_id: str,
        logs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """执行控制和防御效果（阶段6专用，最高优先级）。
        
        包括：沉默、反弹、抵挡等。
        
        Args:
            state: 游戏状态字典
            player_key: 出牌方
            opponent_key: 对手
            card: 卡牌对象
            effect_id: 效果ID
            logs: 日志列表
            
        Returns:
            执行的日志记录列表
        """
        # 控制和防御效果已经在现有方法中处理，直接调用
        EffectExecutor.execute(state, player_key, card, logs)
        return logs


# ── 模块级兼容接口（供 resolution_engine 直接调用）────────────────

def dispatch_effect_new(
    effect_id: str,
    state: dict[str, Any],
    player_key: str,
    card: Any,
    logs: list[dict[str, Any]],
) -> bool:
    """新系统的效果派发入口，接口与旧版 dispatch_effect 保持一致。

    供 resolution_engine 逐步迁移时调用：
        # 新系统优先，旧系统兜底
        dispatched = dispatch_effect_new(eff_id, state, player, card, logs)
        if not dispatched:
            dispatched = dispatch_effect(eff_id, state, player, card, logs)  # 旧系统

    Returns:
        True 表示新系统处理了该 effect_id，False 表示未处理（可回退旧系统）
    """
    return EffectExecutor.execute(state, player_key, card, logs)
