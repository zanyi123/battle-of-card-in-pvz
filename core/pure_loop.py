from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from core.models import Deck, Player


@dataclass
class GameCard:
    id: int
    name: str
    cost: int
    atk: int
    type: str
    limit_flag: bool
    effect_id: str
    faction: str


def load_card_pool(cards_path: str | Path) -> list[GameCard]:
    path = Path(cards_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    examples = data.get("cards", [])
    total = int(data.get("meta", {}).get("total_templates", len(examples)))
    if not examples:
        return []
    pool: list[GameCard] = []
    for i in range(total):
        src = examples[i % len(examples)]
        pool.append(
            GameCard(
                id=i + 1,
                name=f"{src['name']}_{i + 1}",
                cost=int(src["cost"]),
                atk=int(src["atk"]),
                type=str(src["type"]),
                limit_flag=bool(src["limit_flag"]),
                effect_id=str(src["effect_id"]),
                faction=str(src["faction"]),
            )
        )
    return pool


def setup_players(card_pool: list[GameCard], seed: int = 7) -> tuple[Player, Player]:
    rng = random.Random(seed)
    cards = card_pool[:]
    rng.shuffle(cards)
    p1_deck_cards = cards[:27]
    p2_deck_cards = cards[27:54]

    p1 = Player(hand=[], deck=Deck(cards=p1_deck_cards), mana=3, hp=10, max_hp=10)
    p2 = Player(hand=[], deck=Deck(cards=p2_deck_cards), mana=3, hp=10, max_hp=10)

    p1.hand.extend(p1.deck.draw(5))
    p2.hand.extend(p2.deck.draw(5))
    return p1, p2


def should_force_skip(hand: list[GameCard], mana: int) -> bool:
    if not hand:
        return True
    min_cost = min(card.cost for card in hand)
    return min_cost > mana


def choose_play_cards(player: Player) -> list[GameCard]:
    if should_force_skip(player.hand, player.mana):
        return []

    affordable = [c for c in player.hand if c.cost <= player.mana]
    main_cards = [c for c in affordable if c.type == "主"]
    support_cards = [c for c in affordable if c.type == "辅"]
    chosen: list[GameCard] = []

    if main_cards:
        main = sorted(main_cards, key=lambda c: (-c.atk, c.cost, c.id))[0]
        if main.limit_flag:
            chosen = [main]
        else:
            chosen = [main]
            remain_mana = player.mana - main.cost
            second = [
                c
                for c in support_cards
                if c.cost <= remain_mana and not c.limit_flag and c.id != main.id
            ]
            if second:
                chosen.append(sorted(second, key=lambda c: (-c.atk, c.cost, c.id))[0])
    else:
        # 没有主卡时，不允许只出辅卡，按规则视为跳过
        chosen = []

    total_cost = sum(c.cost for c in chosen)
    if total_cost > player.mana:
        return []
    if len(chosen) > 2:
        chosen = chosen[:2]
    if len(chosen) == 2 and any(c.limit_flag for c in chosen):
        chosen = chosen[:1]

    for c in chosen:
        player.hand.remove(c)
    player.mana -= sum(c.cost for c in chosen)
    return chosen


def resolve_main_clash(p1_main: GameCard | None, p2_main: GameCard | None) -> tuple[int, int]:
    if p1_main is None or p2_main is None:
        return 0, 0
    if p1_main.faction == p2_main.faction and p1_main.atk == p2_main.atk:
        return 0, 0
    if p1_main.atk > p2_main.atk:
        return 0, p1_main.atk - p2_main.atk
    if p2_main.atk > p1_main.atk:
        return p2_main.atk - p1_main.atk, 0
    return 0, 0


def resolve_support_damage(cards: list[GameCard]) -> int:
    return sum(c.atk for c in cards if c.type == "辅")


def rescue_if_needed(
    player: Player,
    incoming_damage: int,
    rescue_card: GameCard | None = None,
) -> tuple[bool, int]:
    before_hp = player.hp
    after_damage = before_hp - incoming_damage
    if after_damage > 0:
        player.hp = after_damage
        return False, 0

    card = rescue_card
    if card is None and player.hand:
        card = sorted(player.hand, key=lambda c: (-c.atk, c.cost, c.id))[0]
    rescue_value = card.atk if card else 0
    if card and card in player.hand:
        player.hand.remove(card)
    final_hp = min(10, before_hp - incoming_damage + rescue_value)
    player.hp = final_hp
    defeated = final_hp <= 0
    return defeated, rescue_value


def draw_to_five(player: Player) -> int:
    need = max(0, 5 - len(player.hand))
    if need == 0:
        return 0
    drawn = player.deck.draw(need)
    player.hand.extend(drawn)
    return len(drawn)


def decide_winner_if_decks_empty(p1: Player, p2: Player) -> str:
    if p1.deck.cards or p2.deck.cards:
        return "ongoing"
    if p1.hp > 0 and p2.hp > 0:
        if p1.hp > p2.hp:
            return "p1"
        if p2.hp > p1.hp:
            return "p2"
        return "draw"
    return "ongoing"


def simulate_one_round() -> None:
    cards_path = Path(__file__).resolve().parents[1] / "config" / "cards.json"
    pool = load_card_pool(cards_path)
    p1, p2 = setup_players(pool, seed=11)

    # 固定 mock，确保演示出现：出牌 -> 克制 -> 补救 -> 补牌
    p1.hp = 10
    p2.hp = 2
    p1.mana = 3
    p2.mana = 3
    p1.hand = [
        GameCard(101, "主攻法师", 2, 5, "主", False, "E1", "法"),
        GameCard(102, "辅助增伤", 1, 2, "辅", False, "E2", "辅"),
    ]
    p2.hand = [
        GameCard(201, "防守射手", 2, 3, "主", False, "E3", "射"),
        GameCard(202, "补救坦克", 1, 4, "主", False, "E4", "坦"),
    ]

    print("=== 初始化 ===")
    print(f"牌池总数: {len(pool)}")
    print(f"P1 手牌: {len(p1.hand)}, P2 手牌: {len(p2.hand)}")
    print(f"P1 HP={p1.hp}, P2 HP={p2.hp}, 回合精力重置为3")

    p1_cards = choose_play_cards(p1)
    p2_cards = choose_play_cards(p2)
    print("\n=== 出牌阶段 ===")
    print(f"P1 出牌: {[c.name for c in p1_cards]} (剩余精力 {p1.mana})")
    print(f"P2 出牌: {[c.name for c in p2_cards]} (剩余精力 {p2.mana})")

    p1_main = next((c for c in p1_cards if c.type == "主"), None)
    p2_main = next((c for c in p2_cards if c.type == "主"), None)
    p1_support = [c for c in p1_cards if c.type == "辅"]
    p2_support = [c for c in p2_cards if c.type == "辅"]

    d1, d2 = resolve_main_clash(p1_main, p2_main)
    d1 += resolve_support_damage(p2_support)
    d2 += resolve_support_damage(p1_support)

    print("\n=== 克制结算 ===")
    print(f"主卡结算后: P1 受伤 {d1}, P2 受伤 {d2}")

    lose1, rescue1 = rescue_if_needed(p1, d1)
    lose2, rescue2 = rescue_if_needed(p2, d2)
    print("\n=== 补救回合 ===")
    print(f"P1 补救值: {rescue1}, 当前HP: {p1.hp}, 是否战败: {lose1}")
    print(f"P2 补救值: {rescue2}, 当前HP: {p2.hp}, 是否战败: {lose2}")
    print("临时Buff已清空")

    drawn1 = draw_to_five(p1)
    drawn2 = draw_to_five(p2)
    print("\n=== 回合结束补牌 ===")
    print(f"P1 补牌 {drawn1} 张，当前手牌 {len(p1.hand)}")
    print(f"P2 补牌 {drawn2} 张，当前手牌 {len(p2.hand)}")

    winner = decide_winner_if_decks_empty(p1, p2)
    print(f"牌库空结算状态: {winner}")
    print("=== 单回合演示结束 ===")


if __name__ == "__main__":
    simulate_one_round()
