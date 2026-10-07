from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import seed
from app.db import connect
from app.engines.borrow_rules import (
    can_lend, classify_loans, is_overdue, parse_due_date, parse_due_time,
    add_grace_days, extend_due, TIME_POLICIES,
)

app = FastAPI(title="Borrowboard", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup(): seed.init_db()


def _now_parts() -> tuple[str, str]:
    """同一时钟源：分栏、顶细条、归还是否逾期都从这里取当前时刻。"""
    now = datetime.now()
    return now.date().isoformat(), now.strftime("%H:%M")


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
    c.close()
    today, now_time = _now_parts()
    cls = classify_loans(loans, today, now_time)
    return {
        "available": available,
        "active": cls["active"],
        "overdue": cls["overdue"],
        "counts": {"available": len(available), "active": len(cls["active"]), "overdue": len(cls["overdue"])},
        "now": {"date": today, "time": now_time},
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
    due_time: str | None = None  # 截止钟点 HH:MM，可空（无钟点老笔）

@app.post("/api/items/{iid}/lend")
def lend(iid: int, body: LendIn):
    # 钟点非法（25 点 / 缺分钟 / 7:30 之类）→ 整单失败：
    # 任何写库之前先校验，逾期扫名单与顶细条停在这次提交之前。
    due_time = parse_due_time(body.due_time)
    if due_time is None:
        raise HTTPException(400, "bad_due_time")
    if parse_due_date(body.due_date) is None:
        raise HTTPException(400, "bad_due_date")
    c = connect()
    item = c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
    if not item: c.close(); raise HTTPException(404, "item")
    active = c.execute("SELECT COUNT(*) c FROM loans WHERE item_id=? AND status='active'", (iid,)).fetchone()["c"]
    check = can_lend(item["status"], active)
    if not check["ok"]:
        c.close(); raise HTTPException(409, check["reason"])
    cur = c.execute(
        "INSERT INTO loans(item_id,borrower,status,due_date,due_time,lent_at) "
        "VALUES (?,?,?,?,?,?)",
        (iid, body.borrower, "active", body.due_date, due_time,
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
    # 归还是否仍当逾期笔：与逾期扫名单/在借栏/顶细条同一函数同一时钟。
    today, now_time = _now_parts()
    overdue = is_overdue(loan["due_date"], today, "active",
                         loan["due_time"] or "", now_time)
    c.execute(
        "UPDATE loans SET status='returned', returned_at=?, was_overdue=? WHERE id=?",
        (datetime.now(timezone.utc).isoformat(), 1 if overdue else 0, lid))
    c.execute("UPDATE items SET status='available' WHERE id=?", (loan["item_id"],))
    c.commit(); c.close()
    return {"ok": True, "was_overdue": overdue}

class GraceIn(BaseModel):
    days: int  # 只加自然日

@app.post("/api/loans/{lid}/grace")
def grace(lid: int, body: GraceIn):
    """改宽限：只加自然日。已写下的钟点原样保留，绝不清掉。"""
    c = connect()
    loan = c.execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
    if not loan: c.close(); raise HTTPException(404, "loan")
    if loan["status"] != "active":
        c.close(); raise HTTPException(400, "not_active")
    try:
        nxt = add_grace_days(loan["due_date"], loan["due_time"] or "", body.days)
    except ValueError as e:
        c.close(); raise HTTPException(400, e.args[0])
    c.execute("UPDATE loans SET due_date=?, due_time=? WHERE id=?",
              (nxt["due_date"], nxt["due_time"], lid))
    c.commit(); c.close()
    return {"ok": True, "due_date": nxt["due_date"], "due_time": nxt["due_time"]}

class ExtendIn(BaseModel):
    days: int
    time_policy: str = "follow"  # follow=时分跟新日走 / keep=钉在原时刻

@app.post("/api/loans/{lid}/extend")
def extend(lid: int, body: ExtendIn):
    """顺延：时分策略由调用方写进接口，分栏与顶细条共用同一解析。"""
    if body.time_policy not in TIME_POLICIES:
        raise HTTPException(400, "bad_time_policy")
    c = connect()
    loan = c.execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
    if not loan: c.close(); raise HTTPException(404, "loan")
    if loan["status"] != "active":
        c.close(); raise HTTPException(400, "not_active")
    try:
        nxt = extend_due(loan["due_date"], loan["due_time"] or "",
                         body.days, body.time_policy)
    except ValueError as e:
        c.close(); raise HTTPException(400, e.args[0])
    c.execute("UPDATE loans SET due_date=?, due_time=? WHERE id=?",
              (nxt["due_date"], nxt["due_time"], lid))
    c.commit(); c.close()
    return {"ok": True, "due_date": nxt["due_date"], "due_time": nxt["due_time"],
            "time_policy": body.time_policy}

@app.get("/api/loans")
def loans():
    c = connect()
    rows = [dict(r) for r in c.execute(
        "SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id ORDER BY loans.id DESC")]
    c.close()
    today, now_time = _now_parts()
    result = classify_loans(rows, today, now_time)
    result["now"] = {"date": today, "time": now_time}
    return result

@app.get("/api/settings")
def settings():
    c = connect(); rows = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}; c.close(); return rows
