"""tests/test_integration.py - 三级技能系统集成验证测试。

验证内容：
  1. validate_all_effects：所有 cards.json effect_id 均已注册
  2. SHIELD_6（巴豆）：P1 护盾 +6
  3. STEAL_CARD（香水蘑菇）：P2 手牌 -1，P1 手牌 +1
  4. SILENCE（冰龙草）：temp[P2_silenced] = True
  5. ATK_DISABLE（棉小雪）：temp[P2_atk_disabled] = True
  6. ARMOR_PIERCE（火龙草）：破甲标记，resolution_engine 绕过护盾
  7. REFLECT_ATK（魅惑菇）：伤害反弹
  8. REDUCE_DMG_2（熊果臼炮）：减伤标记
  9. BOOST_ATK_HEAL（能量花）：增伤 + 回血
  10. ResolutionEngine 完整链路：辅助效果先执行 → 主卡伤害读 temp 修正
"""
from __future__ import annotations

import json
import types
from typing import Any

import pytest


def make_card(
    name: str,
    faction: str,
    card_type: str,
    atk: int,
    cost: int,
    effect_id: str = "",
    limit_flag: bool = False,
    cid: int = 0,
) -> Any:
    c = types.SimpleNamespace()
    c.name = name
    c.faction = faction
    c.type = card_type
    c.atk = atk
    c.cost = cost
    c.effect_id = effect_id
    c.limit_flag = limit_flag
    c.id = cid
    return c


def fresh_state() -> dict[str, Any]:
    return {
        "players": {
            "P1": {"hp": 10, "max_hp": 10, "max_mana": 5, "current_mana": 5, "buffs": []},
            "P2": {"hp": 10, "max_hp": 10, "max_mana": 5, "current_mana": 5, "buffs": []},
        },
        "hands": {"P1": [], "P2": []},
        "played_cards": {"P1": [], "P2": []},
        "played_cards_history": [],
        "temp": {},
    }


# ── 1. validate_all_effects ───────────────────────────────────────────

def test_validate_all_effects_passes():
    """所有 cards.json 中有 effect_id 的卡，均已在 SKILL_REGISTRY 中注册。"""
    from core.skill_registry import validate_all_effects
    with open("config/cards.json", "r", encoding="utf-8") as f:
        cards_data = json.load(f)["cards"]
    # 不应抛出异常
    validate_all_effects(cards_data)


# ── 2. SHIELD_6 ──────────────────────────────────────────────────────

def test_shield_6_adds_shield_buff():
    from core.effect_executor import EffectExecutor
    state = fresh_state()
    card = make_card("巴豆", "辅", "辅", 0, 3, "SHIELD_6", cid=15)
    logs: list = []
    result = EffectExecutor.execute(state, "P1", card, logs)
    assert result is True
    shield_buffs = [b for b in state["players"]["P1"]["buffs"] if b["type"] == "shield"]
    assert len(shield_buffs) == 1
    assert shield_buffs[0]["value"] == 6
    assert shield_buffs[0]["duration"] == -1


# ── 3. STEAL_CARD ─────────────────────────────────────────────────────

def test_steal_card_moves_card_between_hands():
    from core.effect_executor import EffectExecutor
    state = fresh_state()
    target = make_card("被偷目标", "射", "主", 4, 3, cid=88)
    state["hands"]["P2"] = [target]
    state["hands"]["P1"] = []
    card = make_card("香水蘑菇", "辅", "辅", 0, 2, "STEAL_CARD", cid=38)
    logs: list = []
    EffectExecutor.execute(state, "P1", card, logs)
    assert len(state["hands"]["P1"]) == 1
    assert len(state["hands"]["P2"]) == 0
    assert state["hands"]["P1"][0].name == "被偷目标"


def test_steal_card_empty_hand_no_crash():
    from core.effect_executor import EffectExecutor
    state = fresh_state()
    state["hands"]["P2"] = []
    card = make_card("香水蘑菇", "辅", "辅", 0, 2, "STEAL_CARD", cid=38)
    logs: list = []
    # 对手手牌为空时不应崩溃
    EffectExecutor.execute(state, "P1", card, logs)
    assert len(state["hands"]["P1"]) == 0


# ── 4. SILENCE ───────────────────────────────────────────────────────

def test_silence_sets_temp_flag():
    from core.effect_executor import EffectExecutor
    state = fresh_state()
    card = make_card("冰龙草", "法", "辅", 0, 2, "SILENCE", cid=19)
    logs: list = []
    EffectExecutor.execute(state, "P1", card, logs)
    assert state["temp"].get("P2_silenced") is True


# ── 5. ATK_DISABLE ───────────────────────────────────────────────────

def test_atk_disable_sets_temp_flag():
    from core.effect_executor import EffectExecutor
    state = fresh_state()
    card = make_card("棉小雪", "射", "辅", 0, 2, "ATK_DISABLE", cid=17)
    logs: list = []
    EffectExecutor.execute(state, "P1", card, logs)
    assert state["temp"].get("P2_atk_disabled") is True


# ── 6. ARMOR_PIERCE → _apply_damage 绕过护盾 ─────────────────────────

def test_armor_pierce_bypasses_shield():
    from core.resolution_engine import ResolutionEngine
    re = ResolutionEngine()
    # P1 有护盾 10，但 P2 有破甲 → P1 护盾应被无视
    state = {
        "players": {
            "P1": {"hp": 10, "max_hp": 10, "buffs": [{"type": "shield", "value": 10, "duration": -1, "icon_code": "shield"}]},
            "P2": {"hp": 10, "max_hp": 10, "buffs": []},
        },
        "played_cards": {"P1": [], "P2": []},
        "temp": {"P2_armor_pierce": True},
    }
    p1_main = make_card("P1主", "坦", "主", 0, 2)
    p2_main = make_card("P2主", "法", "主", 8, 2)
    dmg1, dmg2 = re._resolve_main_damage(p1_main, p2_main, state)
    assert dmg1 == 8, f"P1应受8伤 got {dmg1}"
    logs: list = []
    re._apply_damage("P1", dmg1, state, logs, "test")
    # 破甲时攻击方(P2)有 armor_pierce 标记，P1 受到的伤害应绕过护盾
    actions = [l["action"] for l in logs]
    assert "armor_pierce_bypass" in actions, f"未找到 armor_pierce_bypass: {actions}"
    assert state["players"]["P1"]["hp"] == 2  # 10 - 8 = 2（护盾被绕过）


# ── 7. REFLECT_ATK → resolve_clash 伤害反弹 ──────────────────────────

def test_reflect_atk_bounces_damage():
    from core.resolution_engine import ResolutionEngine
    re = ResolutionEngine()
    state = {
        "players": {
            "P1": {"hp": 10, "max_hp": 10, "buffs": []},
            "P2": {"hp": 10, "max_hp": 10, "buffs": []},
        },
        "played_cards": {"P1": [], "P2": []},
        "temp": {"P1_reflect_atk": True},
    }
    # P2_ATK=5 > P1_ATK=0 → 正常情况 P1 受 5 伤，但 P1 有反弹 → P2 受 5 伤
    p1_main = make_card("P1主", "坦", "主", 0, 2)
    p2_main = make_card("P2主", "法", "主", 5, 2)
    dmg1, dmg2 = re._resolve_main_damage(p1_main, p2_main, state)
    assert dmg1 == 5  # P1 要受 5 伤

    # 反弹处理
    dmg1_after, dmg2_after = re._apply_reflect(dmg1, dmg2, state, [])
    assert dmg1_after == 0, f"P1伤害应被反弹到0, got {dmg1_after}"
    assert dmg2_after == 5, f"P2应额外受5伤, got {dmg2_after}"


# ── 8. REDUCE_DMG_2 → _resolve_main_damage 减伤 ──────────────────────

def test_reduce_dmg_2_flat_reduction():
    from core.resolution_engine import ResolutionEngine
    re = ResolutionEngine()
    state = {
        "players": {
            "P1": {"hp": 10, "max_hp": 10, "buffs": []},
            "P2": {"hp": 10, "max_hp": 10, "buffs": []},
        },
        "played_cards": {
            "P1": [make_card("P1主", "坦", "主", 0, 2)],
            "P2": [make_card("P2主", "法", "主", 8, 2)],
        },
        "temp": {"P1_flat_dmg_reduce": 2},  # P1 被攻击时每张卡减 2 伤
    }
    p1_main = make_card("P1主", "坦", "主", 0, 2)
    p2_main = make_card("P2主", "法", "主", 8, 2)
    dmg1, dmg2 = re._resolve_main_damage(p1_main, p2_main, state)
    # P2_ATK=8, P1_ATK=0, 净伤=8, P2打出1张卡, 减伤2*1=2, 最终6
    assert dmg1 == 6, f"P1应受6伤（8-2减伤）, got {dmg1}"


# ── 9. BOOST_ATK_HEAL ────────────────────────────────────────────────

def test_boost_atk_heal_applies_both():
    from core.effect_executor import EffectExecutor
    state = fresh_state()
    state["players"]["P1"]["hp"] = 8  # max_hp=10，回血+2=10
    card = make_card("能量花", "辅", "辅", 0, 2, "BOOST_ATK_HEAL", cid=41)
    logs: list = []
    EffectExecutor.execute(state, "P1", card, logs)
    # atk_boost 标记
    assert state["temp"].get("P1_atk_boost") == 2, f"atk_boost 应为2: {state['temp']}"
    # 回血 +2 → 8+2=10（不超过 max_hp）
    assert state["players"]["P1"]["hp"] == 10, f"HP应为10, got {state['players']['P1']['hp']}"


# ── 10. ResolutionEngine 完整链路：辅助牌先执行，主卡读 temp ───────────

def test_resolution_engine_support_before_main():
    """辅助牌（BOOST_ATK_HEAL）先执行，atk_boost 被 _resolve_main_damage 读取。"""
    from core.resolution_engine import ResolutionEngine
    re = ResolutionEngine()
    state = fresh_state()
    state["players"]["P1"]["hp"] = 8  # max_hp=10，回血+2=10

    # P1 打出主卡(atk=3) + 辅助卡(BOOST_ATK_HEAL +2 = 实际atk=5)
    # P2 打出主卡(atk=4)
    p1_main = make_card("P1主", "法", "主", 3, 2, cid=1)
    p1_support = make_card("能量花", "辅", "辅", 0, 2, "BOOST_ATK_HEAL", cid=41)
    p2_main = make_card("P2主", "坦", "主", 4, 2, cid=2)

    state["played_cards"]["P1"] = [p1_main, p1_support]
    state["played_cards"]["P2"] = [p2_main]

    logs = re.resolve_clash([p1_main, p1_support], [p2_main], state)
    # 全额制：P1 增伤后 atk=3+2=5，P2 atk=4
    # 新克制关系：坦克(TK) → 克制 → 法师(FA)
    # P2(坦克4) 克制 P1(法师3)，溢出伤害 = 4-3=1，总伤害 = 4+1=5
    # P1 打 P2 → 5 伤，P2 打 P1 → 5 伤（含溢出）
    # 并且 P1 额外回血 2（HP=8+2=10，不超过 max_hp）
    p1_hp = state["players"]["P1"]["hp"]
    p2_hp = state["players"]["P2"]["hp"]
    assert p2_hp == 5, f"P2应受5伤(HP=5), got p2_hp={p2_hp}"
    assert p1_hp == 5, f"P1应回血2后被P2打5伤(HP=5), got p1_hp={p1_hp}"
