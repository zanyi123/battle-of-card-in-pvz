"""core/effect_registry.py - 三级技能系统：一级分类注册表。

架构说明：
  三级架构：
    一级（本文件）  ── EFFECT_CATEGORIES：14个效果大类，描述技能的逻辑类型
    二级            ── skill_registry.py：SKILL_REGISTRY，具体技能ID → 类别+参数映射
    三级            ── effect_executor.py：EffectExecutor，执行引擎，真正改变 state

本文件职责：
  - 定义所有效果类别常量及元数据（name/type/icon_code/description）
  - 供 skill_registry.py 和 effect_executor.py 引用，避免魔法字符串
  - 提供 get_category() 查询函数
"""
from __future__ import annotations

from typing import Any


# ── 一级：14个效果大类 ────────────────────────────────────────────

#: 效果分类注册表。
#: 键：全大写分类名（str），作为 SKILL_REGISTRY 中 "category" 字段的合法值。
#: 值：字典，包含 name（中文名）、type（大类型）、icon_code（UI图标代码）、desc（说明）。
EFFECT_CATEGORIES: dict[str, dict[str, str]] = {
    # ── 精力类 ──────────────────────────────────────────────────
    "MANA": {
        "name": "精力增益",
        "type": "buff",
        "icon_code": "mana_up",
        "desc": "提升玩家最大精力上限，并同步增加当前精力",
    },

    # ── 防御类 ──────────────────────────────────────────────────
    "SHIELD": {
        "name": "护盾增益",
        "type": "buff",
        "icon_code": "shield",
        "desc": "为玩家添加数值护盾（永久持续直到被攻击耗尽）",
    },
    "DMG_REDUCE": {
        "name": "减伤",
        "type": "buff",
        "icon_code": "dmg_reduce",
        "desc": "本回合受到伤害按百分比减少",
    },
    "BLOCK": {
        "name": "抵挡",
        "type": "defense",
        "icon_code": "block",
        "desc": "抵挡一回合的所有攻击（完全免疫一次伤害）",
    },
    "ABSORB": {
        "name": "吸收",
        "type": "penetration",
        "icon_code": "absorb",
        "desc": "吸收对手护盾值并移除",
    },
    "WEAKEN": {
        "name": "削弱",
        "type": "penetration",
        "icon_code": "weaken",
        "desc": "将对手所有卡牌攻击力强制降至1",
    },
    "MULTIPLY": {
        "name": "增生",
        "type": "penetration",
        "icon_code": "multiply",
        "desc": "伤害 × 对手出牌数量",
    },
    "REFLECT": {
        "name": "反弹",
        "type": "defense",
        "icon_code": "reflect",
        "desc": "将对方的攻击伤害反弹回攻击方",
    },

    # ── 恢复类 ──────────────────────────────────────────────────
    "HEAL": {
        "name": "生命恢复",
        "type": "heal",
        "icon_code": "heal",
        "desc": "直接恢复指定点数的生命值（不超过上限）",
    },

    # ── 进攻类 ──────────────────────────────────────────────────
    "ARMOR_PEN": {
        "name": "破甲",
        "type": "penetration",
        "icon_code": "armor_pen",
        "desc": "攻击无视对方护盾，直接扣血",
    },
    "DMG_BUFF": {
        "name": "增伤",
        "type": "buff",
        "icon_code": "dmg_buff",
        "desc": "提升同回合出牌的攻击伤害",
    },
    "COUNTER": {
        "name": "克制",
        "type": "counter",
        "icon_code": "counter",
        "desc": "对克制阵营触发特殊效果（伤害倍增/清零）",
    },

    # ── 控制类 ──────────────────────────────────────────────────
    "DISCARD": {
        "name": "弃牌",
        "type": "control",
        "icon_code": "discard",
        "desc": "从对手手牌中随机弃置指定阵营的卡牌",
    },
    "SILENCE": {
        "name": "沉默",
        "type": "control",
        "icon_code": "silence",
        "desc": "该回合对手无法打出卡牌",
    },
    "STEAL": {
        "name": "偷卡",
        "type": "control",
        "icon_code": "steal",
        "desc": "从对手手牌中抽取一张卡牌加入己方手牌",
    },

    # ── 特殊类 ──────────────────────────────────────────────────
    "CONVERT": {
        "name": "转化",
        "type": "special",
        "icon_code": "convert",
        "desc": "将特定数值（如费用、攻击）转化为生命回复",
    },
    "COMBO": {
        "name": "连携",
        "type": "combo",
        "icon_code": "combo",
        "desc": "与同回合其他牌联动触发增益或伤害加成",
    },

    # ── 辅助增伤类 ──────────────────────────────────────────────
    "SUPPORT_DMG": {
        "name": "辅助增伤",
        "type": "buff",
        "icon_code": "support_dmg",
        "desc": "有辅助卡同出时，伤害倍增",
    },
}


# ── 查询接口 ──────────────────────────────────────────────────────

def get_category(category_key: str) -> dict[str, str] | None:
    """根据分类键获取分类元数据，未找到返回 None。

    Args:
        category_key: 全大写分类名，如 "SHIELD"、"HEAL"

    Returns:
        分类元数据字典，或 None
    """
    return EFFECT_CATEGORIES.get(category_key)


def is_valid_category(category_key: str) -> bool:
    """判断分类键是否合法。"""
    return category_key in EFFECT_CATEGORIES


def get_all_category_keys() -> list[str]:
    """返回所有合法分类键列表（用于校验）。"""
    return list(EFFECT_CATEGORIES.keys())
