"""main.py - PVZ 植物卡牌对战主入口。

启动流程（Scene 状态机）：
  INTRO → (动画完成) → LOADING → (进度满) → MENU → (点人机) → CONFIRM → (确认) → GAME → (结束) → MENU

Scene 枚举：
  - INTRO:   致谢入场动画（黑屏→淡入→停留，共6秒）
  - LOADING: 加载界面（滚动进度条）
  - MENU:    主菜单（4按钮）
  - CONFIRM: 阵前曲确认对话框（蓝底模态）
  - GAME:    游戏主循环

核心原则：main.py 不包含任何阶段推进逻辑，全部由 state_machine.update(dt) 驱动。
"""
from __future__ import annotations

import json
import random
import shutil
from enum import Enum, auto
from pathlib import Path
from typing import Any, Optional

import pygame

from utils.path_utils import get_resource_path, get_user_data_dir
from core.event_bus import EventBus
from core.input_router import InputRouter
from core.models import Card, Deck
from core.music_manager import MusicManager
from core.settings_manager import SettingsManager, load_settings, save_settings
from core.state_machine import GameStateMachine, TurnPhase
from core.save_manager import (
    load_save_data,
    save_save_data,
    create_fresh_game_stats,
    merge_game_stats_to_save,
    check_achievements,
)
from ui.intro_screen import IntroScreen
from ui.loading_screen import LoadingScreen, run_loading_screen
from ui.main_menu import MainMenu, run_main_menu
from ui.renderer import Renderer


# ── 常量 ─────────────────────────────────────────────────────
SCREEN_SIZE = (1024, 768)
FPS = 60

_SFX_ROOT = get_resource_path("assets/sfx")
_SFX_UNDOCK = "card_lighter.wav"

DEBUG_LOG: bool = False
DEBUG_HOVER: bool = False


# ── Scene 枚举 ───────────────────────────────────────────────

class Scene(Enum):
    """游戏场景枚举。"""
    INTRO = auto()
    LOADING = auto()
    MENU = auto()
    SETTINGS = auto()
    CONFIRM = auto()
    GAME = auto()


# ── 日志 ─────────────────────────────────────────────────────

def log_event(msg: str, level: str = "info") -> None:
    """统一日志函数。

    - level="error" → 始终输出
    - level="info"  → 仅当 DEBUG_LOG=True 时输出
    - 鼠标悬停/移动相关日志 → 仅当 DEBUG_HOVER=True 时输出
    """
    if level == "error":
        print(msg)
    elif level == "hover":
        if DEBUG_HOVER:
            print(msg)
    else:
        if DEBUG_LOG:
            print(msg)


# ── 牌库加载 ─────────────────────────────────────────────────

_FULL_DECK: list[Card] = []
_DECK_LOADED: bool = False


def _load_full_deck() -> list[Card]:
    """从 config/cards.json 加载完整牌库（仅加载一次）。

    - Path(__file__).parent 构建绝对路径
    - 文件不存在 / JSON 语法错误 → error 日志 + SystemExit
    - 字段容错：description/effect_id/image_file 缺失默认空字符串
    - faction 原样保留，不做任何映射
    """
    global _FULL_DECK, _DECK_LOADED
    if _DECK_LOADED:
        return _FULL_DECK

    cards_path = get_resource_path("config/cards.json")
    if not cards_path.exists():
        log_event(f"[Deck] 卡牌配置文件不存在: {cards_path}", "error")
        log_event("[Deck] 程序无法继续运行，请确认 config/cards.json 是否就位。", "error")
        raise SystemExit(1)

    try:
        raw = Path(cards_path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log_event(
            f"[Deck] JSON 语法错误: {e.msg}\n[Deck] 文件: {cards_path}\n"
            f"[Deck] 行 {e.lineno}, 列 {e.colno}: {e.msg}",
            "error",
        )
        raise SystemExit(1)

    templates = data.get("cards")
    if not isinstance(templates, list):
        log_event(
            f'[Deck] JSON 根节点缺少 "cards" 数组或格式不正确 (类型: {type(templates).__name__})',
            "error",
        )
        raise SystemExit(1)

    if not templates:
        log_event("[Deck] cards.json 中卡牌数组为空，游戏将以空牌堆运行。")

    seen_ids: set[int] = set()
    for idx, entry in enumerate(templates):
        if not isinstance(entry, dict):
            log_event(f"[Deck] 跳过无效条目 #{idx}: 不是 JSON 对象")
            continue
        card_id = int(entry.get("id", -1))
        if card_id in seen_ids:
            log_event(f"[Deck] 跳过重复 ID {card_id}")
            continue
        seen_ids.add(card_id)

        try:
            card = Card(
                id=card_id,
                name=str(entry.get("name", f"未知卡牌#{card_id}")),
                cost=int(entry.get("cost", 0)),
                atk=int(entry.get("atk", 0)),
                faction=str(entry.get("faction", "")),
                type=str(entry.get("type", "")),
                limit_flag=bool(entry.get("limit_flag", False)),
                effect_id=str(entry.get("effect_id", "")),
                description=str(entry.get("description", "")),
                image_file=str(entry.get("image_file", "")),
            )
            _FULL_DECK.append(card)
        except (ValueError, TypeError) as exc:
            log_event(f"[Deck] 跳过条目 #{idx} ({entry.get('name', '?')}): 字段解析失败 - {exc}")

    _DECK_LOADED = True
    log_event(f"[Deck] 配置文件: {cards_path}")
    log_event(f"[Deck] 成功解析 {len(_FULL_DECK)} 张卡牌（全局唯一牌库）")
    if _FULL_DECK:
        sample = _FULL_DECK[0]
        log_event(
            f"[Deck] 锚点样本: ID={sample.id}, "
            f'Name="{sample.name}", Cost={sample.cost}, Atk={sample.atk}'
        )
    else:
        log_event("[Deck] 未成功加载任何卡牌。", "error")
    return _FULL_DECK


# ── 辅助函数 ─────────────────────────────────────────────────

def _get_played_card_rects(played_cards: list[Card]) -> list[pygame.Rect]:
    """获取 P1 出牌槽中已出牌的 Rect 列表（与 renderer slot 位置一致）。

    坐标与 Renderer._draw_played_cards_in_slot 保持同步：
      field = (80, 210, 804, 300)  → p1_slot = (120, 380, 120, 90)
      card_h = min(90, 120) = 90, card_w = 60, step = 62
    """
    # 与 renderer.zones["battlefield"] 和 _draw_played_cards_in_slot 保持一致
    CARD_W, CARD_H = 80, 120
    slot_x, slot_y, slot_w, slot_h = 120, 380, 120, 90
    card_h = min(slot_h, CARD_H)   # 90
    card_w = int(card_h * CARD_W / CARD_H)  # 60
    step = card_w + 2  # 62
    start_x = slot_x + (slot_w - card_w * len(played_cards)) // 2
    draw_y = slot_y + (slot_h - card_h) // 2  # 380

    rects: list[pygame.Rect] = []
    for i in range(min(len(played_cards), 2)):
        rects.append(pygame.Rect(start_x + i * step, draw_y, card_w, card_h))
    return rects


def trigger_draw_animation(
    state: dict[str, Any],
    player_key: str,
    new_cards: list[Card],
) -> None:
    """触发补牌动画，拦截直接发牌改为动画驱动。

    Args:
        state: 游戏状态字典
        player_key: 目标玩家 "P1" 或 "P2"
        new_cards: 需要补给的卡牌列表
    """
    anim = state.setdefault("draw_anim", {})
    anim["count"] = len(new_cards)
    anim["pending_cards"] = list(new_cards)
    anim["start_time"] = pygame.time.get_ticks()
    anim["active"] = True
    anim["progress"] = 0.0
    anim["player_key"] = player_key


def build_initial_state(state_machine: GameStateMachine) -> dict[str, Any]:
    """构建初始游戏状态字典，绑定到 state_machine。

    - HP=10
    - 读取全部 54 张唯一卡牌 → shuffle → P1 抽 5 张 → P2 抽 5 张
    - 剩余 44 张进入牌堆
    - 自动构建 CATEGORY_MAP（按 effect_id 前缀归类卡牌 ID）
    - buffs 改为列表结构：[{"type":str,"value":int,"duration":int,"icon_code":str}]
    """
    full_deck = _load_full_deck()

    if not full_deck:
        log_event("[Deck] 警告：牌库为空，双方手牌为空", "error")

    # 构建 CATEGORY_MAP（按 effect_id 前缀归类卡牌 ID）
    category_map: dict[str, list[int]] = {}
    for card in full_deck:
        eid = str(getattr(card, "effect_id", "") or "")
        if eid:
            prefix = eid.split("_")[0].upper()
            category_map.setdefault(prefix, []).append(card.id)

    log_event(f"[Init] CATEGORY_MAP: {category_map}")

    # shuffle → P1:5 + P2:5 + 牌堆:44
    random.shuffle(full_deck)
    p1_hand = full_deck[:5]
    p2_hand = full_deck[5:10]
    remaining = full_deck[10:]

    log_event(
        f"[Init] 牌库总数: {len(full_deck)} | P1手牌: {len(p1_hand)} "
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


# ── 游戏主循环 ───────────────────────────────────────────────

def run_game(
    screen: pygame.Surface,
    music_manager: Optional[MusicManager] = None,
    settings: Optional[dict[str, Any]] = None,
) -> None:
    """游戏主循环。所有阶段推进由 state_machine.update(dt) 驱动。"""
    log_event("[Game] 加载人机对战...")

    if settings is None:
        settings = load_settings()

    # ── 初始化 SFX ───────────────────────────────────────────
    sfx_undock: Optional[pygame.mixer.Sound] = None
    sfx_path = _SFX_ROOT / _SFX_UNDOCK
    if sfx_path.exists():
        try:
            sfx_undock = pygame.mixer.Sound(str(sfx_path))
            vol = float(settings.get("sfx_volume", 0.7))
            sfx_undock.set_volume(vol)
        except Exception as exc:
            log_event(f"[SFX] 加载出牌音效失败: {exc}", "error")

    # ── 初始化游戏核心 ───────────────────────────────────────
    event_bus = EventBus()
    state_machine = GameStateMachine(event_bus)
    input_router = InputRouter(SCREEN_SIZE, state_machine)
    input_router.set_debug_hover(DEBUG_HOVER)
    renderer = Renderer(screen, SCREEN_SIZE)

    if music_manager is not None:
        music_manager.update_settings(settings)

    # ── 先手选择 ─────────────────────────────────────────────
    from ui.order_dialog import OrderDialog

    order_dialog = OrderDialog(screen, SCREEN_SIZE)
    order_dialog.show()

    # 先渲染一帧游戏背景作为对话框底图
    screen.fill((28, 36, 46))
    order_dialog.draw(screen)
    pygame.display.flip()

    order_clock = pygame.time.Clock()
    while order_dialog.visible:
        dt = order_clock.tick(FPS) / 1000.0
        order_dialog.update(dt)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return
            order_dialog.handle_event(event)
        order_dialog.draw(screen)
        pygame.display.flip()

    first_player = order_dialog.result or "P1"
    log_event(f"[Game] 先手选择: {first_player}")

    state_machine.first_player = first_player

    # ── 构建初始状态 ─────────────────────────────────────────
    state = build_initial_state(state_machine)
    state_machine.bind_runtime_state(state)

    # 切换到 PLAY_P1（或 PLAY_P2）
    if first_player == "P1":
        state_machine.current_phase = TurnPhase.PLAY_P1
    else:
        state_machine.current_phase = TurnPhase.PLAY_P2
    state["phase"] = state_machine.current_phase
    # 同步 state_machine 的 _phase_entered_at_ms
    now = pygame.time.get_ticks()
    state["phase_started_at_ms"] = now
    state_machine._phase_entered_at_ms = now
    log_event("━━━ Round 1 开始 ━━━")

    # ── 游戏主循环 ───────────────────────────────────────────
    clock = pygame.time.Clock()
    pause_active: bool = False
    _pause_accumulated_ms: int = 0  # 累计暂停时长（毫秒），恢复时补偿倒计时

    while True:
        dt = clock.tick(FPS) / 1000.0

        # ── 事件处理 ─────────────────────────────────────────
        events = pygame.event.get()
        frame_logs: list[dict[str, Any]] = []

        # 当前阶段（事件处理和超时检测都需要）
        phase = state_machine.current_phase

        # 初始化 UI 状态
        ui_state = state.setdefault("ui", {})
        ui_state.setdefault("tooltip_card", None)
        ui_state.setdefault("tooltip_anchor_rect", None)

        for event in events:
            if event.type == pygame.QUIT:
                return

            # ── ESC 暂停 ──────────────────────────────────────
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                if not pause_active:
                    pause_active = True
                    _pause_start_ms = pygame.time.get_ticks()
                    log_event("[Pause] ESC 暂停游戏")
                continue

            if pause_active:
                continue

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # ── 判断当前阶段是否允许 P1 出牌 ───────────────
                is_play_phase = phase in (TurnPhase.PLAY_P1, TurnPhase.REMEDY)

                if is_play_phase:
                    # ── 点击预出牌区撤回（仅 PLAY_P1 阶段有预出牌区）──
                    pending_cards = state.get("pending_play", {}).get("P1", [])
                    if pending_cards and phase == TurnPhase.PLAY_P1:
                        played_rects = _get_played_card_rects(pending_cards)
                        for idx, rect in enumerate(zip(pending_cards, played_rects)):
                            card, r = rect
                            if r.collidepoint(event.pos):
                                if state_machine.undo_play_card(card, "P1"):
                                    log_event(f"[退牌] P1 从预出牌区撤回: {card.name}")
                                    if sfx_undock:
                                        sfx_undock.play()
                                break
                        else:
                            # 点击其他区域：尝试从手牌出牌
                            p1_cards = state.get("hands", {}).get("P1", [])
                            hit = renderer.get_hand_card_hit(event.pos, p1_cards)
                            if hit is not None:
                                card_index = hit[0]
                                if 0 <= card_index < len(p1_cards):
                                    card = p1_cards[card_index]
                                    if state_machine.play_card(card, "P1"):
                                        if sfx_undock:
                                            sfx_undock.play()
                    else:
                        # 预出牌区为空或 REMEDY 阶段：点击手牌出牌
                        p1_cards = state.get("hands", {}).get("P1", [])
                        hit = renderer.get_hand_card_hit(event.pos, p1_cards)
                        if hit is not None:
                            card_index = hit[0]
                            if 0 <= card_index < len(p1_cards):
                                card = p1_cards[card_index]
                                if phase == TurnPhase.REMEDY:
                                    # 补救阶段使用专用出牌方法
                                    success, msg = state_machine.play_card_remedy(card, "P1")
                                    if success:
                                        log_event(f"[补救出牌] P1: {card.name} - {msg}")
                                        if sfx_undock:
                                            sfx_undock.play()
                                    else:
                                        log_event(f"[补救拦截] {card.name}: {msg}")
                                else:
                                    if state_machine.play_card(card, "P1"):
                                        if sfx_undock:
                                            sfx_undock.play()

                # ── 认输按钮 ─────────────────────────────────
                surrender_btn = state.get("surrender_btn_rect")
                if surrender_btn and hasattr(surrender_btn, "collidepoint"):
                    if surrender_btn.collidepoint(event.pos):
                        log_event("[Surrender] P1 主动认输")
                        state["winner"] = "P2"
                        state["phase"] = "GAME_OVER"
                        state_machine.current_phase = TurnPhase.GAME_OVER
                        state.setdefault("draw_anim", {})["active"] = False

                # ── 暂停按钮 ─────────────────────────────────────
                pause_btn = state.get("pause_btn_rect")
                if pause_btn and hasattr(pause_btn, "collidepoint"):
                    if pause_btn.collidepoint(event.pos):
                        if not pause_active:
                            pause_active = True
                            _pause_start_ms = pygame.time.get_ticks()
                            log_event("[Pause] 点击暂停按钮")

                # ── PLAY_P1 阶段：点击牌库结束出牌 ────────────────────────
                if phase == TurnPhase.PLAY_P1:
                    deck_rect = renderer.zones.get("deck")
                    if deck_rect and deck_rect.collidepoint(event.pos):
                        state_machine.finish_p1_turn()
                        log_event("[出牌] P1 点击牌库结束出牌")
                        if sfx_undock:
                            sfx_undock.play()

                # ── ROUND_END 阶段：点击牌库补牌 ────────────────────────────
                if phase == TurnPhase.ROUND_END:
                    deck_rect = renderer.zones.get("deck")
                    if deck_rect and deck_rect.collidepoint(event.pos):
                        deck = state.get("deck")
                        if deck and len(deck.cards) > 0:
                            # 调用 state_machine 的补牌方法
                            drawn = state_machine.request_replenish(1)
                            if drawn > 0:
                                # 触发补牌动画
                                state["draw_anim"] = {
                                    "active": True,
                                    "start_time": pygame.time.get_ticks(),
                                    "progress": 0.0,
                                    "pending_cards": [],
                                    "player_key": "P1"
                                }
                                log_event(f"[补牌] 点击牌库，补回 {drawn} 张卡")
                            else:
                                log_event("[补牌] 牌库为空，无法补牌")
                        else:
                            log_event("[补牌] 牌库为空，无法补牌")

            elif event.type == pygame.MOUSEMOTION:
                # 暂停状态也要更新悬停状态（用于牌库高亮）
                if not pause_active:
                    ui_state["tooltip_card"] = None
                    ui_state["tooltip_anchor_rect"] = None

                # ── 牌库悬停高亮（任何阶段）──────────────────────
                deck_rect = renderer.zones.get("deck")
                if deck_rect and deck_rect.collidepoint(event.pos):
                    state.setdefault("ui", {})["deck_hovered"] = True
                else:
                    state.setdefault("ui", {})["deck_hovered"] = False

        # ── 暂停状态渲染 ─────────────────────────────────────
        if pause_active:
            renderer.draw(state, [])
            renderer.draw_pause_panel(state)
            apply_brightness(screen, float(settings.get("screen_brightness", 1.0)))
            pygame.display.flip()

            # 暂停面板事件处理（独立循环，不与游戏事件混合）
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    pause_active = False
                    # 补偿暂停时长到倒计时
                    paused_ms = pygame.time.get_ticks() - _pause_start_ms
                    _pause_accumulated_ms += paused_ms
                    state["phase_started_at_ms"] += paused_ms
                    state_machine._phase_entered_at_ms += paused_ms
                    log_event(f"[Pause] ESC 恢复游戏（暂停 {paused_ms // 1000}s 已补偿）")
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if renderer.pause_back_btn and renderer.pause_back_btn.collidepoint(event.pos):
                        pause_active = False
                        # 补偿暂停时长到倒计时
                        paused_ms = pygame.time.get_ticks() - _pause_start_ms
                        _pause_accumulated_ms += paused_ms
                        state["phase_started_at_ms"] += paused_ms
                        state_machine._phase_entered_at_ms += paused_ms
                        log_event(f"[Pause] 返回游戏（暂停 {paused_ms // 1000}s 已补偿）")

            clock.tick(FPS)
            continue

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

        # 使用 state_machine.current_phase 而不是旧的 phase 变量
        # 因为 state_machine.update() 可能已经改变了阶段
        current_phase = state_machine.current_phase

        if current_phase == TurnPhase.PLAY_P1 and elapsed >= 90:
            log_event("[Timeout] P1 出牌超时（90秒），直接判负")
            state["winner"] = "P2"
            state["phase"] = "GAME_OVER"
            state_machine.current_phase = TurnPhase.GAME_OVER
            state.setdefault("draw_anim", {})["active"] = False

        if current_phase == TurnPhase.REMEDY:
            try:
                if elapsed >= 30:
                    log_event("[Timeout] REMEDY 阶段超时（30秒），P1 判负")
                    state["winner"] = "P2"
                    state["phase"] = "GAME_OVER"
                    state_machine.current_phase = TurnPhase.GAME_OVER
                    state.setdefault("draw_anim", {})["active"] = False
            except AttributeError as exc:
                log_event(f"[Timeout] REMEDY 阶段切换异常: {exc}", "error")

        # ── 补牌动画更新 ─────────────────────────────────────
        anim = state.get("draw_anim", {})
        if anim.get("active"):
            start_time = int(anim.get("start_time", 0))
            duration_ms = 500
            progress = min(1.0, (now_ms - start_time) / max(1, duration_ms))
            anim["progress"] = progress
            if progress >= 1.0:
                anim["active"] = False
                pending_cards = anim.get("pending_cards", [])
                player_key = anim.get("player_key", "P1")
                state["hands"].setdefault(player_key, []).extend(pending_cards)
                log_event(f"[补牌动画] {player_key} 获得 {len(pending_cards)} 张卡牌")

        # ── 飘字更新 ─────────────────────────────────────────
        # state_machine 把飘字请求（dict）写入 state["floating_texts"]，
        # 这里将它们转交给 renderer 的 FloatingTextManager 渲染。
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
        # 更新 renderer 内部管理的飘字
        renderer.floating_text_manager.update(dt)

        # ── 战报播报 ─────────────────────────────────────────
        toasts = state.get("toasts", [])
        active_toasts = []
        for toast in toasts:
            toast_age = now_ms - int(toast.get("time", 0))
            if toast_age < 2500:
                active_toasts.append(toast)
        state["toasts"] = active_toasts

        # ── 渲染 ─────────────────────────────────────────────
        # 根据阶段使用不同超时时间：正常回合 90s，补救回合 30s
        # 使用 state_machine.current_phase 获取最新的阶段
        current_phase = state_machine.current_phase
        phase_timeout = 90
        if current_phase == TurnPhase.REMEDY:
            phase_timeout = 30
        state["time_left"] = max(0, phase_timeout - elapsed)
        renderer.draw(state, frame_logs)
        apply_brightness(screen, float(settings.get("screen_brightness", 1.0)))

        # ── 鼠标悬停提示 ─────────────────────────────────────
        mouse_pos = pygame.mouse.get_pos()
        hovered_card = None
        p1_cards = state.get("hands", {}).get("P1", [])
        hit = renderer.get_hand_card_hit(mouse_pos, p1_cards)
        if hit is not None:
            hovered_card = p1_cards[hit[0]]
        if hovered_card is not None:
            renderer.draw_card_tooltip(screen, hovered_card, mouse_pos[0], mouse_pos[1])

        pygame.display.flip()

        # ── 游戏结束检测 ─────────────────────────────────────
        if state_machine.current_phase == TurnPhase.GAME_OVER:
            winner = state.get("winner", "")
            if winner == "TIMEOUT":
                pass  # 超时已处理

            # ── 成就判定 + 存档 ───────────────────────────────
            try:
                save_data = load_save_data()
                game_stats = state.get("stats", {})
                merge_game_stats_to_save(game_stats, save_data)

                if winner == "P1":
                    unlocked = check_achievements(state, save_data)
                    if unlocked:
                        for ach_name in unlocked:
                            log_event(f"[成就] 新解锁: {ach_name}")
                    save_data["stats"]["unlocked_achievements"] = unlocked
                    save_save_data(save_data)
            except Exception as exc:
                log_event(f"[存档] 保存异常: {exc}", "error")

            # ── 游戏结束等待界面 ─────────────────────────────
            action = _wait_game_over(screen, renderer, state, clock)
            log_event(f"[Game] 返回主菜单")
            return


# ── 游戏结束等待界面 ─────────────────────────────────────────

def _wait_game_over(
    screen: pygame.Surface,
    renderer: Renderer,
    state: dict[str, Any],
    clock: pygame.time.Clock,
) -> str:
    """游戏结束等待界面：使用 renderer 绘制界面，点击按钮返回菜单。

    Returns:
        "menu" 返回主菜单，"quit" 退出游戏。
    """
    # 使用 renderer 绘制游戏结束界面
    renderer.draw(state, [])
    pygame.display.flip()

    # 等待点击
    while True:
        clock.tick(FPS)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return "quit"
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # 检测是否点击了胜利按钮或失败按钮
                victory_btn = getattr(renderer, "victory_btn_rect", None)
                game_over_btn = getattr(renderer, "game_over_btn_rect", None)
                if victory_btn and victory_btn.collidepoint(event.pos):
                    return "menu"
                if game_over_btn and game_over_btn.collidepoint(event.pos):
                    return "menu"
    return "quit"


# ── 亮度 ─────────────────────────────────────────────────────

def apply_brightness(screen: pygame.Surface, brightness: float) -> None:
    """应用亮度遮罩（brightness: 0.3-1.0）。"""
    brightness = max(0.3, min(1.0, brightness))
    if brightness >= 1.0:
        return
    overlay = pygame.Surface(screen.get_size())
    overlay.fill((0, 0, 0))
    overlay.set_alpha(int((1.0 - brightness) * 255))
    screen.blit(overlay, (0, 0))


# ── 设置界面 ─────────────────────────────────────────────────

def save_and_show_settings(
    screen: pygame.Surface,
    music_manager: Optional[MusicManager],
    settings: dict[str, Any],
) -> Scene:
    """设置界面主循环。返回下一个 Scene。"""
    clock = pygame.time.Clock()
    renderer = Renderer(screen, SCREEN_SIZE)
    settings_active = True
    settings_copy = dict(settings)

    while settings_active:
        clock.tick(FPS)
        mouse_pos = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return Scene.MENU
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                save_settings(settings_copy)
                if music_manager:
                    music_manager.update_settings(settings_copy)
                return Scene.MENU
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                renderer.handle_settings_mouse_up()
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                result = renderer.handle_settings_click(event.pos, settings_copy)
                if result == "back":
                    save_settings(settings_copy)
                    if music_manager:
                        music_manager.update_settings(settings_copy)
                    return Scene.MENU
                # 同步 BGM 静音状态
                if music_manager:
                    music_manager.update_settings(settings_copy)

        # 同步 BGM 音量
        if music_manager and not settings_copy.get("bgm_muted", False):
            try:
                pygame.mixer.music.set_volume(float(settings_copy.get("bgm_volume", 0.5)))
            except Exception:
                pass

        screen.fill((30, 30, 50))
        renderer.draw_settings(settings_copy)
        apply_brightness(screen, float(settings_copy.get("screen_brightness", 1.0)))
        pygame.display.flip()

    return Scene.MENU


# ── 首次运行 ─────────────────────────────────────────────────

def _ensure_first_run() -> None:
    """首次运行时确保用户数据目录有默认配置文件。

    打包模式下：将项目内嵌的默认 save_data.json / settings.json
    复制到用户数据目录（仅当目标文件不存在时）。
    开发模式下：无需操作（文件已就位）。
    """
    user_dir = get_user_data_dir()
    marker = user_dir / ".initialized"

    if marker.exists():
        return

    for filename in ("save_data.json", "settings.json"):
        src = get_resource_path(f"config/{filename}")
        dst = user_dir / filename
        if not dst.exists() and src.exists():
            try:
                shutil.copy2(str(src), str(dst))
            except OSError as exc:
                log_event(f"[FirstRun] 复制 {filename} 失败: {exc}", "error")

    # 写入标记文件
    try:
        marker.write_text("initialized", encoding="utf-8")
    except OSError as exc:
        log_event(f"[FirstRun] 写入标记文件失败: {exc}", "error")


# ── 主入口 ───────────────────────────────────────────────────

def main() -> None:
    """PVZ Plant Card Game 主入口。"""
    _ensure_first_run()

    settings_mgr = SettingsManager()
    settings = settings_mgr.settings

    music_manager = MusicManager()
    music_manager.init_mixer()
    music_manager.scan()

    pygame.init()
    screen = pygame.display.set_mode(SCREEN_SIZE)
    pygame.display.set_caption("PVZ Plant Card Game")

    current_scene = Scene.INTRO
    intro = IntroScreen(screen)
    clock = pygame.time.Clock()

    while True:
        if current_scene == Scene.INTRO:
            # ── 致谢入场动画 ─────────────────────────────────
            intro_done = intro.is_done
            if not intro_done:
                dt = clock.tick(FPS) / 1000.0
                intro.update(dt)
                intro.draw()
                pygame.display.flip()
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        pygame.quit()
                        return
                continue
            current_scene = Scene.LOADING

        elif current_scene == Scene.LOADING:
            # ── 加载界面 ─────────────────────────────────────
            loading_done = False
            loading: Optional[LoadingScreen] = None

            def _on_loading_complete() -> None:
                nonlocal loading_done
                loading_done = True

            run_loading_screen(
                screen, SCREEN_SIZE,
                on_complete=_on_loading_complete,
            )
            current_scene = Scene.MENU

        elif current_scene == Scene.MENU:
            # ── 主菜单 ───────────────────────────────────────
            action, selected_world = run_main_menu(screen, music_manager, settings)

            if action == "quit":
                pygame.quit()
                return
            elif action == "settings":
                current_scene = Scene.SETTINGS
            elif action == "start_ai":
                current_scene = Scene.GAME

        elif current_scene == Scene.SETTINGS:
            # ── 设置界面 ─────────────────────────────────────
            next_scene = save_and_show_settings(screen, music_manager, settings)
            current_scene = next_scene

        elif current_scene == Scene.GAME:
            # ── 游戏主循环 ───────────────────────────────────
            run_game(screen, music_manager, settings)
            current_scene = Scene.MENU

        else:
            # 未知场景，返回主菜单
            current_scene = Scene.MENU

        # 处理退出事件
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                music_manager.quit_mixer()
                pygame.quit()
                return

    music_manager.quit_mixer()
    pygame.quit()


if __name__ == "__main__":
    main()
