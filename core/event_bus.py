from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable


EventCallback = Callable[[Any], None]


class EventBus:
    EVENTS: tuple[str, ...] = (
        "card_played",
        "damage_dealt",
        "remedy_start",
        "round_end",
        "game_over",
    )

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventCallback]] = defaultdict(list)
        for event_name in self.EVENTS:
            self._subscribers[event_name]

    def subscribe(self, event_name: str, callback: EventCallback) -> None:
        if event_name not in self.EVENTS:
            raise ValueError(f"Unsupported event: {event_name}")
        self._subscribers[event_name].append(callback)

    def emit(self, event_name: str, data: Any = None) -> None:
        if event_name not in self.EVENTS:
            raise ValueError(f"Unsupported event: {event_name}")
        for callback in list(self._subscribers[event_name]):
            callback(data)
