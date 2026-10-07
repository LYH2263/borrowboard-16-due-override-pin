"""One active loan per item + overdue detection.

应还日 ``due_date`` 是自然日（YYYY-MM-DD）；可再带一个截止钟点 ``due_time``
（HH:MM，24 小时制）。逾期判定永远走 :func:`is_overdue` 一个出口，看板分栏、
逾期扫名单、状态条计数、归还时的逾期结论共用同一结果。

宽限（``grace_days``）只在判定时给应还日加自然日，不落库：已写下的钟点原样
保留，只过了应还日但还没到钟点的笔不会因此进逾期。
"""

from datetime import date, timedelta

FOLLOW_DAY = "follow_day"  # 时分跟着新日走：原本无钟点则仍是整日语义
KEEP_TIME = "keep_time"    # 钉在原时刻：原本无钟点则钉为当日 23:59
TIME_POLICIES = (FOLLOW_DAY, KEEP_TIME)
_DAY_END = "23:59"


def validate_due_time(value):
    """严格校验 HH:MM；空值归一为 None。

    25 点、缺分钟、非两位等任何非法写法都抛 ValueError——调用方必须让整单失败，
    不能落一半数据。
    """
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("bad_due_time")
    parts = value.split(":")
    # 必须同时有时和分（缺分钟失败）；时、分各自纯数字，取值合法即可
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("bad_due_time")
    hh, mm = parts
    if not (hh.isdigit() and mm.isdigit()):
        raise ValueError("bad_due_time")
    hour, minute = int(hh), int(mm)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("bad_due_time")
    return f"{hour:02d}:{minute:02d}"


def can_lend(item_status: str, active_loans: int) -> dict:
    if item_status != "available":
        return {"ok": False, "reason": "item_not_available"}
    if active_loans > 0:
        return {"ok": False, "reason": "already_on_loan"}
    return {"ok": True, "reason": ""}


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def effective_due_date(due_date: str, grace_days: int = 0):
    """应还日 + 宽限自然日；宽限不影响钟点。无应还日返回 None。"""
    if not due_date:
        return None
    return date.fromisoformat(due_date) + timedelta(days=int(grace_days or 0))


def is_overdue(due_date: str, today: str, loan_status: str,
               due_time: str | None = None, now_time: str | None = None,
               grace_days: int = 0) -> bool:
    """同一笔是否已过点的唯一判定。

    无钟点：应还日（含宽限）早于今天即逾期；
    有钟点：日期相同时还要当前钟点严格超过截止钟点才算逾期——只过日未到点不逾期。
    """
    if loan_status != "active":
        return False
    due = effective_due_date(due_date, grace_days)
    if due is None:
        return False
    today_d = date.fromisoformat(today)
    if due < today_d:
        return True
    if due > today_d:
        return False
    if due_time and now_time:
        return _to_minutes(due_time) < _to_minutes(now_time)
    return False


def classify_loans(loans: list[dict], today: str,
                   now_time: str | None = None, grace_days: int = 0) -> dict:
    """把借还记录分成 在借 / 逾期 / 已还；逾期结论来自 is_overdue。"""
    active, overdue, returned = [], [], []
    for L in loans:
        st = L.get("status")
        if st == "returned":
            returned.append(L)
        elif is_overdue(L.get("due_date"), today, st,
                        L.get("due_time"), now_time, grace_days):
            overdue.append({**L, "overdue": True})
        elif st == "active":
            active.append({**L, "overdue": False})
    return {"active": active, "overdue": overdue, "returned": returned}


def apply_extension(due_date: str, due_time: str | None, days: int,
                    time_policy: str) -> tuple[str, str | None]:
    """顺延 ``days`` 个自然日，返回 (新应还日, 新钟点)。

    只动库里的应还日，不掺宽限。``follow_day`` 时分跟着新日走——原本没有钟点
    仍是整日；``keep_time`` 钉在原时刻——原本没有钟点则钉为当日 23:59。
    """
    if not due_date:
        raise ValueError("no_due_date")
    days = int(days)
    if days < 0:
        raise ValueError("bad_days")
    if time_policy not in TIME_POLICIES:
        raise ValueError("bad_time_policy")
    new_date = (date.fromisoformat(due_date) + timedelta(days=days)).isoformat()
    if time_policy == KEEP_TIME:
        return new_date, validate_due_time(due_time) or _DAY_END
    return new_date, validate_due_time(due_time)
