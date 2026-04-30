"""
测试新的阵营克制机制

阵营克制关系：
- 法师(FA) → 克制 → 射手(SH)
- 射手(SH) → 克制 → 坦克(TK)
- 坦克(TK) → 克制 → 法师(FA)
- 辅助(FU) → 无克制

溢出伤害机制：
- 当攻击方克制防御方，且 攻击方atk > 防御方atk 时
- 溢出伤害 = 攻击方atk - 防御方atk
- 总伤害 = 技能倍率后的基础伤害 + 溢出伤害
- 护盾优先吸收总伤害，剩余部分扣除HP
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from core.resolution_engine import ResolutionEngine
from core.effect_executor import EffectExecutor


def make_card(name, faction, card_type, atk, cost, cid=0, effect_id=None):
    """创建测试用卡牌"""
    return {
        "id": cid,
        "name": name,
        "faction": faction,
        "type": card_type,
        "atk": atk,
        "cost": cost,
        "effect_id": effect_id or "",
        "limit_flag": False,
        "description": "测试卡牌",
        "image_file": "test.png"
    }


def fresh_state():
    """创建初始游戏状态"""
    return {
        "players": {
            "P1": {"hp": 10, "max_hp": 10, "shield": 0, "mana": 5, "max_mana": 5, "hand": [], "deck": [], "buffs": []},
            "P2": {"hp": 10, "max_hp": 10, "shield": 0, "mana": 5, "max_mana": 5, "hand": [], "deck": [], "buffs": []}
        },
        "phase": "RESOLVE",
        "played_cards": {"P1": [], "P2": []},
        "temp": {},
        "turn": 1,
        "logs": []
    }


def test_watermelon_vs_nutwall():
    """测试西瓜投手 vs 坚果墙
    
    西瓜投手(ID:33, 射手, atk4) 攻击 坚果墙(坦克, atk1)
    - 射手克制坦克
    - 西瓜投手技能：攻击坦克时伤害×3
    - 基础伤害 = 4×3 = 12
    - 溢出伤害 = 4-1 = 3
    - 总伤害 = 12+3 = 15
    """
    print("\n" + "="*70)
    print("测试1: 西瓜投手 vs 坚果墙")
    print("="*70)
    
    engine = ResolutionEngine()
    state = fresh_state()
    
    # 西瓜投手：ID:33, 射手, atk4, 技能 COUNTER_DMG_X3
    watermelon = make_card("西瓜投手", "射", "主", 4, 5, cid=33, effect_id="COUNTER_DMG_X3")
    # 坚果墙：ID:3, 坦克, atk1
    nutwall = make_card("坚果墙", "坦", "主", 1, 2, cid=3)
    
    state["played_cards"]["P1"] = [watermelon]
    state["played_cards"]["P2"] = [nutwall]
    
    logs = engine.resolve_clash([watermelon], [nutwall], state)
    
    p2_hp = state["players"]["P2"]["hp"]
    print(f"西瓜投手(射手,atk4) 攻击 坚果墙(坦克,atk1)")
    print(f"预期总伤害: 4×3 + (4-1) = 15")
    print(f"P2实际HP: {p2_hp} (预期: -5, 即10-15=-5)")
    
    assert p2_hp == -5, f"西瓜投手对坦克应为15伤, 实际P2_HP={p2_hp}"
    print("[OK] 测试通过: 西瓜投手正确计算克制x3和溢出伤害")


def test_doomshroom_vs_peashooter():
    """测试毁灭菇 vs 豌豆射手
    
    毁灭菇(ID:34, 法师, atk5) 攻击 豌豆射手(射手, atk1)
    - 法师克制射手
    - 毁灭菇技能：攻击非坦克时伤害×2
    - 基础伤害 = 5×2 = 10
    - 溢出伤害 = 5-1 = 4
    - 总伤害 = 10+4 = 14
    """
    print("\n" + "="*70)
    print("测试2: 毁灭菇 vs 豌豆射手")
    print("="*70)
    
    engine = ResolutionEngine()
    state = fresh_state()
    
    # 毁灭菇：ID:34, 法师, atk5, 技能 NO_COUNTER_DMG_X2
    doomshroom = make_card("毁灭菇", "法", "主", 5, 6, cid=34, effect_id="NO_COUNTER_DMG_X2")
    # 豌豆射手：ID:2, 射手, atk1
    peashooter = make_card("豌豆射手", "射", "主", 1, 1, cid=2)
    
    state["played_cards"]["P1"] = [doomshroom]
    state["played_cards"]["P2"] = [peashooter]
    
    logs = engine.resolve_clash([doomshroom], [peashooter], state)
    
    p2_hp = state["players"]["P2"]["hp"]
    print(f"毁灭菇(法师,atk5) 攻击 豌豆射手(射手,atk1)")
    print(f"预期总伤害: 5×2 + (5-1) = 14")
    print(f"P2实际HP: {p2_hp} (预期: -4, 即10-14=-4)")
    
    assert p2_hp == -4, f"毁灭菇对射手应为14伤, 实际P2_HP={p2_hp}"
    print("[OK] 测试通过: 毁灭菇正确计算x2和溢出伤害")


def test_doomshroom_vs_tank():
    """测试毁灭菇 vs 坦克（被克制）
    
    毁灭菇(ID:34, 法师, atk5) 攻击 坚果墙(坦克, atk1)
    - 坦克克制法师（毁灭菇被克制）
    - 毁灭菇技能：攻击非坦克时伤害×2，攻击坦克时不触发
    - 基础伤害 = 5（无倍率）
    - 无溢出伤害（被克制）
    - 总伤害 = 5
    """
    print("\n" + "="*70)
    print("测试3: 毁灭菇 vs 坦克（被克制）")
    print("="*70)
    
    engine = ResolutionEngine()
    state = fresh_state()
    
    # 毁灭菇：ID:34, 法师, atk5, 技能 NO_COUNTER_DMG_X2
    doomshroom = make_card("毁灭菇", "法", "主", 5, 6, cid=34, effect_id="NO_COUNTER_DMG_X2")
    # 坚果墙：ID:3, 坦克, atk1
    nutwall = make_card("坚果墙", "坦", "主", 1, 2, cid=3)
    
    state["played_cards"]["P1"] = [doomshroom]
    state["played_cards"]["P2"] = [nutwall]
    
    logs = engine.resolve_clash([doomshroom], [nutwall], state)
    
    p2_hp = state["players"]["P2"]["hp"]
    print(f"毁灭菇(法师,atk5) 攻击 坚果墙(坦克,atk1)")
    print(f"预期总伤害: 5（被克制，无倍率无溢出）")
    print(f"P2实际HP: {p2_hp} (预期: 5, 即10-5=5)")
    
    assert p2_hp == 5, f"毁灭菇被坦克克制应为5伤, 实际P2_HP={p2_hp}"
    print("[OK] 测试通过: 毁灭菇被坦克克制时无倍率无溢出")


def test_tank_vs_dart_thistle():
    """测试坦克攻击飞镖洋蓟
    
    坚果墙(坦克, atk1) 攻击 飞镖洋蓟(射手, atk5)
    - 飞镖洋蓟技能：当坦克阵营卡牌攻击它时，攻击方atk清0
    - 坦克攻击被清0
    - 飞镖洋蓟反击
    """
    print("\n" + "="*70)
    print("测试4: 坦克攻击飞镖洋蓟")
    print("="*70)
    
    engine = ResolutionEngine()
    state = fresh_state()
    
    # 坚果墙：ID:3, 坦克, atk1
    nutwall = make_card("坚果墙", "坦", "主", 1, 2, cid=3)
    # 飞镖洋蓟：ID:32, 射手, atk5, 技能 COUNTER_ATK_ZERO
    dart = make_card("飞镖洋蓟", "射", "主", 5, 4, cid=32, effect_id="COUNTER_ATK_ZERO")
    
    state["played_cards"]["P1"] = [nutwall]
    state["played_cards"]["P2"] = [dart]
    
    logs = engine.resolve_clash([nutwall], [dart], state)
    
    p1_hp = state["players"]["P1"]["hp"]
    p2_hp = state["players"]["P2"]["hp"]
    print(f"坚果墙(坦克,atk1) 攻击 飞镖洋蓟(射手,atk5)")
    print(f"预期: 坦克攻击清0, 飞镖洋蓟反击5伤")
    print(f"P1实际HP: {p1_hp} (预期: 5, 即10-5=5)")
    print(f"P2实际HP: {p2_hp} (预期: 10, 未受伤害)")
    
    assert p1_hp == 5, f"坦克攻击应清0, 飞镖反击5伤, 实际P1_HP={p1_hp}"
    assert p2_hp == 10, f"坦克攻击应清0, P2应未受伤害, 实际P2_HP={p2_hp}"
    print("[OK] 测试通过: 飞镖洋蓟正确清零坦克攻击")


def test_overflow_damage_with_shield():
    """测试溢出伤害不穿透护盾
    
    西瓜投手(射手, atk4) 攻击 坚果墙(坦克, atk1)，坚果墙有10护盾
    - 总伤害 = 15
    - 护盾吸收15，剩余0
    - HP不受影响
    """
    print("\n" + "="*70)
    print("测试5: 溢出伤害与护盾")
    print("="*70)
    
    engine = ResolutionEngine()
    state = fresh_state()
    
    # 西瓜投手：ID:33, 射手, atk4, 技能 COUNTER_DMG_X3
    watermelon = make_card("西瓜投手", "射", "主", 4, 5, cid=33, effect_id="COUNTER_DMG_X3")
    # 坚果墙：ID:3, 坦克, atk1
    nutwall = make_card("坚果墙", "坦", "主", 1, 2, cid=3)
    
    # P2有10点护盾
    state["players"]["P2"]["shield"] = 10
    
    state["played_cards"]["P1"] = [watermelon]
    state["played_cards"]["P2"] = [nutwall]
    
    logs = engine.resolve_clash([watermelon], [nutwall], state)
    
    p2_hp = state["players"]["P2"]["hp"]
    p2_shield = state["players"]["P2"]["shield"]
    print(f"西瓜投手(射手,atk4) 攻击 坚果墙(坦克,atk1)")
    print(f"总伤害: 15, P2初始护盾: 10")
    print(f"预期: 护盾吸收15后变为0, HP不变")
    print(f"P2实际HP: {p2_hp} (预期: 10)")
    print(f"P2实际护盾: {p2_shield} (预期: 0)")
    
    assert p2_hp == 10, f"护盾应吸收全部伤害, P2_HP应为10, 实际P2_HP={p2_hp}"
    assert p2_shield == 0, f"护盾应被消耗15后变为0, 实际P2_shield={p2_shield}"
    print("[OK] 测试通过: 护盾正确吸收溢出伤害")


def test_mage_vs_shooter():
    """测试法师克制射手（基础克制）"""
    print("\n" + "="*70)
    print("测试6: 法师克制射手（基础克制）")
    print("="*70)
    
    engine = ResolutionEngine()
    state = fresh_state()
    
    # 火龙草：法师, atk5
    mage = make_card("火龙草", "法", "主", 5, 2, cid=23)
    # 豌豆射手：射手, atk2
    shooter = make_card("豌豆射手", "射", "主", 2, 1, cid=2)
    
    state["played_cards"]["P1"] = [mage]
    state["played_cards"]["P2"] = [shooter]
    
    logs = engine.resolve_clash([mage], [shooter], state)
    
    p1_hp = state["players"]["P1"]["hp"]
    p2_hp = state["players"]["P2"]["hp"]
    print(f"火龙草(法师,atk5) 攻击 豌豆射手(射手,atk2)")
    print(f"预期: 法师克制射手, 溢出=5-2=3, 总伤害=5+3=8")
    print(f"P1实际HP: {p1_hp} (预期: 8, 即10-2=8)")
    print(f"P2实际HP: {p2_hp} (预期: 2, 即10-8=2)")
    
    assert p1_hp == 8, f"P1应受2伤, 实际P1_HP={p1_hp}"
    assert p2_hp == 2, f"P2应受8伤(含溢出3), 实际P2_HP={p2_hp}"
    print("[OK] 测试通过: 法师克制射手，正确计算溢出伤害")


def test_shooter_vs_tank():
    """测试射手克制坦克（基础克制）"""
    print("\n" + "="*70)
    print("测试7: 射手克制坦克（基础克制）")
    print("="*70)
    
    engine = ResolutionEngine()
    state = fresh_state()
    
    # 豌豆射手：射手, atk3
    shooter = make_card("豌豆射手", "射", "主", 3, 1, cid=2)
    # 坚果墙：坦克, atk1
    tank = make_card("坚果墙", "坦", "主", 1, 2, cid=3)
    
    state["played_cards"]["P1"] = [shooter]
    state["played_cards"]["P2"] = [tank]
    
    logs = engine.resolve_clash([shooter], [tank], state)
    
    p1_hp = state["players"]["P1"]["hp"]
    p2_hp = state["players"]["P2"]["hp"]
    print(f"豌豆射手(射手,atk3) 攻击 坚果墙(坦克,atk1)")
    print(f"预期: 射手克制坦克, 溢出=3-1=2, 总伤害=3+2=5")
    print(f"P1实际HP: {p1_hp} (预期: 9, 即10-1=9)")
    print(f"P2实际HP: {p2_hp} (预期: 5, 即10-5=5)")
    
    assert p1_hp == 9, f"P1应受1伤, 实际P1_HP={p1_hp}"
    assert p2_hp == 5, f"P2应受5伤(含溢出2), 实际P2_HP={p2_hp}"
    print("[OK] 测试通过: 射手克制坦克，正确计算溢出伤害")


def test_tank_vs_mage():
    """测试坦克克制法师（基础克制）"""
    print("\n" + "="*70)
    print("测试8: 坦克克制法师（基础克制）")
    print("="*70)
    
    engine = ResolutionEngine()
    state = fresh_state()
    
    # 坚果墙：坦克, atk4
    tank = make_card("坚果墙", "坦", "主", 4, 2, cid=3)
    # 火龙草：法师, atk2
    mage = make_card("火龙草", "法", "主", 2, 2, cid=23)
    
    state["played_cards"]["P1"] = [tank]
    state["played_cards"]["P2"] = [mage]
    
    logs = engine.resolve_clash([tank], [mage], state)
    
    p1_hp = state["players"]["P1"]["hp"]
    p2_hp = state["players"]["P2"]["hp"]
    print(f"坚果墙(坦克,atk4) 攻击 火龙草(法师,atk2)")
    print(f"预期: 坦克克制法师, 溢出=4-2=2, 总伤害=4+2=6")
    print(f"P1实际HP: {p1_hp} (预期: 8, 即10-2=8)")
    print(f"P2实际HP: {p2_hp} (预期: 4, 即10-6=4)")
    
    assert p1_hp == 8, f"P1应受2伤, 实际P1_HP={p1_hp}"
    assert p2_hp == 4, f"P2应受6伤(含溢出2), 实际P2_HP={p2_hp}"
    print("[OK] 测试通过: 坦克克制法师，正确计算溢出伤害")


def test_support_faction_no_counter():
    """测试辅助阵营无克制"""
    print("\n" + "="*70)
    print("测试9: 辅助阵营无克制")
    print("="*70)
    
    engine = ResolutionEngine()
    state = fresh_state()
    
    # 向日葵：辅助, atk1
    support = make_card("向日葵", "辅", "主", 1, 1, cid=1)
    # 豌豆射手：射手, atk3
    shooter = make_card("豌豆射手", "射", "主", 3, 1, cid=2)
    
    state["played_cards"]["P1"] = [support]
    state["played_cards"]["P2"] = [shooter]
    
    logs = engine.resolve_clash([support], [shooter], state)
    
    p1_hp = state["players"]["P1"]["hp"]
    p2_hp = state["players"]["P2"]["hp"]
    print(f"向日葵(辅助,atk1) 攻击 豌豆射手(射手,atk3)")
    print(f"预期: 辅助无克制，无溢出，各自造成基础伤害")
    print(f"P1实际HP: {p1_hp} (预期: 7, 即10-3=7)")
    print(f"P2实际HP: {p2_hp} (预期: 9, 即10-1=9)")
    
    assert p1_hp == 7, f"P1应受3伤, 实际P1_HP={p1_hp}"
    assert p2_hp == 9, f"P2应受1伤, 实际P2_HP={p2_hp}"
    print("[OK] 测试通过: 辅助阵营无克制，无溢出伤害")


def main():
    """运行所有测试"""
    print("\n" + "="*70)
    print("阵营克制机制测试套件")
    print("="*70)
    print("\n克制关系：")
    print("  法师(FA) → 射手(SH) → 坦克(TK) → 法师(FA)")
    print("  辅助(FU) → 无克制")
    print("\n溢出伤害机制：")
    print("  当攻击方克制防御方，且 atk攻击 > atk防御 时")
    print("  溢出伤害 = atk攻击 - atk防御")
    print("  总伤害 = 技能倍率后的基础伤害 + 溢出伤害")
    
    tests = [
        test_watermelon_vs_nutwall,
        test_doomshroom_vs_peashooter,
        test_doomshroom_vs_tank,
        test_tank_vs_dart_thistle,
        test_overflow_damage_with_shield,
        test_mage_vs_shooter,
        test_shooter_vs_tank,
        test_tank_vs_mage,
        test_support_faction_no_counter,
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
            failed += 1
    
    print("\n" + "="*70)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("="*70)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
