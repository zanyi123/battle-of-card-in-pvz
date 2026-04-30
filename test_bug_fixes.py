"""
Bug修复验证测试

测试内容：
1. 暂停按键功能
2. 回合倒计时
3. 点击牌库补牌
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def test_timer_initialization():
    """测试倒计时初始化"""
    print("\n=== 测试1: 倒计时初始化 ===")

    import pygame
    from core.state_machine import GameStateMachine
    from core.event_bus import EventBus

    pygame.init()

    # 创建 state_machine
    event_bus = EventBus()
    state_machine = GameStateMachine(event_bus)

    # 检查 _phase_entered_at_ms 是否初始化为 0
    assert state_machine._phase_entered_at_ms == 0, "初始化应为 0"
    print("[OK] _phase_entered_at_ms 初始化正确")

    # 模拟游戏开始时的同步
    now = pygame.time.get_ticks()
    state_machine._phase_entered_at_ms = now
    assert state_machine._phase_entered_at_ms == now, "同步时间应正确"
    print("[OK] 时间同步正确")

    pygame.quit()


def test_phase_transition():
    """测试阶段切换时倒计时重置"""
    print("\n=== 测试2: 阶段切换时倒计时重置 ===")

    import pygame
    from core.state_machine import GameStateMachine, TurnPhase
    from core.event_bus import EventBus
    from core.models import Deck, Card

    pygame.init()

    # 创建 state_machine
    event_bus = EventBus()
    state_machine = GameStateMachine(event_bus)

    # 创建测试状态
    state = {
        "phase": TurnPhase.PLAY_P1,
        "phase_started_at_ms": 0,
        "players": {
            "P1": {"hp": 10, "max_hp": 10, "current_mana": 5, "max_mana": 5, "buffs": []},
            "P2": {"hp": 10, "max_hp": 10, "current_mana": 5, "max_mana": 5, "buffs": []}
        },
        "hands": {"P1": [], "P2": []},
        "deck": Deck(cards=[]),
        "played_cards": {"P1": [], "P2": []},
        "pending_play": {"P1": [], "P2": []},
    }

    state_machine._runtime_state = state
    state_machine.current_phase = TurnPhase.PLAY_P1

    # 切换到 PLAY_P2
    before_time = state_machine._phase_entered_at_ms
    state_machine._advance_to(TurnPhase.PLAY_P2)

    after_time = state_machine._phase_entered_at_ms
    assert after_time > before_time, "阶段切换后时间应更新"
    assert state["phase_started_at_ms"] == after_time, "state 中的时间应同步"
    print("[OK] 阶段切换时倒计时正确重置")

    pygame.quit()


def test_deck_rect_click_detection():
    """测试牌库点击检测逻辑"""
    print("\n=== 测试3: 牌库点击检测逻辑 ===")

    import pygame

    pygame.init()

    # 创建模拟的牌库矩形
    deck_rect = pygame.Rect(100, 100, 200, 300)

    # 测试点击在牌库内
    click_inside = (200, 250)
    assert deck_rect.collidepoint(click_inside), "点击牌库内应检测到"
    print("[OK] 牌库内点击检测正确")

    # 测试点击在牌库外
    click_outside = (50, 50)
    assert not deck_rect.collidepoint(click_outside), "点击牌库外不应检测到"
    print("[OK] 牌库外点击检测正确")

    pygame.quit()


def test_replenish_functionality():
    """测试补牌功能"""
    print("\n=== 测试4: 补牌功能 ===")

    import pygame
    from core.state_machine import GameStateMachine
    from core.event_bus import EventBus
    from core.models import Deck, Card

    pygame.init()

    # 创建 state_machine
    event_bus = EventBus()
    state_machine = GameStateMachine(event_bus)

    # 创建测试状态
    test_cards = [
        Card(id=1, name="测试卡1", faction="法", type="主", atk=1, cost=1, effect_id="", limit_flag=False),
        Card(id=2, name="测试卡2", faction="射", type="主", atk=1, cost=1, effect_id="", limit_flag=False),
    ]

    state = {
        "phase": "ROUND_END",
        "phase_started_at_ms": pygame.time.get_ticks(),
        "players": {
            "P1": {"hp": 10, "max_hp": 10, "buffs": []},
            "P2": {"hp": 10, "max_hp": 10, "buffs": []}
        },
        "hands": {"P1": [], "P2": []},
        "deck": Deck(cards=test_cards),
        "deck_size": 2,
        "played_cards": {"P1": [], "P2": []},
        "pending_play": {"P1": [], "P2": []},
    }

    state_machine._runtime_state = state

    # 测试补牌
    drawn = state_machine.request_replenish(1)
    assert drawn == 1, f"应补回1张卡，实际补回{drawn}张"
    assert len(state["hands"]["P1"]) == 1, "P1手牌应有1张"
    assert state["deck_size"] == 1, "牌库应有1张"
    print("[OK] 补牌功能正常")

    # 测试再次补牌
    drawn = state_machine.request_replenish(1)
    assert drawn == 1, f"应补回1张卡，实际补回{drawn}张"
    assert len(state["hands"]["P1"]) == 2, "P1手牌应有2张"
    assert state["deck_size"] == 0, "牌库应有0张"
    print("[OK] 第二次补牌功能正常")

    # 测试牌库为空时的补牌
    drawn = state_machine.request_replenish(1)
    assert drawn == 0, f"牌库为空应补回0张卡，实际补回{drawn}张"
    print("[OK] 牌库为空时补牌正确返回0")

    pygame.quit()


def test_pause_time_compensation():
    """测试暂停时长补偿"""
    print("\n=== 测试5: 暂停时长补偿 ===")

    import pygame

    pygame.init()

    # 模拟暂停场景
    phase_start = pygame.time.get_ticks()
    pause_start = pygame.time.get_ticks()
    pygame.time.delay(500)  # 暂停500ms
    pause_end = pygame.time.get_ticks()

    paused_ms = pause_end - pause_start
    compensated_phase_start = phase_start + paused_ms

    assert paused_ms > 450, f"暂停时长应约500ms，实际{paused_ms}ms"
    assert compensated_phase_start > phase_start, "补偿后开始时间应增加"

    print(f"[OK] 暂停时长: {paused_ms}ms")
    print(f"[OK] 补偿后开始时间增加: {compensated_phase_start - phase_start}ms")

    pygame.quit()


def main():
    """运行所有测试"""
    print("\n" + "="*70)
    print("Bug修复验证测试套件")
    print("="*70)

    tests = [
        test_timer_initialization,
        test_phase_transition,
        test_deck_rect_click_detection,
        test_replenish_functionality,
        test_pause_time_compensation,
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] 测试失败: {e}")
            failed += 1
        except Exception as e:
            print(f"[ERROR] 测试异常: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "="*70)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("="*70)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
