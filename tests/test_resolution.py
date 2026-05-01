from core.resolution_engine import ResolutionEngine


def make_card(card_type: str, atk: int, faction: str = "法", effect_id: str = "") -> dict:
    return {"type": card_type, "atk": atk, "faction": faction, "effect_id": effect_id}


def test_main_clash_counteract():
    """全额制：同阵营同 atk → 双方互相造成等量伤害。"""
    engine = ResolutionEngine()
    state = {"players": {"P1": {"hp": 10}, "P2": {"hp": 10}}, "temp": {"shields": {"P1": 2}}}
    p1_cards = [make_card("主", 4, faction="法")]
    p2_cards = [make_card("主", 4, faction="法")]

    logs = engine.resolve_clash(p1_cards, p2_cards, state)

    # 全额制：P1 打 P2 4 伤，P2 打 P1 4 伤
    assert state["players"]["P1"]["hp"] == 6
    assert state["players"]["P2"]["hp"] == 6
    assert state["temp"] == {}
    assert any(log["action"] == "clear_temporary" for log in logs)


def test_main_clash_overflow_damage():
    """克制溢出伤害。
    
    克制关系：法→射→坦→法
    P1(法7) 克制 P2(射3)：溢出伤害 = 7 - 3 = 4
    P2(射3) 被 P1(法) 克制：攻击清0
    """
    engine = ResolutionEngine()
    state = {"players": {"P1": {"hp": 10}, "P2": {"hp": 10}}, "temp": {}}
    p1_cards = [make_card("主", 7, faction="法")]
    p2_cards = [make_card("主", 3, faction="射")]

    logs = engine.resolve_clash(p1_cards, p2_cards, state)

    # P1(法7) 克制 P2(射3)：伤害 = 7 - 3 = 4
    # P2(射3) 被 P1(法) 克制：攻击清0
    assert state["players"]["P1"]["hp"] == 10  # 10 - 0
    assert state["players"]["P2"]["hp"] == 6   # 10 - 4（溢出伤害）


def test_support_effect_apply_independently():
    """辅助卡 heal 先执行，然后全额伤害结算。
    
    P1(法2)+辅(heal+5) vs P2(射3)
    克制关系：法→射→坦→法，法克制射
    P1(法2)克制P2(射3)：但法atk=2 < 射atk=3，双方0伤害
    """
    engine = ResolutionEngine()
    state = {"players": {"P1": {"hp": 6}, "P2": {"hp": 10}}, "temp": {}}
    # 使用无克制阵营测试heal+全额互伤
    p1_cards = [make_card("主", 2, faction="辅"), make_card("辅", 5, effect_id="heal")]
    p2_cards = [make_card("主", 3, faction="法")]

    logs = engine.resolve_clash(p1_cards, p2_cards, state)

    # 辅助卡先 heal +5: P1 hp=6→10（不超过max_hp，实际受max_hp限制）
    # 无克制全额：P2(atk=3) 打 P1 → 3 伤，P1(atk=2) 打 P2 → 2 伤
    # 但 heal 旧系统会按 atk=5 回血，hp=6+5=10
    assert state["players"]["P1"]["hp"] == 7    # 10 - 3
    assert any(log["player"] == "P1" and log["action"] == "heal" for log in logs)


def test_remedy_formula_and_defeat():
    """全额制：伤害超出 HP → 进入补救。
    
    P1(法1) vs P2(射7)，法克制射但法atk=1 < 射atk=7，双方0伤害。
    改用无克制阵营测试：P1(辅1) vs P2(射7)，无克制全额互伤。
    """
    engine = ResolutionEngine()
    state = {"players": {"P1": {"hp": 3}, "P2": {"hp": 10}}, "temp": {}, "phase": "RESOLVE"}
    p1_cards = [make_card("主", 1, faction="辅")]
    p2_cards = [make_card("主", 7, faction="射")]

    clash_logs = engine.resolve_clash(p1_cards, p2_cards, state)
    assert state["phase"] == "REMEDY"
    # 无克制全额：P2(atk=7) 打 P1，P1 HP=3-7<0 → damage_taken=7
    assert state["remedy"]["P1"] == {"before_hp": 3, "damage_taken": 7}
    assert any(log["action"] == "enter_remedy" for log in clash_logs)

    remedy_card = {"owner": "P1", "atk": 2}
    remedy_logs = engine.apply_remedy(remedy_card, state)
    assert state["players"]["P1"]["hp"] == -2  # 3 - 7 + 2 = -2
    assert state["phase"] == "GAME_OVER"
    assert state["winner"] == "P2"
    assert any(log["action"] == "defeat" for log in remedy_logs)
