"""One active loan per item + overdue detection.

逾期判定只有一个入口 :func:`is_overdue` —— 看板分栏、顶细条、归还时是否
仍当逾期笔，全部以同一当前时刻 ``today`` + ``now_time`` 对照
``due_date`` + ``due_time``：

* 没写钟点的老笔：应还日当天 00:00 起算逾期（保留旧行为：只比日期）。
* 写了钟点的笔：到应还日的那个钟点之前都不算逾期（只过日、未到点不算）。

宽限只加自然日、不动钟点；顺延的时分策略由调用方写进顺延接口
（``follow`` 时分跟着新日走 / ``keep`` 钉在原时刻整体平移），
分栏与顶细条共用同一套解析。
"""

import re
from datetime import date, datetime, timedelta

_DUE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DUE_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

TIME_POLICY_FOLLOW = "follow"   # 时分跟着新日走
TIME_POLICY_KEEP = "keep"       # 钉在原时刻，整体平移
TIME_POLICIES = (TIME_POLICY_FOLLOW, TIME_POLICY_KEEP)


def can_lend(item_status: str, active_loans: int) -> dict:
    if item_status != "available":
        return {"ok": False, "reason": "item_not_available"}
    if active_loans > 0:
        return {"ok": False, "reason": "already_on_loan"}
    return {"ok": True, "reason": ""}


def parse_due_date(value):
    """严格校验 YYYY-MM-DD（拒绝 2026-2-1、2026-13-40 之类）。"""
    if not isinstance(value, str) or not _DUE_DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_due_time(value):
    """严格校验 HH:MM 24 小时制。

    空串/None → 空串（无钟点老笔）；25 点、缺分钟、7:30 一律返回 None，
    由上层让整单失败。
    """
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or not _DUE_TIME_RE.match(value):
        return None
    return value


def _deadline(due_date: str, due_time: str):
    d = parse_due_date(due_date or "")
    if d is None:
        return None
    if due_time:
        try:
            return datetime.combine(d, datetime.strptime(due_time, "%H:%M").time())
        except ValueError:
            return None
    return datetime.combine(d, datetime.min.time())


def _now(today: str, now_time: str):
    t_d = parse_due_date(today)
    if t_d is None:
        return None
    if now_time:
        try:
            return datetime.combine(t_d, datetime.strptime(now_time, "%H:%M").time())
        except ValueError:
            pass
    return datetime.combine(t_d, datetime.min.time())


def is_overdue(due_date: str, today: str, loan_status: str,
               due_time: str = "", now_time: str = "") -> bool:
    """同一笔在各入口（逾期扫名单 / 在借栏样式 / 顶细条 / 归还）的唯一结论。"""
    if loan_status != "active" or not due_date:
        return False
    deadline = _deadline(due_date, due_time)
    now = _now(today, now_time)
    if deadline is None or now is None:
        return False  # 数据异常不进逾期扫名单
    return now > deadline


def classify_loans(loans: list[dict], today: str, now_time: str = "") -> dict:
    """分栏与顶细条共用：每个 active 笔输出统一的 ``overdue`` 标记。"""
    active, overdue, returned = [], [], []
    for L in loans:
        st = L.get("status")
        if st == "returned":
            # 结论在归还那一刻已钉死，不再随后续时钟翻动
            returned.append({**L, "overdue": bool(L.get("was_overdue"))})
        elif is_overdue(L.get("due_date"), today, st,
                        L.get("due_time") or "", now_time):
            overdue.append({**L, "overdue": True})
        elif st == "active":
            active.append({**L, "overdue": False})
    return {"active": active, "overdue": overdue, "returned": returned}


def _validate(due_date: str, due_time: str, days: int):
    d = parse_due_date(due_date or "")
    if d is None:
        raise ValueError("bad_due_date")
    if not isinstance(days, int) or days <= 0:
        raise ValueError("bad_days")
    t = parse_due_time(due_time or "")
    if t is None:
        raise ValueError("bad_due_time")
    return d, t


def add_grace_days(due_date: str, due_time: str, days: int) -> dict:
    """改宽限：只加自然日，不清掉已经写下的钟点。

    钟点原样跟着日期平移——只过日未到点的笔不会因钟点被清而突然进逾期扫。
    """
    d, t = _validate(due_date, due_time, days)
    return {"due_date": (d + timedelta(days=days)).isoformat(), "due_time": t}


def extend_due(due_date: str, due_time: str, days: int, time_policy: str) -> dict:
    """顺延 N 天，时分策略写进接口，分栏与顶细条共用：

    * ``follow`` 时分跟着新日走：新日挂原 HH:MM（无钟点仍无钟点）；
    * ``keep``   钉在原时刻：以原截止时刻为锚整体平移 N 个自然日。

    自然日模型下两者落库同为「日期 +N、钟点不变」；区别在于锚点语义，
    后续若引入非整日/时区调整从这里演进。
    """
    d, t = _validate(due_date, due_time, days)
    if time_policy not in TIME_POLICIES:
        raise ValueError("bad_time_policy")
    if time_policy == TIME_POLICY_KEEP:
        moved = _deadline(due_date, t) + timedelta(days=days)
        return {"due_date": moved.date().isoformat(),
                "due_time": moved.strftime("%H:%M") if t else ""}
    return {"due_date": (d + timedelta(days=days)).isoformat(), "due_time": t}
