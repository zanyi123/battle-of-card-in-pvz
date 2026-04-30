from __future__ import annotations

import random
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.state_machine import GameStateMachine


class SimpleAI:
    """简易 AI，用于 P2 自动出牌。
    出牌策略（贪心）：
    1. 筛选手牌中费用 <= 当前 mana 的卡
    2. 优先选攻击力最高的主牌
    3. 若主牌非限制卡，用剩余 mana 搭配一张辅牌
    4. 若手牌全部费用 > mana，跳过不出
    """

    def choose_cards(self, hand: list[Any], mana: int) -> list[Any]:
        """从手牌中选出本回合要出的卡牌列表（会直接从 hand 中移除已选卡）。

        Args:
            hand: P2 当前手牌（list of Card / any object with .cost/.atk/.type/.limit_flag 属性）
            mana: 当前可用精力

        Returns:
            选出的卡牌列表（0~2张），同时已从 hand 中移除
        """
        if not hand:
            return []

        affordable = [c for c in hand if int(getattr(c, "cost", 0)) <= mana]
        if not affordable:
            return []  # 强制跳过

        main_cards = [c for c in affordable if getattr(c, "type", "") == "主"]
        support_cards = [c for c in affordable if getattr(c, "type", "") == "辅"]

        if not main_cards:
            # 没有主卡时按规则不允许只出辅卡，视为跳过
            return []

        # 选攻击力最高的主卡（同攻击力取 cost 低、id 小的）
        main = sorted(main_cards, key=lambda c: (-int(getattr(c, "atk", 0)), int(getattr(c, "cost", 0)), int(getattr(c, "id", 0))))[0]
        chosen: list[Any] = [main]

        if not getattr(main, "limit_flag", False):
            remain_mana = mana - int(getattr(main, "cost", 0))
            candidates = [
                c for c in support_cards
                if int(getattr(c, "cost", 0)) <= remain_mana
                and not getattr(c, "limit_flag", False)
                and c is not main
            ]
            if candidates:
                support = sorted(candidates, key=lambda c: (-int(getattr(c, "atk", 0)), int(getattr(c, "cost", 0)), int(getattr(c, "id", 0))))[0]
                chosen.append(support)

        # 安全校验：总费用不超出 mana，且最多2张，限制卡不组合
        total_cost = sum(int(getattr(c, "cost", 0)) for c in chosen)
        if total_cost > mana:
            chosen = chosen[:1]
        if len(chosen) > 2:
            chosen = chosen[:2]
        if len(chosen) == 2 and any(getattr(c, "limit_flag", False) for c in chosen):
            chosen = chosen[:1]

        # 从手牌中移除已选卡
        for c in chosen:
            if c in hand:
                hand.remove(c)

        return chosen

    def try_remedy(
        self,
        state: dict[str, Any],
        state_machine: GameStateMachine,
    ) -> tuple[bool, str]:
        """AI 补救回合：从手牌中寻找允许的补救卡并自动打出。

        优先级：回血效果 > 护盾效果 > 其他防御效果。
        补救阶段不受精力限制（濒死时可以超费出牌）。

        Args:
            state: 当前游戏状态
            state_machine: 状态机实例（用于调用 play_card_remedy）

        Returns:
            (是否成功补救, 提示消息)
        """
        hand = state.get("hands", {}).get("P2", [])
        if not hand:
            return False, "AI 手牌为空"

        # 筛选允许补救的卡牌（复用 state_machine.play_card_remedy 的验证逻辑）
        from core.skill_registry import get_skill_category

        allowed_categories: set[str] = {"HEAL", "SHIELD", "BLOCK", "SILENCE", "REFLECT", "CONVERT"}
        allowed_skill_ids: set[str] = {
            "COUNTER_ATK_ZERO", "COST_TO_HEAL", "COST_TO_HEAL_SELF",
            "REFLECT_ATK", "ATK_TO_HEAL", "ATK_DISABLE", "SILENCE",
        }

        valid_cards: list[tuple[int, Any]] = []  # (优先级, card)
        for card in hand:
            effect_id = str(getattr(card, "effect_id", "")).strip()
            if not effect_id:
                continue
            is_allowed = False
            if get_skill_category(effect_id) in allowed_categories:
                is_allowed = True
            elif effect_id in allowed_skill_ids:
                is_allowed = True
            else:
                eid_lower = effect_id.lower()
                if "heal" in eid_lower or "shield" in eid_lower:
                    is_allowed = True
            if is_allowed:
                # 优先级：HEAL > SHIELD > 其他
                category = get_skill_category(effect_id)
                priority = 0  # 其他
                if category == "HEAL":
                    priority = 2
                elif category == "SHIELD":
                    priority = 1
                valid_cards.append((priority, card))

        if not valid_cards:
            return False, "AI 无卡可救"

        # 按优先级降序选牌，同级随机
        valid_cards.sort(key=lambda x: -x[0])
        max_priority = valid_cards[0][0]
        top_cards = [c for p, c in valid_cards if p == max_priority]
        chosen_card = random.choice(top_cards)

        card_name = getattr(chosen_card, "name", "?")
        success, message = state_machine.play_card_remedy(chosen_card, "P2")
        if success:
            return True, f"AI 使用 {card_name} 补救成功"
        else:
            return False, f"AI 补救失败：{card_name}"
