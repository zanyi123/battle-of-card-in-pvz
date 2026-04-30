from core.models import Deck, Player
from core.pure_loop import (
    GameCard,
    decide_winner_if_decks_empty,
    rescue_if_needed,
    resolve_main_clash,
    should_force_skip,
)


def test_draw_boundary():
    deck = Deck(
        cards=[
            GameCard(1, "A", 1, 1, "主", False, "E1", "法"),
            GameCard(2, "B", 1, 1, "主", False, "E2", "射"),
        ]
    )
    drawn = deck.draw(5)
    assert len(drawn) == 2
    assert len(deck.cards) == 0


def test_force_skip_when_mana_not_enough():
    hand = [
        GameCard(1, "A", 4, 2, "主", False, "E1", "法"),
        GameCard(2, "B", 5, 3, "主", False, "E2", "射"),
    ]
    assert should_force_skip(hand, mana=3) is True


def test_counteract_same_faction_equal_atk():
    c1 = GameCard(1, "A", 2, 3, "主", False, "E1", "法")
    c2 = GameCard(2, "B", 2, 3, "主", False, "E2", "法")
    d1, d2 = resolve_main_clash(c1, c2)
    assert (d1, d2) == (0, 0)


def test_rescue_overflow_clamped_to_10():
    p = Player(
        hand=[GameCard(10, "救援卡", 1, 10, "主", False, "R1", "坦")],
        deck=Deck(cards=[]),
        mana=3,
        hp=5,
        max_hp=10,
    )
    lost, rescue_value = rescue_if_needed(p, incoming_damage=10)
    # 5 - 10 + 10 = 5, 钳制到 min(10, 5) = 5
    assert lost is False
    assert rescue_value == 10
    assert p.hp == 5


def test_empty_deck_settlement():
    p1 = Player(hand=[], deck=Deck(cards=[]), mana=3, hp=12, max_hp=10)
    p2 = Player(hand=[], deck=Deck(cards=[]), mana=3, hp=8, max_hp=10)
    assert decide_winner_if_decks_empty(p1, p2) == "p1"
