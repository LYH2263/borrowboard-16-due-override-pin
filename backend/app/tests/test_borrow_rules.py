from app.engines.borrow_rules import (
    can_lend, is_overdue, classify_loans,
    parse_due_time, parse_due_date, add_grace_days, extend_due,
)

def _l(**kw):
    base = {"id": 1, "status": "active", "due_date": "2026-10-06", "due_time": "18:00"}
    base.update(kw)
    return base

# ---------- 既有行为保持兼容 ----------

def test_mutex():
    assert can_lend("available", 0)["ok"]
    assert can_lend("available", 1)["reason"] == "already_on_loan"
    assert can_lend("retired", 0)["ok"] is False

def test_overdue_legacy_no_time():
    # 无钟点老笔：应还日当天 00:00 起算逾期，旧行为不变
    assert is_overdue("2020-01-01", "2026-01-01", "active")
    assert not is_overdue("2020-01-01", "2026-01-01", "returned")

def test_classify():
    r = classify_loans([
        {"id": 1, "status": "active", "due_date": "2020-01-01"},
        {"id": 2, "status": "active", "due_date": "2099-01-01"},
        {"id": 3, "status": "returned", "due_date": "2020-01-01"},
    ], "2026-01-01")
    assert len(r["overdue"]) == 1 and len(r["active"]) == 1 and len(r["returned"]) == 1

# ---------- 钟点严格校验：25 点 / 缺分钟整单失败 ----------

def test_parse_due_time_rejects_bad():
    assert parse_due_time("25:00") is None
    assert parse_due_time("24:00") is None
    assert parse_due_time("18:60") is None
    assert parse_due_time("1860") is None     # 缺冒号/分钟
    assert parse_due_time("18") is None       # 缺分钟
    assert parse_due_time("7:30") is None     # 不补零
    assert parse_due_time("abc") is None
    assert parse_due_time(None) == "" and parse_due_time("") == ""
    assert parse_due_time("00:00") == "00:00"
    assert parse_due_time("23:59") == "23:59"

def test_parse_due_date_strict():
    assert parse_due_date("2026-2-1") is None
    assert parse_due_date("2026-13-40") is None
    assert parse_due_date("2026-10-06").isoformat() == "2026-10-06"

# ---------- 核心不变量：四个入口同一结论 ----------

def test_date_passed_but_time_not_yet_not_overdue():
    """已经过了应还日但还没到钟点 → 不算逾期。"""
    # 应还 10-06 18:00；当天 09:00 / 17:59 都未过点
    assert is_overdue("2026-10-06", "2026-10-06", "active", "18:00", "09:00") is False
    assert is_overdue("2026-10-06", "2026-10-06", "active", "18:00", "17:59") is False
    # 18:00 整不算（now > deadline 才算），18:01 算
    assert is_overdue("2026-10-06", "2026-10-06", "active", "18:00", "18:00") is False
    assert is_overdue("2026-10-06", "2026-10-06", "active", "18:00", "18:01") is True
    # 次日任何时刻都逾期
    assert is_overdue("2026-10-06", "2026-10-07", "active", "18:00", "00:00") is True

def test_all_entrypoints_agree():
    """逾期扫名单(classify) / 在借栏样式 / 顶细条 / 归还 对同一笔同一结论。"""
    L = _l(due_date="2026-10-06", due_time="18:00")
    for hhmm in ("09:00", "17:59", "18:00"):
        cls = classify_loans([L], "2026-10-06", hhmm)
        assert len(cls["active"]) == 1 and cls["active"][0]["overdue"] is False
        assert is_overdue(L["due_date"], "2026-10-06", "active", L["due_time"], hhmm) is False
    for hhmm in ("18:01", "23:59"):
        cls = classify_loans([L], "2026-10-06", hhmm)
        assert len(cls["overdue"]) == 1 and cls["overdue"][0]["overdue"] is True
        assert is_overdue(L["due_date"], "2026-10-06", "active", L["due_time"], hhmm) is True
    # 已还笔：结论钉死，不随后续时钟翻动
    R = {**L, "status": "returned", "was_overdue": 1}
    cls = classify_loans([R], "2099-01-01", "00:00")
    assert cls["returned"][0]["overdue"] is True

# ---------- 宽限：只加自然日，不清钟点，不突变逾期 ----------

def test_grace_keeps_time():
    nxt = add_grace_days("2026-10-06", "18:00", 3)
    assert nxt == {"due_date": "2026-10-09", "due_time": "18:00"}
    # 无钟点老笔宽限后仍无钟点
    nxt2 = add_grace_days("2026-10-06", "", 2)
    assert nxt2 == {"due_date": "2026-10-08", "due_time": ""}

def test_grace_day_passed_time_not_rejected():
    """只过日未到点的笔宽限：钟点保留，新截止前仍不逾期。"""
    # 今天 10-06 10:00，应还 10-06 18:00（未逾期），宽 1 天
    nxt = add_grace_days("2026-10-06", "18:00", 1)
    assert is_overdue(nxt["due_date"], "2026-10-06", "active", nxt["due_time"], "10:00") is False
    assert is_overdue(nxt["due_date"], "2026-10-07", "active", nxt["due_time"], "17:59") is False
    assert is_overdue(nxt["due_date"], "2026-10-07", "active", nxt["due_time"], "18:01") is True

def test_grace_rejects_bad_days():
    import pytest
    for d in (0, -1):
        with pytest.raises(ValueError):
            add_grace_days("2026-10-06", "18:00", d)

# ---------- 顺延：follow / keep 策略写进接口 ----------

def test_extend_follow():
    nxt = extend_due("2026-10-06", "18:00", 5, "follow")
    assert nxt == {"due_date": "2026-10-11", "due_time": "18:00"}
    nxt2 = extend_due("2026-10-06", "", 5, "follow")
    assert nxt2 == {"due_date": "2026-10-11", "due_time": ""}

def test_extend_keep_pins_original_time():
    nxt = extend_due("2026-10-06", "18:00", 5, "keep")
    assert nxt == {"due_date": "2026-10-11", "due_time": "18:00"}

def test_extend_bad_policy():
    import pytest
    with pytest.raises(ValueError):
        extend_due("2026-10-06", "18:00", 1, "pin")
