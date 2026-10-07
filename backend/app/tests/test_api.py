import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """每个用例一个全新 DATA_DIR，startup 重新建库 + 种子。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import app.main as main
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c, main, str(tmp_path)


def _add_item(c, title="梯子"):
    r = c.post("/api/items", json={"title": title, "owner": "老周"})
    assert r.status_code == 200
    return r.json()["id"]


def test_lend_with_due_time_ok(client):
    c, _, _ = client
    iid = _add_item(c)
    r = c.post(f"/api/items/{iid}/lend",
               json={"borrower": "邻居甲", "due_date": "2099-01-01", "due_time": "18:30"})
    assert r.status_code == 200
    b = c.get("/api/board").json()
    assert b["now"]["time"]  # 顶细条共用的当前时刻随接口下发
    loan = next(l for l in b["active"] if l["item_id"] == iid)
    assert loan["due_time"] == "18:30" and loan["overdue"] is False


def test_lend_bad_time_whole_order_fails_no_row(client):
    """25 点 / 缺分钟：整单失败，逾期扫名单与顶细条停在提交之前（不落库）。"""
    c, main, data_dir = client
    iid = _add_item(c)
    for bad in ("25:00", "24:00", "18:60", "18", "7:30"):
        r = c.post(f"/api/items/{iid}/lend",
                   json={"borrower": "邻居甲", "due_date": "2099-01-01", "due_time": bad})
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == "bad_due_time"
    # 没有任何 loan 落库；物品仍是 available
    import sqlite3
    conn = sqlite3.connect(os.path.join(data_dir, "borrowboard.db"))
    n = conn.execute("SELECT COUNT(*) FROM loans WHERE item_id=?", (iid,)).fetchone()[0]
    status = conn.execute("SELECT status FROM items WHERE id=?", (iid,)).fetchone()[0]
    conn.close()
    assert n == 0 and status == "available"


def test_lend_bad_date_whole_order_fails(client):
    c, _, _ = client
    iid = _add_item(c)
    r = c.post(f"/api/items/{iid}/lend",
               json={"borrower": "邻居甲", "due_date": "2099-02-31", "due_time": "18:00"})
    assert r.status_code == 400


def test_board_and_loans_agree(client):
    """提交后分栏(/board)与顶细条/借还记录(/loans)对同一笔同一结论。"""
    c, main, _ = client
    from datetime import date
    today = date.today().isoformat()
    iid_late = _add_item(c, "晚钟点")   # 今天 23:59 → 此刻必然未过点
    iid_early = _add_item(c, "早钟点")  # 今天 00:00 → 此刻必然已过点
    assert c.post(f"/api/items/{iid_late}/lend",
                  json={"borrower": "甲", "due_date": today, "due_time": "23:59"}).status_code == 200
    assert c.post(f"/api/items/{iid_early}/lend",
                  json={"borrower": "乙", "due_date": today, "due_time": "00:00"}).status_code == 200
    board = c.get("/api/board").json()
    loans = c.get("/api/loans").json()

    def verdict(payload, iid):
        for col in ("active", "overdue"):
            for l in payload[col]:
                if l["item_id"] == iid:
                    return col, l["overdue"]
        return None, None

    col_b, ov_b = verdict(board, iid_late)
    col_l, ov_l = verdict(loans, iid_late)
    assert (col_b, ov_b) == (col_l, ov_l) == ("active", False)
    col_b, ov_b = verdict(board, iid_early)
    col_l, ov_l = verdict(loans, iid_early)
    assert (col_b, ov_b) == (col_l, ov_l) == ("overdue", True)


def test_return_pins_overdue_conclusion(client):
    c, _, _ = client
    iid = _add_item(c)
    assert c.post(f"/api/items/{iid}/lend",
                  json={"borrower": "甲", "due_date": "2000-01-01", "due_time": "00:00"}).status_code == 200
    lid = c.get("/api/loans").json()["overdue"][0]["id"]
    r = c.post(f"/api/loans/{lid}/return")
    assert r.status_code == 200 and r.json()["was_overdue"] is True
    rec = next(l for l in c.get("/api/loans").json()["returned"] if l["id"] == lid)
    assert rec["overdue"] is True  # 结论钉死


def test_return_before_timepoint_not_overdue(client):
    """只过日（同日）未到点归还：不当逾期笔。"""
    from datetime import date
    c, _, _ = client
    iid = _add_item(c)
    today = date.today().isoformat()
    assert c.post(f"/api/items/{iid}/lend",
                  json={"borrower": "甲", "due_date": today, "due_time": "23:59"}).status_code == 200
    lid = c.get("/api/loans").json()["active"][0]["id"]
    r = c.post(f"/api/loans/{lid}/return")
    assert r.status_code == 200 and r.json()["was_overdue"] is False


def test_grace_adds_calendar_days_keeps_time(client):
    c, _, _ = client
    iid = _add_item(c)
    assert c.post(f"/api/items/{iid}/lend",
                  json={"borrower": "甲", "due_date": "2000-01-01", "due_time": "18:00"}).status_code == 200
    lid = c.get("/api/loans").json()["overdue"][0]["id"]
    r = c.post(f"/api/loans/{lid}/grace", json={"days": 3})
    assert r.status_code == 200
    assert r.json()["due_date"] == "2000-01-04" and r.json()["due_time"] == "18:00"


def test_extend_follow_and_keep(client):
    c, _, _ = client
    iid = _add_item(c)
    assert c.post(f"/api/items/{iid}/lend",
                  json={"borrower": "甲", "due_date": "2000-01-01", "due_time": "18:00"}).status_code == 200
    lid = c.get("/api/loans").json()["overdue"][0]["id"]
    r1 = c.post(f"/api/loans/{lid}/extend", json={"days": 5, "time_policy": "follow"})
    assert r1.status_code == 200
    assert r1.json()["due_date"] == "2000-01-06" and r1.json()["due_time"] == "18:00"
    r2 = c.post(f"/api/loans/{lid}/extend", json={"days": 2, "time_policy": "keep"})
    assert r2.status_code == 200
    assert r2.json()["due_date"] == "2000-01-08" and r2.json()["due_time"] == "18:00"
    r3 = c.post(f"/api/loans/{lid}/extend", json={"days": 1, "time_policy": "nope"})
    assert r3.status_code == 400
