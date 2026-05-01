"""network/online_game.py - 联机游戏主循环（Host 端 + Client 端）。

两个入口函数：
  - run_online_host(screen, host, ...) → Host（P1）视角，运行完整 state_machine
  - run_online_client(screen, client, ...) → Client（P2）视角，只渲染 + 发操作

联机模式下卡牌、回合机制与 AI 模式完全相同，唯一区别：
  - P2 操作来源：AI.choose_cards() → 网络接收
  - Client 端不运行 state_machine
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Optional

import pygame

from core.event_bus import EventBus
from core.input_router import InputRouter
from core.models import Card, Deck
from core.player_profile import get_player_name, get_display_id
from core.state_machine import GameStateMachine, TurnPhase, MANA_INITIAL
from core.save_manager import (
    create_fresh_game_stats,
)
from network.game_host import GameHost
from network.game_client import GameClient
from ui.renderer import Renderer

from main import (
    _load_full_deck,
    _wait_game_over,
    apply_brightness,
    log_event,
    trigger_draw_animation,
    SCREEN_SIZE,
    FPS,
)
from core.music_manager import MusicManager


# ═══════════════════════════════════════════════════════════════
#  Host 端（P1 视角）
# ═══════════════════════════════════════════════════════════════

def build_online_state(state_machine: GameStateMachine) -> dict[str, Any]:
    """构建联机初始游戏状态（与 build_initial_state 相同逻辑）。"""
    full_deck = _load_full_deck()
    if not full_deck:
        log_event("[Deck] 警告：牌库为空", "error")

    # 构建 CATEGORY_MAP
    category_map: dict[str, list[int]] = {}
    for card in full_deck:
        eid = str(getattr(card, "effect_id", "") or "")
        if eid:
            prefix = eid.split("_")[0].upper()
            category_map.setdefault(prefix, []).append(card.id)

    # shuffle → P1:5 + P2:5 + 牌堆:44
    random.shuffle(full_deck)
    p1_hand = full_deck[:5]
    p2_hand = full_deck[5:10]
    remaining = full_deck[10:]

    log_event(
        f"[Online] 牌库总数: {len(full_deck)} | P1手牌: {len(p1_hand)} "
        f"| P2手牌: {len(p2_hand)} | 牌堆: {len(remaining)}"
    )

    stats = create_fresh_game_stats()

    state: dict[str, Any] = {
        "phase": state_machine.current_phase,
        "phase_started_at_ms": pygame.time.get_ticks(),
        "time_left": 90,
        "players": {
            "P1": {"hp": 10, "max_hp": 10},
            "P2": {"hp": 10, "max_hp": 10},
        },
        "hands": {"P1": list(p1_hand), "P2": list(p2_hand)},
        "deck": Deck(cards=list(remaining)),
        "deck_size": len(remaining),
        "played_cards": {"P1": [], "P2": []},
        "pending_play": {"P1": [], "P2": []},
        "played_cards_history": [],
        "temp": {},
        "toasts": [],
        "ui": {"hovered_zone": ""},
        "winner": None,
        "floating_texts": [],
        "round_count": 0,
        "stats": stats,
        "category_map": category_map,
    }

    return state


def _get_played_card_rects(played_cards: list[Card]) -> list[pygame.Rect]:
    """与 main.py 中 _get_played_card_rects 相同逻辑。"""
    CARD_W, CARD_H = 80, 120
    slot_x, slot_y, slot_w, slot_h = 120, 380, 120, 90
    card_h = min(slot_h, CARD_H)
    card_w = int(card_h * CARD_W / CARD_H)
    step = card_w + 2
    start_x = slot_x + (slot_w - card_w * len(played_cards)) // 2
    draw_y = slot_y + (slot_h - card_h) // 2

    rects: list[pygame.Rect] = []
    for i in range(min(len(played_cards), 2)):
        rects.append(pygame.Rect(start_x + i * step, draw_y, card_w, card_h))
    return rects


def run_online_host(
    screen: pygame.Surface,
    host: GameHost,
    music_manager: Optional[MusicManager] = None,
    settings: Optional[dict[str, Any]] = None,
) -> None:
    """联机 Host 主循环（P1 视角）。

    与 run_game() 几乎相同，区别：
      1. state_machine.is_online = True
      2. 每帧从 host.poll_actions() 获取 P2 操作 → feed_online_action
      3. 每帧同步 state 给 Client
      4. 无 AI 延迟
    """
    log_event("[OnlineHost] 启动联机 Host（P1）...")

    if settings is None:
        from core.settings_manager import load_settings
        settings = load_settings()

    # ── 初始化 ───────────────────────────────────────────────
    event_bus = EventBus()
    state_machine = GameStateMachine(event_bus)
    state_machine.is_online = True  # 🔑 联机模式标志
    input_router = InputRouter(SCREEN_SIZE, state_machine)
    renderer = Renderer(screen, SCREEN_SIZE)

    if music_manager is not None:
        music_manager.update_settings(settings)

    # ── 先手选择 ─────────────────────────────────────────────
    from ui.order_dialog import OrderDialog
    order_dialog = OrderDialog(screen, SCREEN_SIZE)
    order_dialog.show()
    screen.fill((28, 36, 46))
    order_dialog.draw(screen)
    pygame.display.flip()

    order_clock = pygame.time.Clock()
    while order_dialog.visible:
        dt = order_clock.tick(FPS) / 1000.0
        order_dialog.update(dt)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                host.close()
                return
            order_dialog.handle_event(event)
        order_dialog.draw(screen)
        pygame.display.flip()

    first_player = order_dialog.result or "P1"
    state_machine.first_player = first_player
    log_event(f"[OnlineHost] 先手: {first_player}")

    # ── 构建初始状态 ─────────────────────────────────────────
    state = build_online_state(state_machine)
    state_machine.bind_runtime_state(state)

    if first_player == "P1":
        state_machine.current_phase = TurnPhase.PLAY_P1
    else:
        state_machine.current_phase = TurnPhase.PLAY_P2
    state["phase"] = state_machine.current_phase
    now = pygame.time.get_ticks()
    state["phase_started_at_ms"] = now
    state_machine._phase_entered_at_ms = now
    log_event("━━━ Online Round 1 开始 ━━━")

    # ── 主循环 ───────────────────────────────────────────────
    clock = pygame.time.Clock()

    while True:
        dt = clock.tick(FPS) / 1000.0
        events = pygame.event.get()
        phase = state_machine.current_phase
        ui_state = state.setdefault("ui", {})
        ui_state.setdefault("tooltip_card", None)
        ui_state.setdefault("tooltip_anchor_rect", None)

        # ── 接收 Client 操作 ─────────────────────────────────
        online_actions = host.poll_actions()
        for action in online_actions:
            state_machine.feed_online_action(action)

        for event in events:
            if event.type == pygame.QUIT:
                host.close()
                return

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                is_play_phase = phase in (TurnPhase.PLAY_P1, TurnPhase.REMEDY)

                if is_play_phase:
                    pending_cards = state.get("pending_play", {}).get("P1", [])
                    if pending_cards and phase == TurnPhase.PLAY_P1:
                        played_rects = _get_played_card_rects(pending_cards)
                        for idx, rect_pair in enumerate(zip(pending_cards, played_rects)):
                            card, r = rect_pair
                            if r.collidepoint(event.pos):
                                if state_machine.undo_play_card(card, "P1"):
                                    log_event(f"[退牌] P1 撤回: {card.name}")
                                break
                        else:
                            p1_cards = state.get("hands", {}).get("P1", [])
                            hit = renderer.get_hand_card_hit(event.pos, p1_cards)
                            if hit is not None:
                                card_index = hit[0]
                                if 0 <= card_index < len(p1_cards):
                                    card = p1_cards[card_index]
                                    if state_machine.play_card(card, "P1"):
                                        pass
                    else:
                        p1_cards = state.get("hands", {}).get("P1", [])
                        hit = renderer.get_hand_card_hit(event.pos, p1_cards)
                        if hit is not None:
                            card_index = hit[0]
                            if 0 <= card_index < len(p1_cards):
                                card = p1_cards[card_index]
                                if phase == TurnPhase.REMEDY:
                                    success, msg = state_machine.play_card_remedy(card, "P1")
                                    if success:
                                        log_event(f"[补救] P1: {card.name} - {msg}")
                                else:
                                    if state_machine.play_card(card, "P1"):
                                        pass

                # 认输
                surrender_btn = state.get("surrender_btn_rect")
                if surrender_btn and hasattr(surrender_btn, "collidepoint"):
                    if surrender_btn.collidepoint(event.pos):
                        state["winner"] = "P2"
                        state["phase"] = "GAME_OVER"
                        state_machine.current_phase = TurnPhase.GAME_OVER

                # 点击牌库结束出牌
                if phase == TurnPhase.PLAY_P1:
                    deck_rect = renderer.zones.get("deck")
                    if deck_rect and deck_rect.collidepoint(event.pos):
                        state_machine.finish_p1_turn()

                # ROUND_END 补牌
                if phase == TurnPhase.ROUND_END:
                    deck_rect = renderer.zones.get("deck")
                    if deck_rect and deck_rect.collidepoint(event.pos):
                        deck = state.get("deck")
                        if deck and len(deck.cards) > 0:
                            drawn = state_machine.request_replenish(1)
                            if drawn > 0:
                                state["draw_anim"] = {
                                    "active": True,
                                    "start_time": pygame.time.get_ticks(),
                                    "progress": 0.0,
                                    "pending_cards": [],
                                    "player_key": "P1"
                                }

            elif event.type == pygame.MOUSEMOTION:
                ui_state["tooltip_card"] = None
                ui_state["tooltip_anchor_rect"] = None
                deck_rect = renderer.zones.get("deck")
                if deck_rect and deck_rect.collidepoint(event.pos):
                    state.setdefault("ui", {})["deck_hovered"] = True
                else:
                    state.setdefault("ui", {})["deck_hovered"] = False

        # ── 空格结束出牌 ─────────────────────────────────────
        keys = pygame.key.get_pressed()
        if keys[pygame.K_SPACE]:
            if state_machine.current_phase == TurnPhase.PLAY_P1:
                state_machine.finish_p1_turn()

        # ── 状态机更新 ───────────────────────────────────────
        state_machine.update(dt)

        # ── 超时检测 ─────────────────────────────────────────
        now_ms = pygame.time.get_ticks()
        elapsed = max(0, (now_ms - state.get("phase_started_at_ms", now_ms)) // 1000)
        current_phase = state_machine.current_phase

        if current_phase == TurnPhase.PLAY_P1 and elapsed >= 90:
            log_event("[Timeout] P1 出牌超时")
            state["winner"] = "P2"
            state["phase"] = "GAME_OVER"
            state_machine.current_phase = TurnPhase.GAME_OVER

        if current_phase == TurnPhase.REMEDY and elapsed >= 30:
            state["winner"] = "P2"
            state["phase"] = "GAME_OVER"
            state_machine.current_phase = TurnPhase.GAME_OVER

        # ── 补牌动画 ─────────────────────────────────────────
        anim = state.get("draw_anim", {})
        if anim.get("active"):
            start_time = int(anim.get("start_time", 0))
            progress = min(1.0, (now_ms - start_time) / 500)
            anim["progress"] = progress
            if progress >= 1.0:
                anim["active"] = False
                pending_cards = anim.get("pending_cards", [])
                player_key = anim.get("player_key", "P1")
                state["hands"].setdefault(player_key, []).extend(pending_cards)

        # ── 飘字 ─────────────────────────────────────────────
        ft_requests = state.get("floating_texts", [])
        if ft_requests:
            for req in ft_requests:
                if isinstance(req, dict):
                    renderer.floating_text_manager.add_text(
                        text=req.get("text", ""),
                        x=int(req.get("x", 0)),
                        y=int(req.get("y", 0)),
                        color=tuple(req.get("color", (255, 51, 51))),
                        font_size=int(req.get("font_size", 26)),
                    )
            state["floating_texts"] = []

        renderer.floating_text_manager.update(dt)

        # ── 战报 ─────────────────────────────────────────────
        toasts = state.get("toasts", [])
        active_toasts = []
        for toast in toasts:
            toast_age = now_ms - int(toast.get("time", 0))
            if toast_age < 2500:
                active_toasts.append(toast)
        state["toasts"] = active_toasts

        # ── 渲染 ─────────────────────────────────────────────
        phase_timeout = 90
        if current_phase == TurnPhase.REMEDY:
            phase_timeout = 30
        state["time_left"] = max(0, phase_timeout - elapsed)
        renderer.draw(state, [])
        apply_brightness(screen, float(settings.get("screen_brightness", 1.0)))

        # 悬停提示
        mouse_pos = pygame.mouse.get_pos()
        p1_cards = state.get("hands", {}).get("P1", [])
        hit = renderer.get_hand_card_hit(mouse_pos, p1_cards)
        if hit is not None:
            hovered_card = p1_cards[hit[0]]
            renderer.draw_card_tooltip(screen, hovered_card, mouse_pos[0], mouse_pos[1])

        # 联机标识
        _fnt = pygame.font.Font("assets/fonts/SourceHanSansSC-Regular.otf", 13) if Path("assets/fonts/SourceHanSansSC-Regular.otf").exists() else pygame.font.SysFont("simhei", 13)
        online_surf = _fnt.render(f"🌐 联机对战 - 你是 P1（Host）", True, (100, 200, 255))
        screen.blit(online_surf, (10, 10))

        pygame.display.flip()

        # ── 同步状态给 Client ────────────────────────────────
        host.send_state(state)

        # ── 游戏结束 ─────────────────────────────────────────
        if state_machine.current_phase == TurnPhase.GAME_OVER:
            _wait_game_over(screen, renderer, state, clock)
            host.close()
            return


# ═══════════════════════════════════════════════════════════════
#  Client 端（P2 视角）
# ═══════════════════════════════════════════════════════════════

def run_online_client(
    screen: pygame.Surface,
    client: GameClient,
    music_manager: Optional[MusicManager] = None,
    settings: Optional[dict[str, Any]] = None,
) -> None:
    """联机 Client 主循环（P2 视角）。

    Client 不运行 state_machine，只：
      1. 从网络获取渲染状态
      2. 在 PLAY_P2 / REMEDY 阶段处理 P2 的鼠标操作
      3. 发送操作给 Host
    """
    log_event("[OnlineClient] 启动联机 Client（P2）...")

    if settings is None:
        from core.settings_manager import load_settings
        settings = load_settings()

    renderer = Renderer(screen, SCREEN_SIZE)
    clock = pygame.time.Clock()

    # P2 预出牌缓存（本地暂存，确认后一次性发送）
    p2_pending_card_ids: list[int] = []

    # 等待第一个状态（Host 需要完成先手选择，给足时间）
    log_event("[OnlineClient] 等待 Host 开始游戏...")
    wait_font = None
    try:
        fpath = Path("assets/fonts/SourceHanSansSC-Regular.otf")
        if fpath.exists():
            wait_font = pygame.font.Font(str(fpath), 22)
        else:
            wait_font = pygame.font.SysFont("simhei", 22)
    except Exception:
        wait_font = pygame.font.SysFont("simhei", 22)

    remote_state = client.get_latest_state()
    timeout_counter = 0
    while not remote_state and timeout_counter < 1800:  # 最多等 30 秒
        dt = clock.tick(FPS) / 1000.0

        # 显示等待画面
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                client.close()
                return

        screen.fill((26, 43, 58))
        dots = "." * ((timeout_counter // 30) % 4)
        wait_surf = wait_font.render(f"等待 Host 开始游戏{dots}", True, (190, 210, 230))
        screen.blit(wait_surf, wait_surf.get_rect(center=(SCREEN_SIZE[0]//2, SCREEN_SIZE[1]//2)))
        hint_surf = wait_font.render("（请在 Host 窗口完成先手选择）", True, (130, 145, 165))
        screen.blit(hint_surf, hint_surf.get_rect(center=(SCREEN_SIZE[0]//2, SCREEN_SIZE[1]//2 + 40)))
        pygame.display.flip()

        remote_state = client.get_latest_state()
        timeout_counter += 1

    if not remote_state:
        log_event("[OnlineClient] 等待状态超时", "error")
        client.close()
        return

    log_event("[OnlineClient] 收到初始状态，开始游戏")

    while True:
        dt = clock.tick(FPS) / 1000.0
        events = pygame.event.get()

        # 获取最新状态
        remote_state = client.get_latest_state()
        if not remote_state:
            # 连接断开
            log_event("[OnlineClient] 与 Host 断开连接", "error")
            break

        phase_str = str(remote_state.get("phase", ""))
        is_game_over = phase_str == "GAME_OVER" or remote_state.get("winner") is not None

        # ── 构建 P2 手牌 Card 对象（从 JSON 恢复）─────────────
        p2_hand_raw = remote_state.get("hands", {}).get("P2", [])
        p2_hand = [_dict_to_card(c) for c in p2_hand_raw if isinstance(c, dict) and not c.get("hidden")]

        for event in events:
            if event.type == pygame.QUIT:
                client.close()
                return

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # ── PLAY_P2 阶段：P2 出牌 ─────────────────────
                if phase_str == "PLAY_P2":
                    # 点击牌库 → 结束出牌
                    deck_rect = renderer.zones.get("deck")
                    if deck_rect and deck_rect.collidepoint(event.pos):
                        # 发送所有 pending 的出牌
                        if p2_pending_card_ids:
                            for cid in p2_pending_card_ids:
                                client.send_action("play_card", {"card_id": cid})
                            p2_pending_card_ids.clear()
                            client.send_action("finish_turn_with_commit")
                        else:
                            client.send_action("finish_turn")
                        continue

                    # 点击手牌出牌
                    if p2_hand:
                        hit = renderer.get_hand_card_hit(event.pos, p2_hand)
                        if hit is not None:
                            card_index = hit[0]
                            if 0 <= card_index < len(p2_hand):
                                card = p2_hand[card_index]
                                card_id = int(getattr(card, "id", -1))
                                if card_id >= 0:
                                    p2_pending_card_ids.append(card_id)
                                    log_event(f"[OnlineClient] P2 预选: {card.name}")

                # ── REMEDY_AI 阶段：P2 补救 ───────────────────
                elif phase_str == "REMEDY_AI":
                    if p2_hand:
                        hit = renderer.get_hand_card_hit(event.pos, p2_hand)
                        if hit is not None:
                            card_index = hit[0]
                            if 0 <= card_index < len(p2_hand):
                                card = p2_hand[card_index]
                                card_id = int(getattr(card, "id", -1))
                                client.send_action("remedy_play_card", {"card_id": card_id})
                                log_event(f"[OnlineClient] P2 补救出牌: {card.name}")

        # ── 空格结束出牌 ─────────────────────────────────────
        keys = pygame.key.get_pressed()
        if keys[pygame.K_SPACE] and phase_str == "PLAY_P2":
            if p2_pending_card_ids:
                for cid in p2_pending_card_ids:
                    client.send_action("play_card", {"card_id": cid})
                p2_pending_card_ids.clear()
                client.send_action("finish_turn_with_commit")
            else:
                client.send_action("finish_turn")

        # ── 渲染远端状态 ─────────────────────────────────────
        # 构建一个兼容 renderer 的 state dict
        render_state = _build_render_state(remote_state, p2_pending_card_ids)
        renderer.draw(render_state, [])
        apply_brightness(screen, float(settings.get("screen_brightness", 1.0)))

        # 联机标识
        _fnt = pygame.font.Font("assets/fonts/SourceHanSansSC-Regular.otf", 13) if Path("assets/fonts/SourceHanSansSC-Regular.otf").exists() else pygame.font.SysFont("simhei", 13)
        online_surf = _fnt.render(f"🌐 联机对战 - 你是 P2（Client）", True, (100, 200, 255))
        screen.blit(online_surf, (10, 10))

        # 悬停提示
        mouse_pos = pygame.mouse.get_pos()
        if p2_hand:
            hit = renderer.get_hand_card_hit(mouse_pos, p2_hand)
            if hit is not None:
                hovered_card = p2_hand[hit[0]]
                renderer.draw_card_tooltip(screen, hovered_card, mouse_pos[0], mouse_pos[1])

        pygame.display.flip()

        # ── 游戏结束 ─────────────────────────────────────────
        if is_game_over:
            winner = remote_state.get("winner", "")
            log_event(f"[OnlineClient] 游戏结束: {winner}")
            # 简单等待几秒后返回
            pygame.time.wait(3000)
            client.close()
            return


# ═══════════════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════════════

def _dict_to_card(d: dict[str, Any]) -> Card:
    """将 JSON 字典转回 Card 对象。"""
    return Card(
        id=int(d.get("id", 0)),
        name=str(d.get("name", "")),
        cost=int(d.get("cost", 0)),
        atk=int(d.get("atk", 0)),
        faction=str(d.get("faction", "")),
        type=str(d.get("type", "")),
        limit_flag=bool(d.get("limit_flag", False)),
        effect_id=str(d.get("effect_id", "")),
        description=str(d.get("description", "")),
        image_file=str(d.get("image_file", "")),
    )


def _build_render_state(remote: dict[str, Any], pending_ids: list[int]) -> dict[str, Any]:
    """将远端状态转换为 renderer 兼容的 state dict。

    Client 视角：P2 是自己，所以需要将 P2 的手牌渲染在底部。
    """
    # 将 remote JSON 状态转换为与本地 state 结构兼容的格式
    state: dict[str, Any] = {
        "phase": remote.get("phase", ""),
        "time_left": remote.get("time_left", 90),
        "winner": remote.get("winner"),
        "round_count": remote.get("round_count", 0),
        "players": remote.get("players", {}),
        "hands": {},
        "played_cards": {},
        "pending_play": {},
        "deck_size": remote.get("deck_size", 0),
        "toasts": remote.get("toasts", []),
        "floating_texts": remote.get("floating_texts", []),
        "temp": remote.get("temp", {}),
        "ui": {"hovered_zone": ""},
    }

    # 手牌：Card 对象列表
    for p_key in ("P1", "P2"):
        raw_list = remote.get("hands", {}).get(p_key, [])
        cards = []
        for item in raw_list:
            if isinstance(item, dict):
                if item.get("hidden"):
                    cards.append(Card(id=0, name="?", cost=0, atk=0, faction="", type=""))
                else:
                    cards.append(_dict_to_card(item))
        state["hands"][p_key] = cards

    # 出牌
    for p_key in ("P1", "P2"):
        raw_list = remote.get("played_cards", {}).get(p_key, [])
        state["played_cards"][p_key] = [_dict_to_card(c) for c in raw_list if isinstance(c, dict)]

    # 预出牌（P2 的 pending 从本地缓存恢复）
    p2_hand = state["hands"].get("P2", [])
    p2_pending = [c for c in p2_hand if getattr(c, "id", -1) in pending_ids]
    state["pending_play"] = {
        "P1": [],
        "P2": p2_pending,
    }

    # 牌堆用 Deck 对象
    deck_size = remote.get("deck_size", 0)
    state["deck"] = Deck(cards=[Card(id=0, name="", cost=0, atk=0, faction="", type="") for _ in range(deck_size)])

    # phase_started_at_ms
    state["phase_started_at_ms"] = pygame.time.get_ticks()

    return state
