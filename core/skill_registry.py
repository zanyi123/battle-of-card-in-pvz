"""core/skill_registry.py - 三级技能系统：二级技能目录。

架构说明：
  三级架构：
    一级  ── effect_registry.py：EFFECT_CATEGORIES，14个效果大类
    二级（本文件）── SKILL_REGISTRY，effect_id → 类别+参数+执行策略
    三级  ── effect_executor.py：EffectExecutor，执行引擎

本文件职责：
  - 将 cards.json 中所有 effect_id 映射到结构化技能数据
  - 每条记录包含：category（一级分类键）、value（数值参数）、
    target（作用目标）、desc（中文描述）、handler_key（执行器派发键）
  - 是连接"卡牌数据"和"执行引擎"的桥梁

cards.json 中所有 effect_id 清单（19张有技能卡）：
  ID  卡名          effect_id           描述
   7  原始猕猴桃     SHIELD_TURN         抵挡一回合攻击
  14  炙热山葵       DISCARD_FA          弃对手法师阵营牌
  15  巴豆           SHIELD_6            护盾+6
  16  仙桃           HEAL_8              血量恢复至8点
  17  棉小雪         ATK_DISABLE         使对方攻击失效
  19  冰龙草         SILENCE             沉默（对手无法出牌）
  24  火龙草         ARMOR_PIERCE        破甲（无视护盾）
  32  飞镖洋蓟       COUNTER_ATK_ZERO    克制阵营攻击清0
  33  西瓜投手       COUNTER_DMG_X3      对克制阵营伤害×3
  34  毁灭菇         NO_COUNTER_DMG_X2   无法被克制时伤害×2
  38  香水蘑菇       STEAL_CARD          从对手手牌偷一张
  39  粉丝心叶兰     COST_TO_HEAL        同出卡费用转为回血
  40  魅惑菇         REFLECT_ATK         将对方攻击反弹
  41  能量花         BOOST_ATK_HEAL      增伤2+回血2
  44  熊果臼炮       REDUCE_DMG_2        对手每张卡减伤2
  46  暗樱草         STEAL_SH            偷对手射手阵营牌
  49  南瓜巫师       COST_TO_HEAL_SELF   自身费用转为自身回血
  51  热辣海藻       SHIELD_TURN         抵挡一回合攻击
  53  水晶兰         ATK_TO_HEAL         将对方攻击值转为回血
"""
from __future__ import annotations

from typing import Any

from core.effect_registry import EFFECT_CATEGORIES


# ── 技能目标常量 ──────────────────────────────────────────────────
TARGET_SELF = "self"          # 效果作用于出牌方
TARGET_OPPONENT = "opponent"  # 效果作用于对手
TARGET_BOTH = "both"          # 效果同时影响双方


# ── 二级：技能注册表 ──────────────────────────────────────────────

#: 完整技能注册表。
#: 键：effect_id（与 cards.json effect_id 字段完全一致）。
#: 值：
#:   category   ── EFFECT_CATEGORIES 中的一级分类键
#:   value      ── 主数值参数（护盾量/治疗量/伤害倍数等，0 表示无固定值）
#:   value2     ── 次数值参数（可选，用于双效果技能，如 BOOST_ATK_HEAL）
#:   target     ── 作用目标（TARGET_SELF / TARGET_OPPONENT / TARGET_BOTH）
#:   handler_key── 执行器中的派发键（effect_executor 用此键找到具体执行函数）
#:   faction_filter── 对目标阵营的过滤器（可选，如 "法" 表示仅法师牌）
#:   desc       ── 技能中文描述
SKILL_REGISTRY: dict[str, dict[str, Any]] = {

    # ── BLOCK 类（抵挡一回合） ────────────────────────────────────
    "SHIELD_TURN": {
        "category": "BLOCK",
        "value": 1,
        "target": TARGET_SELF,
        "handler_key": "block_one_turn",
        "desc": "抵挡一回合攻击（本回合受到的伤害完全免疫）",
        # 拥有此技能的卡：7-原始猕猴桃、51-热辣海藻
    },

    # ── DISCARD 类（弃牌） ────────────────────────────────────────
    "DISCARD_FA": {
        "category": "DISCARD",
        "value": 1,
        "target": TARGET_OPPONENT,
        "handler_key": "discard_by_faction",
        "faction_filter": "法",
        "desc": "将对手手牌中的法师阵营卡随机抽出作废",
        # 拥有此技能的卡：14-炙热山葵
    },

    # ── SHIELD 类（数值护盾） ─────────────────────────────────────
    "SHIELD_1": {
        "category": "SHIELD",
        "value": 1,
        "target": TARGET_SELF,
        "handler_key": "add_shield",
        "desc": "为自身添加1点护盾值",
        # 拥有此技能的卡：3-坚果墙
    },
    "SHIELD_2": {
        "category": "SHIELD",
        "value": 2,
        "target": TARGET_SELF,
        "handler_key": "add_shield",
        "desc": "为自身添加2点护盾值",
        # 拥有此技能的卡：48-全息坚果
    },
    "SHIELD_6": {
        "category": "SHIELD",
        "value": 6,
        "target": TARGET_SELF,
        "handler_key": "add_shield",
        "desc": "为自身添加6点护盾值",
        # 拥有此技能的卡：15-巴豆
    },

    # ── MANA 类（精力增益） ──────────────────────────────────────
    "MANA_1": {
        "category": "MANA",
        "value": 1,
        "target": TARGET_SELF,
        "handler_key": "gain_mana",
        "desc": "精力上限+1",
        # 拥有此技能的卡：1-向日葵
    },
    "MANA_3": {
        "category": "MANA",
        "value": 3,
        "target": TARGET_SELF,
        "handler_key": "gain_mana",
        "desc": "精力上限+3",
        # 拥有此技能的卡：10-阳光蓓蕾, 27-阳光菇
    },
    "MANA_4": {
        "category": "MANA",
        "value": 4,
        "target": TARGET_SELF,
        "handler_key": "gain_mana",
        "desc": "精力上限+4",
        # 拥有此技能的卡：42-向日葵歌手
    },

    # ── HEAL 类（生命恢复） ───────────────────────────────────────
    "HEAL_2": {
        "category": "HEAL",
        "value": 2,
        "target": TARGET_SELF,
        "handler_key": "heal_flat",
        "desc": "恢复2点生命值",
        # 拥有此技能的卡：18-白萝卜
    },
    "HEAL_3": {
        "category": "HEAL",
        "value": 3,
        "target": TARGET_SELF,
        "handler_key": "heal_flat",
        "desc": "恢复3点生命值",
        # 拥有此技能的卡：43-三叶草
    },
    "HEAL_4": {
        "category": "HEAL",
        "value": 4,
        "target": TARGET_SELF,
        "handler_key": "heal_flat",
        "desc": "恢复4点生命值",
        # 拥有此技能的卡：36-旋转菠萝
    },
    "HEAL_8": {
        "category": "HEAL",
        "value": 8,
        "target": TARGET_SELF,
        "handler_key": "heal_to_value",
        "desc": "将血量恢复至8点（若当前血量低于8则恢复到8）",
        # 拥有此技能的卡：16-仙桃
    },

    # ── SILENCE 类（沉默控制） ────────────────────────────────────
    "ATK_DISABLE": {
        "category": "SILENCE",
        "value": 1,
        "target": TARGET_OPPONENT,
        "handler_key": "disable_atk",
        "desc": "使对方本回合出牌的攻击值失效（仅攻击归零）",
        # 拥有此技能的卡：17-棉小雪
    },
    "SILENCE": {
        "category": "SILENCE",
        "value": 1,
        "target": TARGET_OPPONENT,
        "handler_key": "silence_opponent",
        "desc": "沉默：该回合对手无法打出任何卡牌",
        # 拥有此技能的卡：19-冰龙草
    },

    # ── ARMOR_PEN 类（破甲） ──────────────────────────────────────
    "ARMOR_PIERCE": {
        "category": "ARMOR_PEN",
        "value": 1,
        "target": TARGET_OPPONENT,
        "handler_key": "armor_pierce",
        "desc": "破甲：攻击无视对手护盾，直接造成伤害",
        # 拥有此技能的卡：24-火龙草
    },

    # ── COUNTER 类（克制效果）───────────────────────────────────
    "COUNTER_ATK_ZERO": {
        "category": "COUNTER",
        "value": 0,
        "target": TARGET_OPPONENT,
        "handler_key": "counter_atk_zero",
        "desc": "当坦克阵营卡牌攻击它时，攻击方atk清0（飞镖洋蓟专用）",
        # 拥有此技能的卡：32-飞镖洋蓟
    },
    "COUNTER_DMG_X3": {
        "category": "COUNTER",
        "value": 3,
        "target": TARGET_OPPONENT,
        "handler_key": "counter_dmg_multiplier",
        "desc": "攻击坦克阵营时，基础伤害×3，叠加溢出伤害（西瓜投手专用）",
        # 拥有此技能的卡：33-西瓜投手
    },
    "DMG_BUFF_2X": {
        "category": "COUNTER",
        "value": 2,
        "target": TARGET_SELF,
        "handler_key": "dmg_buff_2x",
        "desc": "攻击非坦克阵营时，基础伤害×2，叠加溢出伤害（毁灭菇专用）",
        # 拥有此技能的卡：34-毁灭菇
    },
    "NO_COUNTER_DMG_X2": {
        "category": "COUNTER",
        "value": 2,
        "target": TARGET_SELF,
        "handler_key": "dmg_buff_2x",
        "desc": "攻击非坦克阵营时，基础伤害×2，叠加溢出伤害（毁灭菇专用）",
        # 拥有此技能的卡：34-毁灭菇（旧ID兼容）
    },

    # ── STEAL 类（偷卡） ──────────────────────────────────────────
    "STEAL_CARD": {
        "category": "STEAL",
        "value": 1,
        "target": TARGET_OPPONENT,
        "handler_key": "steal_random_card",
        "desc": "从对面手牌中随机抽一张加入己方手牌",
        # 拥有此技能的卡：38-香水蘑菇
    },
    "STEAL_SH": {
        "category": "STEAL",
        "value": 1,
        "target": TARGET_OPPONENT,
        "handler_key": "steal_by_faction",
        "faction_filter": "射",
        "desc": "将对手手牌中的射手阵营卡随机抽出添加到己方手牌",
        # 拥有此技能的卡：46-暗樱草
    },

    # ── CONVERT 类（数值转化） ────────────────────────────────────
    "COST_TO_HEAL": {
        "category": "CONVERT",
        "value": 0,          # 动态值：同回合出牌的总费用
        "target": TARGET_SELF,
        "handler_key": "cost_to_heal_combo",
        "desc": "将同回合同出牌的卡牌费用值转化为等量血量回复",
        # 拥有此技能的卡：39-粉丝心叶兰
    },
    "COST_TO_HEAL_SELF": {
        "category": "CONVERT",
        "value": 0,          # 动态值：本卡自身费用
        "target": TARGET_SELF,
        "handler_key": "cost_to_heal_self",
        "desc": "恢复：自身消耗的费用值等于生命回复值",
        # 拥有此技能的卡：49-南瓜巫师
    },
    "ATK_TO_HEAL": {
        "category": "CONVERT",
        "value": 0,          # 动态值：对方手牌攻击值之和
        "target": TARGET_SELF,
        "handler_key": "atk_to_heal_opponent",
        "desc": "将对方手牌中卡牌攻击值转化为自身回复血量",
        # 拥有此技能的卡：53-水晶兰
    },

    # ── REFLECT 类（反弹） ────────────────────────────────────────
    "REFLECT_ATK": {
        "category": "REFLECT",
        "value": 1,
        "target": TARGET_BOTH,
        "handler_key": "reflect_attack",
        "desc": "将对方的攻击伤害完整反弹给对方",
        # 拥有此技能的卡：40-魅惑菇
    },

    # ── COMBO 类（连携增益） ──────────────────────────────────────
    "BOOST_ATK_HEAL": {
        "category": "COMBO",
        "value": 2,           # 增伤值
        "value2": 2,          # 回血值
        "target": TARGET_BOTH,
        "handler_key": "boost_atk_and_heal",
        "desc": "增加同回合出牌伤害2点，同时恢复2点生命",
        # 拥有此技能的卡：41-能量花
    },

    # ── DMG_REDUCE 类（减伤） ─────────────────────────────────────
    "REDUCE_DMG_2": {
        "category": "DMG_REDUCE",
        "value": 2,
        "target": TARGET_SELF,
        "handler_key": "reduce_dmg_flat",
        "desc": "对对手每张出牌减少2点伤害（固定减伤，非百分比）",
        # 拥有此技能的卡：9-寒冰射手、44-熊果臼炮
    },

    # ── SUPPORT_DMG 类（辅助增伤）─────────────────────────────────
    "SUPPORT_DMG_MULTIPLIER": {
        "category": "SUPPORT_DMG",
        "value": 3,
        "target": TARGET_SELF,
        "handler_key": "support_dmg_multiplier",
        "desc": "有辅助卡时，伤害×3",
        # 拥有此技能的卡：30-莲小蓬
    },
}


# ── 查询接口 ──────────────────────────────────────────────────────

def get_skill_data(skill_id: str) -> dict[str, Any] | None:
    """根据 effect_id 获取技能数据。

    Args:
        skill_id: cards.json 中的 effect_id 字符串

    Returns:
        技能数据字典，或 None（未注册）
    """
    return SKILL_REGISTRY.get(skill_id)


def get_handler_key(skill_id: str) -> str | None:
    """快捷获取技能对应的执行器派发键。"""
    data = SKILL_REGISTRY.get(skill_id)
    if data is None:
        return None
    return str(data.get("handler_key", ""))


def get_skill_category(skill_id: str) -> str | None:
    """快捷获取技能对应的一级分类键。"""
    data = SKILL_REGISTRY.get(skill_id)
    if data is None:
        return None
    return str(data.get("category", ""))


def list_skills_by_category(category_key: str) -> list[str]:
    """列出指定分类下所有技能的 effect_id。"""
    return [
        eff_id
        for eff_id, data in SKILL_REGISTRY.items()
        if data.get("category") == category_key
    ]


def validate_registry() -> list[str]:
    """校验所有技能数据的完整性，返回错误列表（空列表表示通过）。"""
    errors: list[str] = []
    required_keys = {"category", "value", "target", "handler_key", "desc"}
    valid_categories = set(EFFECT_CATEGORIES.keys())

    for skill_id, data in SKILL_REGISTRY.items():
        missing = required_keys - set(data.keys())
        if missing:
            errors.append(f"{skill_id}: 缺少必要字段 {missing}")
        cat = data.get("category", "")
        if cat not in valid_categories:
            errors.append(f"{skill_id}: 非法分类 '{cat}'，合法值为 {valid_categories}")

    return errors


def validate_all_effects(cards_data: list[dict[str, Any]]) -> None:
    """启动时扫描 cards.json 所有 effect_id，确保 100% 命中 SKILL_REGISTRY。

    Args:
        cards_data: cards.json 中的 "cards" 数组

    Raises:
        ValueError: 若存在未注册的 effect_id，抛出异常并列出卡牌名称
    """
    missing: list[str] = []
    for card in cards_data:
        eid = card.get("effect_id", "")
        if not eid:
            continue
        # 支持字符串或列表两种格式
        effect_ids: list[str] = eid if isinstance(eid, list) else [str(eid)]
        for single_eid in effect_ids:
            single_eid = single_eid.strip()
            if single_eid and single_eid not in SKILL_REGISTRY:
                missing.append(f"{card.get('name', '?')}(id={card.get('id', '?')}): effect_id='{single_eid}'")

    if missing:
        raise ValueError(f"❌ 以下卡牌的 effect_id 未在 SKILL_REGISTRY 中注册：\n" + "\n".join(missing))
    print("✅ 技能映射完整：所有 effect_id 均已注册")
