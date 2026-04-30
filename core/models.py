from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class Card:
    id: int
    name: str
    cost: int
    atk: int
    faction: str
    type: str
    limit_flag: bool
    description: str = ""
    effect_id: str = ""
    image_file: str = ""


@dataclass
class Deck:
    cards: list[Card] = field(default_factory=list)

    def shuffle(self) -> None:
        random.shuffle(self.cards)

    def draw(self, count: int = 1) -> list[Card]:
        if count <= 0:
            return []
        draw_count = min(count, len(self.cards))
        drawn = self.cards[:draw_count]
        del self.cards[:draw_count]
        return drawn


@dataclass
class Player:
    hand: list[Card] = field(default_factory=list)
    deck: Deck = field(default_factory=Deck)
    mana: int = 0
    hp: int = 10
    max_hp: int = 10
