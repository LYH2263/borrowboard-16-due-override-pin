import pytest
from app.engines.borrow_rules import (
    FOLLOW_DAY, KEEP_TIME, apply_extension, can_lend, classify_loans,
    is_overdue, validate_due_time,
)


def test_mutex():
    assert can_lend("available", 0)["ok"]
    assert can_lend("available", 1)["reason"] == "already_on_loan"
    assert can_lend("retired", 0)["ok"] is False


def test_overdue():
    assert is_overdue("2020-01-01", "2026-01-01", "active")
    assert not is_overdue("2020-01-01", "2026-01-01", "returned")


def test_classify():
    r = classify_loans([
        {"id": 1, "status": "active", "due_date": "2020-01-01"},
        {"id": 2, "status": "active", "due_date": "2099-01-01"},
        {"id": 3, "status": "returned", "due_date": "2020-01-01"},
    ], "2026-01-01")
    assert len(r["overdue"]) == 1 and len(r["active"]) == 1 and len(r["returned"]) == 1


# ---------- 截止钟点 ----------

@pytest.mark.parametrize("raw", ["25:00", "24:00", "09:60", "0900", "ab:cd", "9点", "09:", "09"])
def test_bad_due_time_whole_order_fails(raw):
    # 25 点、缺分钟、非 HH:MM 一律视为非法，调用方必须让整单失败
    with pytest.raises(ValueError):
        validate_due_time(raw)


@pytest.mark.parametrize("raw,norm", [
    ("00:00", "00:00"), ("23:59", "23:59"), ("9:30", "09:30"), ("9:3", "09:03"),
])
def test_good_due_time(raw, norm):
    assert validate_due_time(raw) == norm


@pytest.mark.parametrize("raw", [None, ""])
def test_empty_due_time_means_whole_day(raw):
    assert validate_due_time(raw) is None


def test_due_date_passed_but_time_not_reached_is_not_overdue():
    # 已经过了应还日？其实就是应还日当天：只过日未到点不算逾期
    assert not is_overdue("2026-10-06", "2026-10-06", "active", "18:00", "09:00")
    # 到了同一钟点仍不算（严格过点才算）
    assert not is_overdue("2026-10-06", "2026-10-06", "active", "18:00", "18:00")
    # 过了钟点才算
    assert is_overdue("2026-10-06", "2026-10-06", "active", "18:00", "18:01")


def test_past_or_future_date_time_cannot_save_it():
    assert is_overdue("2026-10-05", "2026-10-06", "active", "23:59", "00:00")
    assert not is_overdue("2026-10-07", "2026-10-06", "active", "00:00", "23:59")


def test_same_loan_same_verdict_everywhere():
    # 逾期扫名单、在借栏样式、顶细条必须对同一笔得出同一结论
    loans = [{"id": 7, "status": "active", "due_date": "2026-10-06",
              "due_time": "18:00", "title": "梯"}]
    before = classify_loans(loans, "2026-10-06", "09:00")
    after = classify_loans(loans, "2026-10-06", "19:00")
    assert len(before["active"]) == 1 and before["active"][0]["overdue"] is False
    assert len(after["overdue"]) == 1 and after["overdue"][0]["overdue"] is True
    assert is_overdue("2026-10-06", "2026-10-06", "active", "18:00", "09:00") is False
    assert is_overdue("2026-10-06", "2026-10-06", "active", "18:00", "19:00") is True


# ---------- 宽限：只加自然日，不动钟点 ----------

def test_grace_adds_calendar_days_without_touching_time():
    # 应还日当天 18:00 截止，宽限 1 天：次日 09:00 仍未到点，19:00 已过点
    assert not is_overdue("2026-10-06", "2026-10-07", "active", "18:00", "09:00", grace_days=1)
    assert is_overdue("2026-10-06", "2026-10-07", "active", "18:00", "19:00", grace_days=1)
    # 无钟点的笔：宽限把判定推到新自然日，不会突然进逾期
    assert not is_overdue("2026-10-06", "2026-10-07", "active", None, "09:00", grace_days=1)
    assert is_overdue("2026-10-06", "2026-10-08", "active", None, "09:00", grace_days=1)


def test_grace_keeps_day_only_loan_out_of_sweep():
    loans = [{"id": 8, "status": "active", "due_date": "2026-10-06", "due_time": None}]
    r = classify_loans(loans, "2026-10-07", "09:00", grace_days=1)
    assert len(r["overdue"]) == 0 and len(r["active"]) == 1


# ---------- 顺延：时分策略 ----------

def test_extend_follow_day_carries_time_or_stays_whole_day():
    assert apply_extension("2026-10-06", "18:00", 2, FOLLOW_DAY) == ("2026-10-08", "18:00")
    # 原本无钟点：跟着新日走，仍是整日语义
    assert apply_extension("2026-10-06", None, 2, FOLLOW_DAY) == ("2026-10-08", None)


def test_extend_keep_time_pins_whole_day_loan_at_2359():
    assert apply_extension("2026-10-06", "18:00", 2, KEEP_TIME) == ("2026-10-08", "18:00")
    # 原本无钟点：钉在原（日末）时刻
    assert apply_extension("2026-10-06", None, 2, KEEP_TIME) == ("2026-10-08", "23:59")


def test_extend_rejects_bad_policy():
    with pytest.raises(ValueError):
        apply_extension("2026-10-06", "18:00", 1, "freeze")


def test_extended_loan_classifies_with_its_new_datetime():
    # 顺延后分栏与顶细条共用同一结论
    new_date, new_time = apply_extension("2026-10-06", "18:00", 1, FOLLOW_DAY)
    loans = [{"id": 9, "status": "active", "due_date": new_date, "due_time": new_time}]
    r = classify_loans(loans, "2026-10-07", "19:00")
    assert len(r["overdue"]) == 1
