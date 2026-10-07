from datetime import date, datetime, timezone
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from app import seed
from app.db import connect
from app.engines.borrow_rules import (
    FOLLOW_DAY, apply_extension, can_lend, classify_loans,
    is_overdue, validate_due_time,
)

app = FastAPI(title="Borrowboard", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _startup(): seed.init_db()


def _now() -> tuple[str, str]:
    n = datetime.now()
    return n.date().isoformat(), n.strftime("%H:%M")


def _grace_days(c) -> int:
    """全板宽限自然日；只在判定时加，从不回写 loans。"""
    row = c.execute("SELECT value FROM settings WHERE key='grace_days'").fetchone()
    try:
        return max(0, int(row["value"])) if row else 0
    except (TypeError, ValueError):
        return 0


@app.get("/api/health")
def health(): return {"ok": True, "project": "borrowboard"}


@app.get("/api/items")
def items():
    c = connect(); rows = [dict(r) for r in c.execute("SELECT * FROM items")]; c.close(); return rows


@app.get("/api/board")
def board():
    c = connect()
    available = [dict(r) for r in c.execute("SELECT * FROM items WHERE status='available'")]
    loans = [dict(r) for r in c.execute(
        """SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id
           WHERE loans.status='active'""")]
    grace = _grace_days(c)
    c.close()
    today, now_time = _now()
    cls = classify_loans(loans, today, now_time, grace)
    return {
        "available": available,
        "active": cls["active"],
        "overdue": cls["overdue"],
        "counts": {"available": len(available), "active": len(cls["active"]), "overdue": len(cls["overdue"])},
    }


class ItemIn(BaseModel):
    title: str
    owner: str


@app.post("/api/items")
def add_item(body: ItemIn):
    c = connect()
    cur = c.execute("INSERT INTO items(title,owner,status,data_quality) VALUES (?,?,?,?)",
                    (body.title, body.owner, "available", "clean"))
    c.commit(); iid = cur.lastrowid; c.close(); return {"id": iid}


class LendIn(BaseModel):
    borrower: str
    due_date: str
    due_time: str | None = None  # 截止钟点 HH:MM；非法则整单 422，一笔都不写

    @field_validator("due_date")
    @classmethod
    def _valid_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("bad_due_date")
        return v

    @field_validator("due_time")
    @classmethod
    def _valid_time(cls, v):
        try:
            return validate_due_time(v)
        except ValueError:
            raise ValueError("bad_due_time")


@app.post("/api/items/{iid}/lend")
def lend(iid: int, body: LendIn):
    c = connect()
    item = c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
    if not item: c.close(); raise HTTPException(404, "item")
    active = c.execute("SELECT COUNT(*) c FROM loans WHERE item_id=? AND status='active'", (iid,)).fetchone()["c"]
    check = can_lend(item["status"], active)
    if not check["ok"]:
        c.close(); raise HTTPException(409, check["reason"])
    cur = c.execute(
        "INSERT INTO loans(item_id,borrower,status,due_date,due_time,lent_at) VALUES (?,?,?,?,?,?)",
        (iid, body.borrower, "active", body.due_date, body.due_time,
         datetime.now(timezone.utc).isoformat()))
    c.execute("UPDATE items SET status='on_loan' WHERE id=?", (iid,))
    c.commit(); lid = cur.lastrowid; c.close(); return {"loan_id": lid}


@app.post("/api/loans/{lid}/return")
def return_loan(lid: int):
    c = connect()
    loan = c.execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
    if not loan: c.close(); raise HTTPException(404, "loan")
    if loan["status"] != "active":
        c.close(); raise HTTPException(400, "not_active")
    today, now_time = _now()
    # 与分栏、逾期扫名单、顶细条同一个判定出口
    overdue = is_overdue(loan["due_date"], today, "active",
                         loan["due_time"], now_time, _grace_days(c))
    c.execute("UPDATE loans SET status='returned', returned_at=? WHERE id=?",
              (datetime.now(timezone.utc).isoformat(), lid))
    c.execute("UPDATE items SET status='available' WHERE id=?", (loan["item_id"],))
    c.commit(); c.close()
    return {"ok": True, "overdue": overdue}


class ExtendIn(BaseModel):
    days: int = Field(ge=0)  # 顺延/宽限都只加自然日
    time_policy: Literal["follow_day", "keep_time"] = FOLLOW_DAY


@app.post("/api/loans/{lid}/extend")
def extend_loan(lid: int, body: ExtendIn):
    """顺延：只加自然日；时分是跟着新日走还是钉在原时刻，由 time_policy 决定。"""
    c = connect()
    loan = c.execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
    if not loan: c.close(); raise HTTPException(404, "loan")
    if loan["status"] != "active":
        c.close(); raise HTTPException(400, "not_active")
    try:
        new_date, new_time = apply_extension(loan["due_date"], loan["due_time"],
                                             body.days, body.time_policy)
    except ValueError as e:
        c.close(); raise HTTPException(422, str(e))
    c.execute("UPDATE loans SET due_date=?, due_time=? WHERE id=?",
              (new_date, new_time, lid))
    c.commit(); c.close()
    return {"id": lid, "due_date": new_date, "due_time": new_time,
            "time_policy": body.time_policy}


@app.get("/api/loans")
def loans():
    c = connect()
    rows = [dict(r) for r in c.execute(
        "SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id ORDER BY loans.id DESC")]
    grace = _grace_days(c)
    c.close()
    today, now_time = _now()
    return classify_loans(rows, today, now_time, grace)


@app.get("/api/loans/{lid}")
def loan_detail(lid: int):
    """顶细条（详情）：日期 + 钟点，以及与分栏完全一致的是否已过点结论。"""
    c = connect()
    loan = c.execute(
        """SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id
           WHERE loans.id=?""", (lid,)).fetchone()
    if not loan: c.close(); raise HTTPException(404, "loan")
    grace = _grace_days(c)
    c.close()
    d = dict(loan)
    today, now_time = _now()
    d["overdue"] = is_overdue(d["due_date"], today, d["status"],
                              d["due_time"], now_time, grace)
    d["grace_days"] = grace
    return d


@app.get("/api/settings")
def settings():
    c = connect(); rows = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}; c.close(); return rows


class GraceIn(BaseModel):
    days: int = Field(ge=0)


@app.put("/api/settings/grace_days")
def set_grace_days(body: GraceIn):
    """改宽限：只加自然日，不回写、不清空任何一笔已写下的钟点。"""
    c = connect()
    c.execute(
        "INSERT INTO settings(key,value) VALUES ('grace_days',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(body.days),))
    c.commit(); c.close()
    return {"grace_days": body.days}
