"""core/state_machine.py - 游戏状态机，内嵌 AI 出牌 + 结算 + 回合流转。

核心设计：所有阶段推进、AI 决策、伤害结算、回合重置均在 update(dt) 中完成。
main.py 只负责事件处理（P1 出牌/空格键）和渲染，不再内联任何阶段逻辑。

精力经济系统：
  - max_mana: 初始 5，硬顶 10
  - current_mana: 当前可用精力，进入 PLAY_P1/P2 首帧自动回满至 max_mana
  - UI：固定 10 点能量石阵列，黄点数 = current_mana
"""
from __future__ import annotations

from enum import Enum, auto
from typing import Any

import pygame

from core.effects import dispatch_effect, tick_buffs
from core.event_bus import EventBus
from core.models import Card
from core.models import Deck
from core.resolution_engine import ResolutionEngine
from core.simple_ai import SimpleAI

# ========== 新技能系统（三级架构）==========
from core.effect_executor import EffectExecutor

# ========== 旧系统（已废弃，保留备份）==========
# from core.old_effects_backup import ...

# ── 精力经济常量 ──────────────────────────────────────────────────

MANA_HARD_CAP = 10          # 精力硬顶
MANA_INITIAL = 5            # 初始精力上限
MANA_DOT_COUNT = 10         # UI 点阵总数（固定）


def _log(msg: str, level: str = "info") -> None:
    """模块级日志函数，受 main.DEBUG_LOG 控制。避免循环导入，动态引用。"""
    try:
        from main import log_event
        log_event(msg, level=level)
    except ImportError:
        # 单元测试环境中 main 不可用，只打 error 级
        if level == "error":
            print(msg)


class TurnPhase(Enum):
    """回合阶段枚举。"""
    DRAW = auto()
    PLAY_P1 = auto()
    PLAY_P2 = auto()
    RESOLVE = auto()
    REMEDY = auto()        # P1 濒死：玩家手动补救
    REMEDY_AI = auto()     # P2 濒死：AI 自动补救
    ROUND_END = auto()
    GAME_OVER = auto()


class GameStateMachine:
    """游戏状态机。

    update(dt) 每帧由主循环调用，内部根据 current_phase 驱动所有逻辑：
      PLAY_P1  → 等待 P1 操作（点击手牌出牌 / 点击 DECK 结束出牌 / 按空格结束出牌）
      PLAY_P2  → 延迟后 AI 自动出牌 → 推进 RESOLVE
      RESOLVE  → ResolutionEngine 结算伤害 → 推进 ROUND_END（或 REMEDY/REMEDY_AI/GAME_OVER）
      REMEDY   → P1 濒死：玩家手动出治疗卡 → 推进 ROUND_END（或 GAME_OVER 超时）
      REMEDY_AI→ P2 濒死：AI 自动补救 → 推进 ROUND_END（或 GAME_OVER 无卡可救）
      ROUND_END→ 归档历史 → 清空战场 → 补牌 → 推进 PLAY_P1（精力回满）
      GAME_OVER→ 停止推进
    """

    AI_DELAY_MS = 3000         # AI 思考延迟（毫秒）→ 3 秒
    REMEDY_DELAY_MS = 30000    # 补救阶段 30 秒超时
    REMEDY_AI_DELAY_MS = 2000  # AI 补救延迟（毫秒）→ 2 秒
    ROUND_END_DELAY_MS = 600   # ROUND_END 停留时间（毫秒）
    USE_PHASE_BASED_RESOLUTION = True  # 是否使用新的基于阶段的结算系统（已启用，包含新的克制机制）

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self.current_phase = TurnPhase.DRAW
        self._runtime_state: dict[str, Any] | None = None
        self._ai: SimpleAI = SimpleAI()
        self._resolver: ResolutionEngine = ResolutionEngine()
        self._round_number: int = 0
        # 用于延迟触发的时间戳
        self._phase_entered_at_ms: int = 0
        # 精力回满标志（每个 PLAY 阶段仅触发一次）
        self._mana_refilled_for_phase: set[str] = set()
        # 先手玩家（"P1" 或 "P2"），控制每回合的出牌顺序
        self.first_player: str = "P1"

        # ── 联机模式支持 ──────────────────────────────────────────
        self.is_online: bool = False           # True=联机模式，False=AI模式
        self._online_actions: list[dict[str, Any]] = []  # 网络接收的 P2 操作队列
        self._waiting_for_online: bool = False           # 是否正在等待远端玩家操作

    def bind_runtime_state(self, state: dict[str, Any]) -> None:
        """绑定运行时状态字典（所有游戏数据存放于此）。"""
        self._runtime_state = state

    # ── 精力经济辅助 ──────────────────────────────────────────────

    def _ensure_player_mana(self, player: str) -> None:
        """确保玩家数据中包含 max_mana / current_mana 字段。"""
        if self._runtime_state is None:
            return
        p = self._runtime_state.setdefault("players", {}).setdefault(player, {})
        if "max_mana" not in p:
            p["max_mana"] = MANA_INITIAL
        if "current_mana" not in p:
            p["current_mana"] = int(p.get("max_mana", MANA_INITIAL))

    def _refill_mana(self, player: str) -> None:
        """精力回满：current_mana = max_mana。"""
        if self._runtime_state is None:
            return
        p = self._runtime_state["players"][player]
        max_m = int(p.get("max_mana", MANA_INITIAL))
        p["current_mana"] = max_m
        _log(f"[回合开始] {player}精力回满至 {max_m}/{max_m}")

    @staticmethod
    def _clamp_mana(player_state: dict[str, Any]) -> None:
        """确保 current_mana 不超过 max_mana 且不小于 0。"""
        max_m = int(player_state.get("max_mana", MANA_INITIAL))
        cur = int(player_state.get("current_mana", 0))
        player_state["current_mana"] = max(0, min(cur, max_m))

    def _gain_max_mana(self, player: str, gain: int) -> None:
        """增加精力上限，硬顶 10。"""
        if self._runtime_state is None or gain <= 0:
            return
        p = self._runtime_state["players"][player]
        p["max_mana"] = min(int(p.get("max_mana", MANA_INITIAL)) + gain, MANA_HARD_CAP)
        self._clamp_mana(p)

    # ── 每帧驱动入口 ─────────────────────────────────────────────

    def update(self, dt: float) -> None:
        """每帧调用，驱动阶段自动推进。dt 为帧间隔（秒）。"""
        _ = dt
        if self._runtime_state is None:
            return

        phase = self.current_phase

        # ── 阶段首帧：精力回满 + 倒计时重置 ─────────────────────
        phase_key = phase.name
        if phase is TurnPhase.PLAY_P1 and "P1" not in self._mana_refilled_for_phase:
            self._ensure_player_mana("P1")
            self._refill_mana("P1")
            self._mana_refilled_for_phase.add("P1")
            # 倒计时重置（Bug Fix #1）
            self._runtime_state["phase_started_at_ms"] = pygame.time.get_ticks()
            # ── Bug Fix：牌库+手牌双空时强制按 HP 判胜负 ──────────
            self._check_deck_and_hands_empty("P1")

        if phase is TurnPhase.PLAY_P2 and "P2" not in self._mana_refilled_for_phase:
            self._ensure_player_mana("P2")
            self._refill_mana("P2")
            self._mana_refilled_for_phase.add("P2")

        # ── 阶段分发 ─────────────────────────────────────────────
        if phase is TurnPhase.PLAY_P2:
            self._on_play_p2()
        elif phase is TurnPhase.RESOLVE:
            self._on_resolve()
        elif phase is TurnPhase.REMEDY:
            self._on_remedy()
        elif phase is TurnPhase.REMEDY_AI:
            self._on_remedy_ai()
        elif phase is TurnPhase.ROUND_END:
            self._on_round_end()

        # ── 状态同步（Bug Fix #3）─────────────────────────────────
        self._sync_state()

    def _sync_state(self) -> None:
        """每帧将 state_machine 内部状态实时覆写至 state 字典，防止同步断裂。"""
        if self._runtime_state is None:
            return
        state = self._runtime_state
        state["phase"] = self.current_phase
        state["phase_started_at_ms"] = self._phase_entered_at_ms

    # ── 阶段处理器 ───────────────────────────────────────────────

    def feed_online_action(self, action: dict[str, Any]) -> None:
        """【联机模式】Host 接收 Client 的操作，加入待处理队列。"""
        self._online_actions.append(action)
        self._waiting_for_online = False

    def _on_play_p2(self) -> None:
        """PLAY_P2 阶段：AI 模式延迟出牌 / 联机模式等待远端操作。"""
        # ── 联机模式：等待网络操作 ──────────────────────────────────
        if self.is_online:
            return self._on_play_p2_online()

        # ── AI 模式（原有逻辑不变）──────────────────────────────────
        now_ms = pygame.time.get_ticks()

        # 首帧记录 ai_turn_start
        if "ai_turn_start" not in self._runtime_state:
            self._runtime_state["ai_turn_start"] = now_ms

        if now_ms - self._runtime_state["ai_turn_start"] < self.AI_DELAY_MS:
            return  # 3 秒延迟未到，仅渲染画面和倒计时

        state = self._runtime_state
        p2_hand = state.setdefault("hands", {}).setdefault("P2", [])
        self._ensure_player_mana("P2")
        p2_mana = int(state["players"]["P2"].get("current_mana", 0))

        # ── 🔇 AI 被沉默：跳过出牌 ──────────────────────────────────
        temp = state.get("temp", {})
        if temp.get("P2_silenced"):
            _log(f"[Round {self._round_number}] AI 被沉默，无法出牌")
            self._advance_after_player("P2")
            return

        # AI 选牌（会从 p2_hand 中移除已选卡）
        chosen = self._ai.choose_cards(p2_hand, p2_mana)
        cost_spent = sum(int(getattr(c, "cost", 0)) for c in chosen)
        state["players"]["P2"]["current_mana"] = max(0, p2_mana - cost_spent)

        played = state.setdefault("played_cards", {})
        played.setdefault("P2", []).extend(chosen)

        if chosen:
            names = "+".join(getattr(c, "name", "?") for c in chosen)
            _log(f"[Round {self._round_number}] AI 出牌: {names}（花费 {cost_spent}）")
            # ── 🔥 AI 出牌：只触发主卡即时效果（辅助卡效果由 _apply_supports 触发）──
            _DELAYED_EFFECT_IDS = frozenset({
                "COUNTER_ATK_ZERO", "COUNTER_DMG_X3", "NO_COUNTER_DMG_X2", "DMG_BUFF_2X_COUNTER",
            })
            _DELAYED_CARD_IDS = frozenset({30})
            for c in chosen:
                card_type = str(getattr(c, "type", "") or "")
                if card_type == "辅":
                    continue  # 辅助卡效果推迟到 RESOLVE 阶段由 _apply_supports 触发
                eid = str(getattr(c, "effect_id", "") or "")
                c_id = int(getattr(c, "id", -1))
                if eid and eid not in _DELAYED_EFFECT_IDS and c_id not in _DELAYED_CARD_IDS:
                    effect_logs: list[dict[str, Any]] = []
                    # 优先新系统，旧系统兜底
                    dispatched = EffectExecutor.execute(state, "P2", c, effect_logs)
                    if not dispatched:
                        dispatched = dispatch_effect(eid, state, "P2", c, effect_logs)
                    if dispatched:
                        _log(f"[Effect] P2 触发主卡效果: {eid} on {getattr(c, 'name', '?')}")
        else:
            _log(f"[Round {self._round_number}] AI 跳过（手牌不可出）")

        # 根据 first_player 决定下一阶段
        self._advance_after_player("P2")

    def _on_play_p2_online(self) -> None:
        """PLAY_P2 阶段（联机模式）：等待 Client 发送操作。"""
        if not self._online_actions:
            self._waiting_for_online = True
            return  # 继续等待，不推进

        action = self._online_actions.pop(0)
        state = self._runtime_state
        action_type = action.get("action", "")

        _log(f"[Online] 收到 P2 操作: {action_type}")

        # ── 🔇 P2 被沉默：跳过出牌 ──────────────────────────────────
        temp = state.get("temp", {})
        if temp.get("P2_silenced"):
            _log(f"[Round {self._round_number}] P2(远端)被沉默，跳过出牌")
            self._advance_after_player("P2")
            return

        if action_type == "finish_turn":
            # P2 结束出牌（可能没出牌直接跳过）
            self._advance_after_player("P2")
            return

        if action_type == "play_card":
            # P2 出牌：根据 card_id 找到手牌中的卡
            card_id = int(action.get("card_id", -1))
            p2_hand = state.setdefault("hands", {}).setdefault("P2", [])
            card = None
            for c in p2_hand:
                if int(getattr(c, "id", -1)) == card_id:
                    card = c
                    break
            if card is None:
                _log(f"[Online] P2 卡牌 ID={card_id} 不在手牌中，跳过")
                return

            # 使用标准出牌逻辑（预出牌）
            if self.play_card(card, "P2"):
                _log(f"[Online] P2 出牌: {getattr(card, 'name', '?')}")

        elif action_type == "commit_and_finish":
            # P2 确认所有出牌并结束
            self._finish_player_turn_online("P2")
            return

        elif action_type == "finish_turn_with_commit":
            # 先 commit pending，再 finish
            pending = state.get("pending_play", {}).get("P2", [])
            if pending:
                self.commit_pending_play("P2")
            self._advance_after_player("P2")
            return

    def _finish_player_turn_online(self, player: str) -> None:
        """联机模式下远端玩家结束出牌。"""
        if self._runtime_state is None:
            return

        # commit pending
        pending = self._runtime_state.get("pending_play", {}).get(player, [])
        if pending:
            self.commit_pending_play(player)

        played = self._runtime_state.get("played_cards", {}).get(player, [])
        if played:
            names = "+".join(getattr(c, "name", "?") for c in played)
            _log(f"[Round {self._round_number}] {player}(远端)出牌: {names}")
        else:
            _log(f"[Round {self._round_number}] {player}(远端)跳过")

        self._advance_after_player(player)

    def _on_resolve(self) -> None:
        """RESOLVE 阶段：调用 ResolutionEngine 结算伤害，立即推进。
        
        支持两种结算模式：
        1. 旧模式（默认）：resolve_clash() - 保持向后兼容
        2. 新模式：resolve_phase_based() - 按阶段顺序执行效果
        
        通过设置 USE_PHASE_BASED_RESOLUTION = True 启用新模式。
        """
        state = self._runtime_state
        p1_cards = state.get("played_cards", {}).get("P1", [])
        p2_cards = state.get("played_cards", {}).get("P2", [])

        if not p1_cards and not p2_cards:
            # 双方都没出牌，跳过结算
            # ── Bug Fix：若牌库+手牌全空，直接判胜负避免无限循环 ──
            deck = state.get("deck")
            p1_hand = state.get("hands", {}).get("P1", [])
            p2_hand = state.get("hands", {}).get("P2", [])
            deck_empty = not isinstance(deck, Deck) or not deck.cards
            if deck_empty and not p1_hand and not p2_hand:
                p1_hp = int(state.get("players", {}).get("P1", {}).get("hp", 0))
                p2_hp = int(state.get("players", {}).get("P2", {}).get("hp", 0))
                winner = "P1" if p1_hp > p2_hp else ("P2" if p2_hp > p1_hp else "DRAW")
                state["winner"] = winner
                state["phase"] = "GAME_OVER"
                self.current_phase = TurnPhase.GAME_OVER
                state.setdefault("draw_anim", {})["active"] = False
                _log(f"[Round {self._round_number}] 双方未出牌且资源耗尽 → 游戏结束 ({winner})")
                return
            self._advance_to(TurnPhase.ROUND_END)
            return

        # 选择结算模式
        if self.USE_PHASE_BASED_RESOLUTION:
            _log(f"[Round {self._round_number}] 使用新的阶段结算模式")
            logs = self._resolver.resolve_phase_based(state, p1_cards, p2_cards)
            
            # 输出阶段结算日志（调试用）
            if _log.__name__ != "_log":  # 检查是否在测试环境
                try:
                    from main import DEBUG_LOG
                    if DEBUG_LOG:
                        summary = self._resolver.log_phase_summary(logs)
                        _log(summary)
                except ImportError:
                    pass
        else:
            _log(f"[Round {self._round_number}] 使用旧的结算模式")
            logs = self._resolver.resolve_clash(p1_cards, p2_cards, state)

        # ── 根据 logs 生成飘字 ─────────────────────────────────
        self._spawn_floating_texts(logs, state)

        # 解析结算结果
        p1_atk_sum = sum(int(getattr(c, "atk", 0)) for c in p1_cards)
        p2_atk_sum = sum(int(getattr(c, "atk", 0)) for c in p2_cards)
        new_phase_str = str(state.get("phase", ""))

        # ── Bug Fix #2：结算后清空出战区 ─────────────────────────
        state["played_cards"]["P1"] = list(state["played_cards"].get("P1", []))
        state["played_cards"]["P2"] = list(state["played_cards"].get("P2", []))
        _log("[结算] 清空出战区")

        if new_phase_str == "REMEDY":
            # 判断谁濒死：检查 remedy 状态中记录的玩家
            remedy_target = None
            remedy_state = state.get("remedy", {})
            if "P1" in remedy_state:
                remedy_target = "P1"
            elif "P2" in remedy_state:
                remedy_target = "P2"

            if remedy_target == "P2":
                # P2 濒死 → AI 自动补救阶段
                _log(f"[Round {self._round_number}] 结算: P1总攻{p1_atk_sum} vs P2总攻{p2_atk_sum} → AI 补救阶段")
                self._advance_to(TurnPhase.REMEDY_AI)
            else:
                # P1 濒死 → 玩家手动补救阶段
                _log(f"[Round {self._round_number}] 结算: P1总攻{p1_atk_sum} vs P2总攻{p2_atk_sum} → 玩家补救阶段")
                self._advance_to(TurnPhase.REMEDY)
        elif new_phase_str == "GAME_OVER":
            winner = state.get("winner", "UNKNOWN")
            _log(f"[Round {self._round_number}] 结算: P1总攻{p1_atk_sum} vs P2总攻{p2_atk_sum} → 游戏结束 ({winner})")
            self.current_phase = TurnPhase.GAME_OVER
        else:
            p1_hp = state.get("players", {}).get("P1", {}).get("hp", "?")
            p2_hp = state.get("players", {}).get("P2", {}).get("hp", "?")
            _log(f"[Round {self._round_number}] 结算: P1总攻{p1_atk_sum} vs P2总攻{p2_atk_sum} → P1 HP:{p1_hp} / P2 HP:{p2_hp}")
            self._advance_to(TurnPhase.ROUND_END)

    def _on_remedy(self) -> None:
        """REMEDY 阶段：等待玩家打出治疗卡，30 秒超时自动判负。

        不再自动补救。玩家必须主动从手牌中打出含 heal/shield 效果的卡牌。
        - 成功回血（HP > 0）→ input_router 触发 _advance_to(ROUND_END)
        - 30 秒超时 → 无条件判 P2 胜（P1 未能自救）
        """
        state = self._runtime_state
        now_ms = pygame.time.get_ticks()

        # 30 秒超时检测 → 无条件判负
        if now_ms - self._phase_entered_at_ms >= self.REMEDY_DELAY_MS:
            _log("[Remedy] 补救超时（30秒），P1 自救失败")
            state["winner"] = "P2"
            state["phase"] = "GAME_OVER"
            self.current_phase = TurnPhase.GAME_OVER
            state.setdefault("draw_anim", {})["active"] = False
            _log("[Remedy] 超时判负 → 游戏结束 (P2)")
            return

        # 不做任何自动推进，等待玩家操作或超时
        # 补救回合的 state_machine 每帧 update(dt) 到这里就停止，
        # 推进由 input_router 的治疗卡出牌逻辑 或 超时逻辑 负责。

    def _on_remedy_ai(self) -> None:
        """REMEDY_AI 阶段：P2 濒死，AI/远端玩家尝试补救。"""
        state = self._runtime_state
        now_ms = pygame.time.get_ticks()

        if self.is_online:
            return self._on_remedy_online()

        # ── AI 模式（原有逻辑）──────────────────────────────────────
        # 延迟等待（给玩家看到"对方尝试自救中"提示的时间）
        if now_ms - self._phase_entered_at_ms < self.REMEDY_AI_DELAY_MS:
            return

        # AI 尝试补救
        success, message = self._ai.try_remedy(state, self)

        if success:
            import pygame as _pg
            state.setdefault("toasts", []).append({
                "text": message,
                "time": _pg.time.get_ticks(),
            })

            # 检查 HP 是否真的回到 > 0
            p2_hp_after = int(state["players"]["P2"].get("hp", 0))
            if p2_hp_after > 0:
                _log(f"[RemedyAI] AI 补救成功：{message}")
            else:
                _log(f"[RemedyAI] AI 补救不足（HP={p2_hp_after}），继续尝试或判定失败")
                self._phase_entered_at_ms = pygame.time.get_ticks()
                p2_hand = state.get("hands", {}).get("P2", [])
                if not p2_hand:
                    _log(f"[RemedyAI] AI 补救不足且手牌为空，P1 胜利")
                    state["winner"] = "P1"
                    state["phase"] = "GAME_OVER"
                    self.current_phase = TurnPhase.GAME_OVER
                    state.setdefault("draw_anim", {})["active"] = False
        else:
            _log(f"[RemedyAI] AI 无卡可救，P1 胜利")
            state["winner"] = "P1"
            state["phase"] = "GAME_OVER"
            self.current_phase = TurnPhase.GAME_OVER
            state.setdefault("draw_anim", {})["active"] = False

    def _on_remedy_online(self) -> None:
        """REMEDY_AI 阶段（联机模式）：P2 濒死，等待远端玩家补救。"""
        state = self._runtime_state

        # 超时检测（30秒）
        now_ms = pygame.time.get_ticks()
        if now_ms - self._phase_entered_at_ms >= self.REMEDY_DELAY_MS:
            _log("[RemedyOnline] P2(远端)补救超时，P1 胜利")
            state["winner"] = "P1"
            state["phase"] = "GAME_OVER"
            self.current_phase = TurnPhase.GAME_OVER
            state.setdefault("draw_anim", {})["active"] = False
            return

        if not self._online_actions:
            return  # 继续等待

        action = self._online_actions.pop(0)
        action_type = action.get("action", "")

        if action_type == "remedy_play_card":
            card_id = int(action.get("card_id", -1))
            p2_hand = state.get("hands", {}).get("P2", [])
            card = None
            for c in p2_hand:
                if int(getattr(c, "id", -1)) == card_id:
                    card = c
                    break
            if card is None:
                _log(f"[RemedyOnline] P2 卡牌 ID={card_id} 不在手牌中")
                return

            success, msg = self.play_card_remedy(card, "P2")
            _log(f"[RemedyOnline] P2(远端)补救: {msg}")

        elif action_type == "remedy_skip":
            # P2 放弃补救
            _log("[RemedyOnline] P2(远端)放弃补救")
            state["winner"] = "P1"
            state["phase"] = "GAME_OVER"
            self.current_phase = TurnPhase.GAME_OVER
            state.setdefault("draw_anim", {})["active"] = False

    def _on_round_end(self) -> None:
        """ROUND_END 阶段：短暂停留后归档、重置、推进到下一回合 PLAY_P1。"""
        now_ms = pygame.time.get_ticks()
        if now_ms - self._phase_entered_at_ms < self.ROUND_END_DELAY_MS:
            return  # 停留

        state = self._runtime_state

        # ① 归档本回合出牌
        self._archive_played_cards()

        # ② 清空出牌区和补救状态（含预出牌区）
        state["played_cards"] = {"P1": [], "P2": []}
        state["pending_play"] = {"P1": [], "P2": []}
        state["remedy"] = {}
        state["temp"] = {}

        # ③ 回合结束 Buff 递减/清理（tick_buffs 自动处理 duration=0 护盾保留，duration>0 递减）
        for p in ("P1", "P2"):
            p_state = state.setdefault("players", {}).setdefault(p, {})
            expired = tick_buffs(p_state)
            if expired:
                _log(f"[Round {self._round_number}] {p} 过期 Buff 清理: {[b.get('type') for b in expired]}")

        # ④ 补牌（精力将在进入 PLAY 阶段时自动回满，此处不再手动设 mana）
        self._refill_hands()

        self._round_number += 1
        _log(f"━━━ Round {self._round_number} 开始 ━━━")

        # 同步回合数记录到 state（供 renderer 判负界面 / 成就判定使用）
        state["round_count"] = self._round_number
        # ── 成就埋点：本局存活回合数 ─────────────────────────────
        state.setdefault("stats", {})["current_game_rounds"] = self._round_number

        # 根据 first_player 决定谁先出牌
        if self.first_player == "P1":
            self._advance_to(TurnPhase.PLAY_P1)
        else:
            self._advance_to(TurnPhase.PLAY_P2)

    # ── 阶段推进 ─────────────────────────────────────────────────

    def _advance_to(self, target: TurnPhase) -> None:
        """切换到目标阶段，更新 state 字典。"""
        self.current_phase = target
        self._phase_entered_at_ms = pygame.time.get_ticks()
        # 重置精力回满标志，允许新阶段触发
        self._mana_refilled_for_phase.discard(target.name.replace("PLAY_", ""))
        if self._runtime_state is not None:
            self._runtime_state["phase"] = target
            self._runtime_state["phase_started_at_ms"] = self._phase_entered_at_ms
            # 清理 ai_turn_start，避免残留
            self._runtime_state.pop("ai_turn_start", None)
            _log(f"[阶段切换] → {target.name} (倒计时重置)")

    # ── P1 出牌接口（由 main.py 事件处理调用）────────────────────

    def commit_pending_play(self, player: str) -> None:
        """将预出牌区（pending_play）的卡牌正式推入 played_cards，并触发主卡即时效果。

        触发时机：由 finish_p1_turn() 在确认出牌时调用。

        效果触发分工：
          - 主卡（type="主"）的即时效果：在此触发（如 STEAL_CARD、SILENCE、DISCARD_FA）
          - 辅助卡（type="辅"）的效果：由 resolution_engine._apply_supports() 在 RESOLVE 阶段触发
            （原因：辅助卡 temp 标记需要在主卡伤害计算前生效，时序由 RESOLVE 保证）

        🔴 绝对不在 play_card() 中触发效果，此方法是效果执行的正确时机。
        """
        if self._runtime_state is None:
            return
        state = self._runtime_state
        pending: list[Any] = state.setdefault("pending_play", {}).get(player, [])
        if not pending:
            return

        played_cards = state.setdefault("played_cards", {})
        played_cards.setdefault(player, []).extend(pending)

        # ── 🔥 只对主卡触发即时效果（辅助卡效果由 _apply_supports 在 RESOLVE 触发）──
        for card in pending:
            card_type = str(getattr(card, "type", "") or "")
            # 跳过辅助卡：其效果将由 resolution_engine._apply_supports() 触发
            if card_type == "辅":
                continue

            eid = str(getattr(card, "effect_id", "") or "")
            # ── 克制类效果跳过：延迟到 RESOLVE 阶段执行（需要对手阵营信息）──
            _DELAYED_EFFECT_IDS = frozenset({
                "COUNTER_ATK_ZERO", "COUNTER_DMG_X3", "NO_COUNTER_DMG_X2", "DMG_BUFF_2X_COUNTER",
            })
            card_id = int(getattr(card, "id", -1))
            # 莲小蓬(ID=30)辅助增伤也延迟（需要知道同回合是否有辅助卡）
            _DELAYED_CARD_IDS = frozenset({30})

            if eid not in _DELAYED_EFFECT_IDS and card_id not in _DELAYED_CARD_IDS:
                # ── 触发即时效果（空 effect_id 时 EffectExecutor 内部兜底处理向日葵系列）──
                effect_logs: list[dict[str, Any]] = []
                dispatched = EffectExecutor.execute(state, player, card, effect_logs)
                if not dispatched and eid:
                    dispatched = dispatch_effect(eid, state, player, card, effect_logs)
                if dispatched:
                    _log(f"[Effect] {player} 确认出牌触发主卡效果: {getattr(card, 'name', '?')}")

            # ── 成就埋点：卡牌使用记录（仅 P1）────────────────────
            if player == "P1":
                stats = state.setdefault("stats", {})
                used_ids: list[int] = stats.setdefault("used_card_ids", [])
                cid = int(getattr(card, "id", -1))
                if cid >= 0 and cid not in used_ids:
                    used_ids.append(cid)

        # 辅助卡的成就埋点同样记录
        if player == "P1":
            for card in pending:
                card_type = str(getattr(card, "type", "") or "")
                if card_type == "辅":
                    stats = state.setdefault("stats", {})
                    used_ids = stats.setdefault("used_card_ids", [])
                    cid = int(getattr(card, "id", -1))
                    if cid >= 0 and cid not in used_ids:
                        used_ids.append(cid)

        # 清空预出牌区
        state["pending_play"][player] = []
        _log(f"[出牌] {player} 确认出牌 {len(pending)} 张（主卡效果已触发，辅助卡效果待 RESOLVE）")

    def play_card_remedy(self, card: Card, player: str) -> tuple[bool, str]:
        """REMEDY 阶段出牌：允许防御/恢复/控制类技能卡，回血后推进 ROUND_END。

        允许的 8 类技能（含分类 + 精确 effect_id 双重匹配）：
          1. 恢复类（HEAL）：回血+2/+3/+4/恢复至8
          2. 护盾类（SHIELD）：护盾+1/+2/+6
          3. 抵挡类（BLOCK）：抵挡一回合攻击
          4. 沉默攻击（SILENCE/ATK_DISABLE）：使对方卡牌攻击失效
          5. 清0攻击（COUNTER/COUNTER_ATK_ZERO）：对克制阵营攻击值清0
          6. 费转血（CONVERT/COST_TO_HEAL/COST_TO_HEAL_SELF）：费用值转为回复血量
          7. 反弹（REFLECT/REFLECT_ATK）：将对方攻击反弹
          8. 攻转血（CONVERT/ATK_TO_HEAL）：对方手牌攻击值转化为回血

        Returns:
            (成功标志, 提示消息) 元组
        """
        if self._runtime_state is None:
            return False, "❌ 游戏状态异常"
        if self.current_phase is not TurnPhase.REMEDY and self.current_phase is not TurnPhase.REMEDY_AI:
            return False, "❌ 当前不在补救阶段"

        state = self._runtime_state

        # ── 🚑 补救回合拦截：仅允许防御/恢复/控制类技能卡 ──────────
        effect_id = str(getattr(card, "effect_id", "")).strip()

        # 允许的一级分类
        allowed_categories: set[str] = {"HEAL", "SHIELD", "BLOCK", "SILENCE", "REFLECT", "CONVERT"}
        # 允许的精确 effect_id（涵盖分类中需要精确控制的技能）
        allowed_skill_ids: set[str] = {
            "COUNTER_ATK_ZERO",    # 克制阵营攻击清0（COUNTER 类中仅允许此技能）
            "COST_TO_HEAL",        # 费转血（CONVERT 类）
            "COST_TO_HEAL_SELF",   # 自身费转血（CONVERT 类）
            "REFLECT_ATK",         # 反弹攻击（REFLECT 类）
            "ATK_TO_HEAL",         # 攻转血（CONVERT 类）
            "ATK_DISABLE",         # 沉默攻击（SILENCE 类）
            "SILENCE",             # 沉默回合（SILENCE 类）
        }

        is_allowed = False
        allow_reason = ""

        if effect_id:
            from core.skill_registry import get_skill_category
            category = get_skill_category(effect_id)

            # 分类匹配
            if category in allowed_categories:
                is_allowed = True
                allow_reason = f"✅ 允许：{category}类效果"

            # 精确 ID 匹配（兜底 + 覆盖 COUNTER 类中的特例）
            if not is_allowed and effect_id in allowed_skill_ids:
                is_allowed = True
                from core.skill_registry import get_skill_data
                skill_data = get_skill_data(effect_id)
                allow_reason = f"✅ 允许：{skill_data.get('desc', effect_id) if skill_data else effect_id}"

            # 旧系统兜底：effect_id 包含 heal/shield 关键词
            if not is_allowed:
                eid_lower = effect_id.lower()
                if "heal" in eid_lower or "shield" in eid_lower:
                    is_allowed = True
                    allow_reason = "✅ 允许：恢复/护盾效果（旧系统匹配）"

        if not is_allowed:
            card_name = getattr(card, "name", "?")
            msg = f"🚫 补救回合不允许 {card_name}（非防御/恢复类技能）"
            _log(f"[Remedy] 拒绝出牌: {card_name} — effect_id={effect_id}")
            return False, msg

        # 检查手牌中是否持有该卡
        hand = state.get("hands", {}).get(player, [])
        if card not in hand:
            return False, "❌ 手牌中无此卡"

        # 从手牌移除
        hand.remove(card)

        # ── 🔥 三级新系统优先触发效果 ──────────────────────────────
        effect_logs: list[dict[str, Any]] = []
        dispatched = EffectExecutor.execute(state, player, card, effect_logs)
        if not dispatched:
            # 旧系统兜底
            dispatched = dispatch_effect(effect_id, state, player, card, effect_logs)
        if not dispatched:
            # 最终兜底：直接读 atk 回血
            heal_value = int(getattr(card, "atk", 0))
            p_state = state.setdefault("players", {}).setdefault(player, {})
            current_hp = int(p_state.get("hp", 0))
            max_hp = int(p_state.get("max_hp", 10))
            p_state["hp"] = min(max_hp, current_hp + heal_value)
            _log(f"[Remedy] {player} 兜底治疗 {heal_value} HP（effect_id={effect_id} 未注册）")

        for elog in effect_logs:
            _log(f"[Remedy] effect_log: {elog}")

        # 检查补救是否成功
        hp_after = int(state["players"][player].get("hp", 0))
        if hp_after > 0:
            _log(f"[Remedy] 补救成功！HP={hp_after}，进入回合结束")
            # ── 成就埋点：补救翻盘标记 ───────────────────────────
            state.setdefault("stats", {})["remedy_flipped"] = True
            self._advance_to(TurnPhase.ROUND_END)
            return True, allow_reason
        else:
            _log(f"[Remedy] 补救不足，HP 仍为 {hp_after}，继续补救...")
            return True, f"⚠️ 补救不足，HP 仍为 {hp_after}"

    def play_card(self, card: Card, player: str) -> bool:
        """预出牌：P1 在 PLAY_P1 阶段点击手牌时调用，仅移入预出牌区（pending_play），不触发效果。

        效果触发时机：
          - P1：finish_p1_turn() → commit_pending_play() → 效果触发
          - P2：_on_play_p2() 中直接触发（AI 无需预出牌区）
          - REMEDY：play_card_remedy() 中即时触发（补救需要立即生效）

        🔴 此方法绝对不调用 EffectExecutor.execute()，严格隔离"预选"与"结算"。
        """
        if self._runtime_state is None:
            return False

        state = self._runtime_state
        phase_name = self.current_phase.name

        if player == "P1" and phase_name != TurnPhase.PLAY_P1.name:
            return False
        if player == "P2" and phase_name != TurnPhase.PLAY_P2.name:
            return False

        # ── 🔇 沉默拦截：被沉默的一方无法出牌 ──────────────────────
        temp = state.get("temp", {})
        if temp.get(f"{player}_silenced"):
            _log(f"[拦截] {player} 处于沉默状态，无法出牌: {getattr(card, 'name', '?')}")
            return False

        # ── 🚫 限制卡拦截：limit_flag=True 的卡每局只能出1次 ────────
        if getattr(card, "limit_flag", False):
            played_history = state.get("played_cards_history", [])
            played_this_round = state.get("played_cards", {}).get(player, [])
            pending_this_round = state.get("pending_play", {}).get(player, [])
            limit_card_id = int(getattr(card, "id", -1))
            # 检查历史回合中是否已出过该限制卡
            already_played = any(
                limit_card_id == int(getattr(c, "id", -2))
                for snapshot in played_history
                for c in snapshot.get(player, [])
                if int(getattr(c, "id", -2)) == limit_card_id
            )
            # 检查本回合已出牌区（played_cards）或预出牌区（pending_play）是否已出过
            already_played = already_played or any(
                int(getattr(c, "id", -2)) == limit_card_id
                for c in (played_this_round + pending_this_round)
            )
            if already_played:
                _log(f"[拦截] 限制卡 {getattr(card, 'name', '?')} 本局已使用，拒绝出牌")
                return False

        self._ensure_player_mana(player)
        player_state = state.get("players", {}).get(player, {})
        current_mana = int(player_state.get("current_mana", 0))
        cost = int(getattr(card, "cost", 0))
        if current_mana < cost:
            return False

        hand = state.get("hands", {}).get(player, [])
        if card not in hand:
            return False

        # ── 🚫 组合规则校验 ──────────────────────────────────────
        # 规则：单出1张 / 1主(射/法/坦)+1辅(辅) / limit_flag只能单出 / 最多2张
        pending_list = state.get("pending_play", {}).get(player, [])
        pending_count = len(pending_list)
        main_factions = {"射", "法", "坦"}
        card_faction = str(getattr(card, "faction", ""))
        card_is_limit = getattr(card, "limit_flag", False)

        # 限制卡只能单出（不能搭配）
        if card_is_limit:
            if pending_count > 0:
                _log(f"[拦截] {player} 限制卡 {getattr(card, 'name', '?')} 只能单出")
                return False

        if pending_count >= 2:
            _log(f"[拦截] {player} 预出牌区已有 {pending_count} 张，每回合最多出2张")
            return False

        if pending_count == 1:
            existing_card = pending_list[0]
            existing_faction = str(getattr(existing_card, "faction", ""))
            existing_is_limit = getattr(existing_card, "limit_flag", False)

            # 已选是限制卡，不能再搭配
            if existing_is_limit:
                _log(f"[拦截] {player} 已选限制卡 {getattr(existing_card, 'name', '?')}，不能搭配")
                return False

            # 校验组合：一主(射/法/坦) + 一辅
            combo = {existing_faction, card_faction}
            if "辅" in combo and (combo & main_factions):
                pass  # 一主一辅，合法
            elif card_faction in main_factions and existing_faction in main_factions:
                _log(f"[拦截] {player} 不能同时出两张主卡（{existing_faction}+{card_faction}）")
                return False
            elif card_faction == "辅" and existing_faction == "辅":
                _log(f"[拦截] {player} 不能同时出两张辅卡")
                return False

        # ── 移入预出牌区（pending_play），扣费，不触发效果 ──────────
        hand.remove(card)
        player_state["current_mana"] = current_mana - cost
        pending = state.setdefault("pending_play", {})
        pending.setdefault(player, []).append(card)

        _log(f"[预出牌] {player} 预选: {getattr(card, 'name', '?')}（cost={cost}，效果待确认后触发）")
        return True

    def undo_play_card(self, card: Card, player: str) -> bool:
        """撤回预出牌：将卡牌从 pending_play 移回手牌并返还 current_mana。

        由于效果尚未触发（pending_play 阶段），撤回无需任何逆效果处理。
        兼容路径：若 pending_play 中不存在，再尝试从 played_cards 撤回（旧行为兼容）。
        """
        if self._runtime_state is None:
            return False

        state = self._runtime_state
        # 仅允许在 PLAY 阶段撤回
        phase = self.current_phase
        if player == "P1" and phase is not TurnPhase.PLAY_P1:
            return False
        if player == "P2" and phase is not TurnPhase.PLAY_P2:
            return False

        # ── 优先从预出牌区（pending_play）撤回 ────────────────────
        pending = state.get("pending_play", {}).get(player, [])
        if card in pending:
            pending.remove(card)
            cost = int(getattr(card, "cost", 0))
            self._ensure_player_mana(player)
            player_state = state["players"][player]
            player_state["current_mana"] = min(
                int(player_state.get("max_mana", MANA_INITIAL)),
                int(player_state.get("current_mana", 0)) + cost,
            )
            state["hands"][player].append(card)
            _log(f"[撤回] {player} 从预出牌区撤回: {getattr(card, 'name', '?')}（效果未触发，无需逆操作）")
            return True

        # ── 兼容路径：从 played_cards 撤回（效果已触发的情况，仅用于旧代码兼容）─
        played = state.get("played_cards", {}).get(player, [])
        if card not in played:
            return False

        played.remove(card)
        cost = int(getattr(card, "cost", 0))
        self._ensure_player_mana(player)
        player_state = state["players"][player]
        player_state["current_mana"] = min(
            int(player_state.get("max_mana", MANA_INITIAL)),
            int(player_state.get("current_mana", 0)) + cost,
        )
        state["hands"][player].append(card)
        _log(f"[撤回] {player} 从已出牌区撤回（注意：效果已触发，此撤回不逆效果）")
        return True

    def _advance_after_player(self, player: str) -> None:
        """根据 first_player 决定当前玩家出牌后的下一阶段。

        用于 AI 出牌后（不走 commit_pending_play 的路径）：
          - 若 player 是先手方 → 推进到后手方的 PLAY 阶段
          - 若 player 是后手方 → 推进到 RESOLVE 阶段
        """
        opponent = "P2" if player == "P1" else "P1"
        if self.first_player == player:
            # 先手方出完，轮到后手方
            _log(f"[阶段] {player} → {opponent}")
            if opponent == "P2":
                self._advance_to(TurnPhase.PLAY_P2)
            else:
                self._advance_to(TurnPhase.PLAY_P1)
        else:
            # 后手方出完，双方都出牌完毕，进入结算
            _log(f"[阶段] {player} → RESOLVE")
            self._advance_to(TurnPhase.RESOLVE)

    def _finish_player_turn(self, player: str) -> None:
        """通用方法：玩家结束出牌，确认出牌并推进阶段。

        根据 first_player 决定推进逻辑：
          - 若 player 是先手方 → 推进到后手方的 PLAY 阶段
          - 若 player 是后手方 → 推进到 RESOLVE 阶段
        """
        if self._runtime_state is None:
            return

        # 确认出牌：将预出牌区提交，效果在此触发
        self.commit_pending_play(player)

        played = self._runtime_state.get("played_cards", {}).get(player, [])
        if played:
            names = "+".join(getattr(c, "name", "?") for c in played)
            _log(f"[Round {self._round_number}] {player} 出牌: {names}")
        else:
            _log(f"[Round {self._round_number}] {player} 跳过（未出牌）")

        self._advance_after_player(player)

    def finish_p1_turn(self) -> None:
        """P1 主动结束出牌（点击 DECK 或按空格）。"""
        if self.current_phase is not TurnPhase.PLAY_P1:
            return
        self._finish_player_turn("P1")

    def finish_p2_turn(self) -> None:
        """P2（AI）主动结束出牌（内部调用）。"""
        if self.current_phase is not TurnPhase.PLAY_P2:
            return
        self._finish_player_turn("P2")

    # ── 补牌接口（保留兼容）──────────────────────────────────────

    def request_replenish(self, count: int) -> int:
        if self._runtime_state is None:
            return 0
        state = self._runtime_state
        safe_count = max(0, int(count))
        deck = state.get("deck")
        if not isinstance(deck, Deck):
            deck = Deck(cards=[])
            state["deck"] = deck
        drawn = deck.draw(safe_count)
        hands = state.setdefault("hands", {})
        p1_hand = hands.setdefault("P1", [])
        p1_hand.extend(drawn)
        state["deck_size"] = len(deck.cards)
        return len(drawn)

    def replenish_hand(self, count: int) -> int:
        if self._runtime_state is None:
            return 0
        state = self._runtime_state
        safe_count = max(0, int(count))
        deck = state.get("deck")
        if not isinstance(deck, Deck):
            deck = Deck(cards=[])
            state["deck"] = deck
        drawn = deck.draw(safe_count)
        hands = state.setdefault("hands", {})
        p1_hand = hands.setdefault("P1", [])
        p1_hand.extend(drawn)
        state["deck_size"] = len(deck.cards)
        return len(drawn)

    def next_phase(self) -> TurnPhase:
        """手动推进一阶段（保留兼容性，一般不应直接调用）。"""
        phase_order = (
            TurnPhase.DRAW,
            TurnPhase.PLAY_P1,
            TurnPhase.PLAY_P2,
            TurnPhase.RESOLVE,
            TurnPhase.REMEDY,
            TurnPhase.REMEDY_AI,
            TurnPhase.ROUND_END,
        )
        if self.current_phase not in phase_order:
            return self.current_phase
        current_idx = phase_order.index(self.current_phase)
        next_idx = (current_idx + 1) % len(phase_order)
        self.current_phase = phase_order[next_idx]
        return self.current_phase

    # ── 内部辅助 ─────────────────────────────────────────────────

    def _spawn_floating_texts(self, logs: list[dict[str, Any]], state: dict[str, Any]) -> None:
        """根据结算 logs 生成飘字，写入 state["floating_texts"] 供 renderer 消费。"""
        ft_requests: list[dict[str, Any]] = state.setdefault("floating_texts", [])

        # P1 飘字锚点（P1 HP 条附近）
        p1_anchor = (200, 620)
        # P2 飘字锚点（P2 HP 条附近）
        p2_anchor = (200, 90)

        anchors: dict[str, tuple[int, int]] = {"P1": p1_anchor, "P2": p2_anchor}

        for log in logs:
            player = log.get("player", "")
            action = log.get("action", "")
            value = int(log.get("value", 0))
            anchor = anchors.get(player)
            if anchor is None or value <= 0:
                continue

            if action == "shield_absorb":
                ft_requests.append({
                    "text": f"-{value}(盾)",
                    "x": anchor[0],
                    "y": anchor[1],
                    "color": (80, 160, 255),  # 蓝色
                })
            elif action == "take_damage":
                ft_requests.append({
                    "text": f"-{value}",
                    "x": anchor[0] + 30,
                    "y": anchor[1],
                    "color": (255, 51, 51),  # 红色
                })
            elif action == "heal" and log.get("reason") == "heal_over_time":
                ft_requests.append({
                    "text": f"+{value}",
                    "x": anchor[0],
                    "y": anchor[1] - 20,
                    "color": (51, 255, 51),  # 绿色
                })
            elif action == "gain_shield":
                ft_requests.append({
                    "text": f"+{value}盾",
                    "x": anchor[0] + 60,
                    "y": anchor[1],
                    "color": (80, 160, 255),  # 蓝色
                })

    def _archive_played_cards(self) -> None:
        """将本回合已出牌存入 played_cards_history（最多保留 2 条）。"""
        if self._runtime_state is None:
            return
        state = self._runtime_state
        history: list[dict[str, list[Any]]] = state.setdefault("played_cards_history", [])
        played = state.get("played_cards", {})
        snapshot = {
            "P1": list(played.get("P1", [])),
            "P2": list(played.get("P2", [])),
        }
        history.append(snapshot)
        if len(history) > 2:
            history.pop(0)

    def _refill_hands(self) -> None:
        """为双方补牌到 5 张（从牌堆无放回抽取），触发动画。"""
        if self._runtime_state is None:
            return
        state = self._runtime_state
        deck = state.get("deck")
        if not isinstance(deck, Deck):
            deck = Deck(cards=[])
            state["deck"] = deck

        # ── BLOCK_NEXT_DRAW：困窘检查 ───────────────────────────────
        # 如果对手被困窘（缠绕水草），则跳过补牌
        control_effects = state.get("control_effects", {})
        if control_effects.get("P2_block_next_draw"):
            _log(f"[Round {self._round_number}] P2 被困窘，跳过补牌")
            # 清除困窘标志
            control_effects.pop("P2_block_next_draw", None)
            return
        if control_effects.get("P1_block_next_draw"):
            _log(f"[Round {self._round_number}] P1 被困窘，跳过补牌")
            # 清除困窘标志
            control_effects.pop("P1_block_next_draw", None)
            return

        # 先抽取所有需要补的牌（暂存）
        p1_draw: list[Any] = []
        p2_draw: list[Any] = []

        for p in ("P1", "P2"):
            hand = state["hands"].setdefault(p, [])
            need = max(0, 5 - len(hand))
            if need > 0:
                if not deck.cards:
                    _log(f"[Round {self._round_number}] {p} 无法补牌 — 牌堆已空")
                    continue
                drawn = deck.draw(need)
                if p == "P1":
                    p1_draw = drawn
                else:
                    p2_draw = drawn
                _log(f"[Round {self._round_number}] {p} 抽取 {len(drawn)} 张待补")

        state["deck_size"] = len(deck.cards)

        # 触发动画（P1 先动画，P2 跟随）
        if p1_draw:
            # 延迟导入避免循环
            from main import trigger_draw_animation
            trigger_draw_animation(state, "P1", p1_draw)
        if p2_draw:
            # P2 补牌直接放入（对手不需要动画效果）
            state["hands"]["P2"].extend(p2_draw)
            _log(f"[Round {self._round_number}] P2 直接补牌 {len(p2_draw)} 张")

        # 牌堆空判定（双方 HP 都 > 0 时按 HP 判胜负）
        if not deck.cards:
            p1_hp = int(state.get("players", {}).get("P1", {}).get("hp", 0))
            p2_hp = int(state.get("players", {}).get("P2", {}).get("hp", 0))
            if p1_hp > 0 and p2_hp > 0:
                winner = "P1" if p1_hp > p2_hp else ("P2" if p2_hp > p1_hp else "DRAW")
                state["winner"] = winner
                state["phase"] = "GAME_OVER"
                self.current_phase = TurnPhase.GAME_OVER
                _log(f"[Round {self._round_number}] 牌堆耗尽 → 游戏结束 ({winner})")

    def _check_deck_and_hands_empty(self, player: str) -> None:
        """检测牌库+手牌双空，强制按 HP 判胜负（防止游戏无限循环）。

        在进入 PLAY_P1 首帧时调用。若双方手牌均空且牌库为空，
        无法继续正常对战，直接按 HP 判胜负结束游戏。
        """
        if self._runtime_state is None:
            return
        state = self._runtime_state

        # 检查牌库是否为空
        deck = state.get("deck")
        if not isinstance(deck, Deck):
            return  # 异常情况，不处理
        if deck.cards:
            return  # 牌库还有牌，正常继续

        # 牌库已空，检查双方手牌
        p1_hand = state.get("hands", {}).get("P1", [])
        p2_hand = state.get("hands", {}).get("P2", [])

        if p1_hand or p2_hand:
            # 至少一方还有手牌，可以继续打
            return

        # 双方手牌+牌库全空，按 HP 判胜负
        p1_hp = int(state.get("players", {}).get("P1", {}).get("hp", 0))
        p2_hp = int(state.get("players", {}).get("P2", {}).get("hp", 0))

        winner = "P1" if p1_hp > p2_hp else ("P2" if p2_hp > p1_hp else "DRAW")
        state["winner"] = winner
        state["phase"] = "GAME_OVER"
        self.current_phase = TurnPhase.GAME_OVER
        state.setdefault("draw_anim", {})["active"] = False
        _log(f"[Round {self._round_number}] 牌库+手牌全空 → 游戏结束 ({winner})")
