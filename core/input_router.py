from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import pygame

from core.state_machine import GameStateMachine, TurnPhase
from utils.path_utils import get_resource_path


class InteractionZone(str, Enum):
    OPPONENT = "opponent"
    BATTLEFIELD = "battlefield"
    DECK = "deck"
    HAND = "hand"
    NONE = "none"


@dataclass
class DragState:
    active: bool = False
    start_pos: tuple[int, int] = (0, 0)
    zone: InteractionZone = InteractionZone.NONE


class InputRouter:
    # ── SFX 资源路径 ──────────────────────────────────────────────
    _SFX_ROOT = get_resource_path("assets/sfx")
    _SFX_CARD = "card_lighter.wav"

    def __init__(self, screen_size: tuple[int, int] = (1024, 768), state_machine: GameStateMachine | None = None) -> None:
        self.screen_w, self.screen_h = screen_size
        self.state_machine = state_machine
        self.drag_state = DragState()
        self.zones = self._build_zones()
        self.debug_hover: bool = False
        # ── SFX 音效预加载 ────────────────────────────────────────
        self._sfx_card: pygame.mixer.Sound | None = self._load_sfx()

    def _load_sfx(self) -> pygame.mixer.Sound | None:
        """预加载出牌音效。"""
        sfx_path = self._SFX_ROOT / self._SFX_CARD
        if not sfx_path.exists():
            return None
        try:
            sound = pygame.mixer.Sound(str(sfx_path))
            sound.set_volume(0.7)
            return sound
        except pygame.error:
            return None

    def _play_card_sfx(self) -> None:
        """播放出牌/退牌音效。"""
        if self._sfx_card is not None:
            self._sfx_card.play()

    def set_debug_hover(self, state: bool) -> None:
        """控制鼠标悬停时是否打印调试信息。"""
        self.debug_hover = state

    def handle(
        self,
        event_or_events: pygame.event.Event | list[pygame.event.Event],
        state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if self.state_machine is not None:
            self.state_machine.bind_runtime_state(state)
        events = event_or_events if isinstance(event_or_events, list) else [event_or_events]
        logs: list[dict[str, Any]] = []
        self.update_hovered_zone(state)

        for event in events:
            hovered = self._resolve_zone(pygame.mouse.get_pos())
            if event.type == pygame.MOUSEMOTION:
                # 鼠标移动日志仅在 debug_hover=True 时传递（默认安静）
                if self.debug_hover:
                    logs.append(
                        {
                            "player": "SYSTEM",
                            "action": "hover",
                            "value": hovered.value,
                            "reason": "mouse_move",
                        }
                    )
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    self.handle_click(
                        event.pos,
                        state.get("phase"),
                        state,
                        logs,
                    )
                    self._on_left_down(event.pos, state, logs)
                elif event.button == 3:
                    self._on_right_click(event.pos, state, logs)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._on_left_up(event.pos, state, logs)
        return logs

    def update_hovered_zone(self, state: dict[str, Any]) -> None:
        mouse_pos = pygame.mouse.get_pos()
        hovered = self._resolve_zone(mouse_pos)
        state.setdefault("ui", {})["hovered_zone"] = hovered.value

    def handle_click(self, pos: tuple[int, int], current_phase: Any, state: dict[str, Any], logs: list[dict[str, Any]] | None = None) -> None:
        zone = self._resolve_zone(pos)

        phase_name = current_phase.name if hasattr(current_phase, "name") else str(current_phase or "")

        # ROUND_END 阶段点击牌库不响应
        if phase_name == TurnPhase.ROUND_END.name and zone is InteractionZone.DECK:
            return

        # REMEDY 阶段点击手牌区域 → 仅允许出防御/恢复/控制类技能卡
        if phase_name == TurnPhase.REMEDY.name and zone is InteractionZone.HAND and self.state_machine is not None:
            p1_cards = state.get("hands", {}).get("P1", [])
            hit = self.get_hand_card_hit(pos, p1_cards)
            if hit is None:
                return
            card_index, _ = hit
            if not (0 <= card_index < len(p1_cards)):
                return
            card = p1_cards[card_index]
            success, message = self.state_machine.play_card_remedy(card, "P1")
            # 推送 toast 提示（允许或拒绝均反馈）
            import pygame as _pygame
            state.setdefault("toasts", []).append({
                "text": message,
                "time": _pygame.time.get_ticks(),
            })
            if logs is not None:
                logs.append(
                    {
                        "player": "SYSTEM",
                        "action": "remedy_result",
                        "value": 1 if success else 0,
                        "reason": message,
                    }
                )
            return

        # PLAY_P1 阶段点击手牌区域 → P1 出牌
        if phase_name == TurnPhase.PLAY_P1.name and zone is InteractionZone.HAND and self.state_machine is not None:
            p1_cards = state.get("hands", {}).get("P1", [])
            hit = self.get_hand_card_hit(pos, p1_cards)
            if hit is None:
                return
            card_index, _ = hit
            if not (0 <= card_index < len(p1_cards)):
                return
            card = p1_cards[card_index]
            p1_mana = int(state.get("players", {}).get("P1", {}).get("current_mana", 0))
            card_cost = int(getattr(card, "cost", 0))
            if p1_mana < card_cost:
                if logs is not None:
                    logs.append(
                        {
                            "player": "SYSTEM",
                            "action": "mana_insufficient",
                            "value": card_cost - p1_mana,
                            "reason": "精力不足",
                        }
                    )
                return
            self.state_machine.play_card(card, "P1")
            self._play_card_sfx()   # 出牌音效
            return

        if phase_name == TurnPhase.DRAW.name and self.state_machine is not None:
            self.state_machine.next_phase()

    def get_hand_card_hit(self, pos: tuple[int, int], hand_cards: list[Any]) -> tuple[int, pygame.Rect] | None:
        card_w, card_h = 80, 120
        start_x = 280
        y = 550

        for i in range(len(hand_cards)):
            rect = pygame.Rect(start_x + i * 90, y, card_w, card_h)
            if rect.collidepoint(pos):
                return i, rect
        return None

    def _build_zones(self) -> dict[InteractionZone, pygame.Rect]:
        return {
            InteractionZone.OPPONENT: pygame.Rect(60, 20, self.screen_w - 120, 170),
            InteractionZone.BATTLEFIELD: pygame.Rect(80, 210, self.screen_w - 220, 300),
            InteractionZone.DECK: pygame.Rect(self.screen_w - 180, 270, 120, 220),
            InteractionZone.HAND: pygame.Rect(60, self.screen_h - 190, self.screen_w - 120, 160),
        }

    def _resolve_zone(self, pos: tuple[int, int]) -> InteractionZone:
        for zone, rect in self.zones.items():
            if rect.collidepoint(pos):
                return zone
        return InteractionZone.NONE

    def _current_phase_name(self, state: dict[str, Any]) -> str:
        phase = state.get("phase")
        if phase is None:
            return ""
        if hasattr(phase, "name"):
            return str(phase.name)
        return str(phase)

    def _is_operation_allowed(self, zone: InteractionZone, state: dict[str, Any]) -> bool:
        phase_name = self._current_phase_name(state)
        allowed_map: dict[str, set[InteractionZone]] = {
            "PLAY_P1": {InteractionZone.HAND, InteractionZone.BATTLEFIELD},
            "PLAY_P2": {InteractionZone.OPPONENT, InteractionZone.BATTLEFIELD},
            "REMEDY": {InteractionZone.HAND},
            "DRAW": {InteractionZone.DECK},
        }
        if not phase_name:
            return True
        allowed = allowed_map.get(phase_name, set())
        return zone in allowed

    def _on_left_down(self, pos: tuple[int, int], state: dict[str, Any], logs: list[dict[str, Any]]) -> None:
        # REMEDY 阶段：已在 handle_click 中处理，不再触发 drag
        if self._current_phase_name(state) in (TurnPhase.REMEDY.name, TurnPhase.REMEDY_AI.name):
            return

        zone = self._resolve_zone(pos)
        if zone is InteractionZone.DECK and self._current_phase_name(state) == TurnPhase.ROUND_END.name:
            logs.append(
                {
                    "player": "SYSTEM",
                    "action": "request_replenish",
                    "value": 1,
                    "reason": "deck_click_round_end",
                }
            )
            return

        if zone is InteractionZone.NONE or not self._is_operation_allowed(zone, state):
            logs.append(
                {
                    "player": "SYSTEM",
                    "action": "ignore_click",
                    "value": 0,
                    "reason": "illegal_operation",
                }
            )
            return

        self.drag_state = DragState(active=True, start_pos=pos, zone=zone)
        logs.append(
            {
                "player": "SYSTEM",
                "action": "left_down",
                "value": zone.value,
                "reason": "select_or_drag_start",
            }
        )

    def _on_left_up(self, pos: tuple[int, int], state: dict[str, Any], logs: list[dict[str, Any]]) -> None:
        if not self.drag_state.active:
            return

        target_zone = self._resolve_zone(pos)
        source_zone = self.drag_state.zone
        self.drag_state = DragState()

        if target_zone is InteractionZone.NONE:
            logs.append(
                {
                    "player": "SYSTEM",
                    "action": "cancel_drag",
                    "value": 0,
                    "reason": "drop_outside",
                }
            )
            return

        if not self._is_operation_allowed(target_zone, state):
            logs.append(
                {
                    "player": "SYSTEM",
                    "action": "ignore_drop",
                    "value": 0,
                    "reason": "illegal_operation",
                }
            )
            return

        action = "click" if source_zone == target_zone else "drag_drop"
        logs.append(
            {
                "player": "SYSTEM",
                "action": action,
                "value": f"{source_zone.value}->{target_zone.value}",
                "reason": "left_up",
            }
        )

    def _on_right_click(self, pos: tuple[int, int], state: dict[str, Any], logs: list[dict[str, Any]]) -> None:
        zone = self._resolve_zone(pos)
        if zone is InteractionZone.NONE:
            return
        logs.append(
            {
                "player": "SYSTEM",
                "action": "view_detail",
                "value": zone.value,
                "reason": "right_click",
            }
        )

    def _open_replenish_selector(self, state: dict[str, Any]) -> None:
        deck_rect = self.zones[InteractionZone.DECK]
        btn_w = 46
        btn_h = 28
        gap = 6
        buttons: list[dict[str, Any]] = []
        start_x = deck_rect.x + (deck_rect.width - (btn_w * 5 + gap * 4)) // 2
        y = deck_rect.bottom + 10
        for idx, count in enumerate((1, 2, 3, 4, 5)):
            rect = pygame.Rect(start_x + idx * (btn_w + gap), y, btn_w, btn_h)
            buttons.append(
                {
                    "count": count,
                    "label": f"补{count}",
                    "rect": (rect.x, rect.y, rect.w, rect.h),
                }
            )
        ui = state.setdefault("ui", {})
        ui["replenish_selector"] = {"visible": True, "buttons": buttons}

    def _handle_replenish_button_click(
        self,
        pos: tuple[int, int],
        state: dict[str, Any],
        logs: list[dict[str, Any]],
    ) -> bool:
        ui = state.setdefault("ui", {})
        selector = ui.get("replenish_selector")
        if not selector or not selector.get("visible"):
            return False

        for button in selector.get("buttons", []):
            rect_data = button.get("rect")
            if not rect_data:
                continue
            rect = pygame.Rect(*rect_data)
            if rect.collidepoint(pos):
                if self.state_machine is not None:
                    self.state_machine.bind_runtime_state(state)
                    drawn = self.state_machine.request_replenish(int(button.get("count", 0)))
                else:
                    drawn = 0
                ui["replenish_selector"] = None
                logs.append(
                    {
                        "player": "SYSTEM",
                        "action": "replenish",
                        "value": drawn,
                        "reason": f"pick_{button.get('count', 0)}",
                    }
                )
                return True
        return False
