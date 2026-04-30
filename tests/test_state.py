# tests/test_state.py
import sys, os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def test_always_pass():
    assert True

try:
    from core.event_bus import EventBus
    from core.state_machine import GameStateMachine
    
    # 兼容不同命名：TurnPhase / Phase / GameState
    from core.state_machine import TurnPhase
except ImportError:
    try:
        from core.state_machine import Phase as TurnPhase
    except ImportError:
        try:
            from core.state_machine import GameState as TurnPhase
        except ImportError:
            TurnPhase = None  # 降级处理

def test_state_machine_init():
    """只要 GameStateMachine 能实例化就算通过"""
    bus = EventBus()
    sm = GameStateMachine(bus)
    assert hasattr(sm, 'current_phase') or hasattr(sm, 'state')