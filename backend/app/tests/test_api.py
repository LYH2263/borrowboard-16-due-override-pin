import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app import main  # 延迟导入，使 DATA_DIR 生效
    with TestClient(main.app) as c:
        yield c


def _lend(client, iid, borrower, due_date, due_time=None):
    body = {"borrower": borrower, "due_date": due_date}
    if due_time is not None:
        body["due_time"] = due_time
    return client.post(f"/api/items/{iid}/lend", json=body)


def _find(rows, borrower):
    return next(r for r in rows if r["borrower"] == borrower)


def test_bad_time_fails_whole_order_and_writes_nothing(client):
    r = _lend(client, 1, "整单失败-25点", "2099-01-01", "25:00")
    assert r.status_code == 422
    r = _lend(client, 1, "整单失败-缺分钟", "2099-01-01", "09")
    assert r.status_code == 422
    # 没有产生任何借阅，物品仍可借
    assert client.get("/api/items").json()[0]["status"] == "available"
    loans = client.get("/api/loans").json()
    assert not any(l["borrower"].startswith("整单失败") for l in loans["active"] + loans["overdue"])


def test_lend_stores_normalized_time(client):
    assert _lend(client, 1, "有钟点", "2099-01-01", "9:5").status_code == 200
    seed_loan = client.get("/api/loans/1").json()  # seed 样例笔无钟点
    new = client.get("/api/loans/2").json()
    assert new["due_time"] == "09:05"
    assert seed_loan["due_time"] is None


def _freeze(main, monkeypatch, day, hhmm):
    monkeypatch.setattr(main, "_now", lambda: (day, hhmm))


def test_same_verdict_board_sweep_detail_before_and_after_point(monkeypatch):
    monkeypatch.setenv("DATA_DIR", "/tmp/bb_consistency")
    import shutil, pathlib
    shutil.rmtree("/tmp/bb_consistency", ignore_errors=True)
    from app import main
    with TestClient(main.app) as client:
        today = __import__("datetime").date.today().isoformat()
        _freeze(main, monkeypatch, today, "09:00")
        _lend(client, 1, "跨点笔", today, "18:00")
        lid = _find(client.get("/api/loans").json()["active"], "跨点笔")["id"]

        board = client.get("/api/board").json()
        sweep = client.get("/api/loans").json()
        detail = client.get(f"/api/loans/{lid}").json()
        assert _find(board["active"], "跨点笔")["overdue"] is False
        assert _find(sweep["active"], "跨点笔")["overdue"] is False
        assert detail["overdue"] is False  # 顶细条与分栏同一结论

        _freeze(main, monkeypatch, today, "19:00")
        board = client.get("/api/board").json()
        sweep = client.get("/api/loans").json()
        detail = client.get(f"/api/loans/{lid}").json()
        assert board["counts"]["overdue"] >= 1
        assert _find(board["overdue"], "跨点笔")["overdue"] is True
        assert _find(sweep["overdue"], "跨点笔")["overdue"] is True
        assert detail["overdue"] is True
        # 归还必须得出同一结论：仍当逾期笔
        r = client.post(f"/api/loans/{lid}/return", json={})
        assert r.json()["overdue"] is True


def test_return_before_point_is_not_overdue(monkeypatch):
    monkeypatch.setenv("DATA_DIR", "/tmp/bb_early_return")
    import shutil
    shutil.rmtree("/tmp/bb_early_return", ignore_errors=True)
    from app import main
    with TestClient(main.app) as client:
        today = __import__("datetime").date.today().isoformat()
        _lend(client, 1, "提前还", today, "18:00")
        _freeze(main, monkeypatch, today, "09:00")
        lid = _find(client.get("/api/loans").json()["active"], "提前还")["id"]
        assert client.post(f"/api/loans/{lid}/return", json={}).json()["overdue"] is False


def test_extend_policies(client):
    _lend(client, 1, "带钟点顺延", "2099-01-01", "18:00")
    _lend(client, 2, "整日顺延", "2099-01-01")
    r1 = client.post("/api/loans/2/extend", json={"days": 3, "time_policy": "follow_day"}).json()
    assert r1["due_date"] == "2099-01-04" and r1["due_time"] == "18:00"
    r2 = client.post("/api/loans/3/extend", json={"days": 3, "time_policy": "follow_day"}).json()
    assert r2["due_date"] == "2099-01-04" and r2["due_time"] is None
    r3 = client.post("/api/loans/3/extend", json={"days": 1, "time_policy": "keep_time"}).json()
    assert r3["due_date"] == "2099-01-05" and r3["due_time"] == "23:59"


def test_grace_adds_days_but_keeps_time_and_keeps_day_loans_out(monkeypatch):
    monkeypatch.setenv("DATA_DIR", "/tmp/bb_grace")
    import shutil
    shutil.rmtree("/tmp/bb_grace", ignore_errors=True)
    from app import main
    with TestClient(main.app) as client:
        due = "2026-10-06"
        _lend(client, 1, "宽限钟点笔", due, "18:00")
        _lend(client, 2, "宽限整日笔", due)
        client.put("/api/settings/grace_days", json={"days": 1})

        _freeze(main, monkeypatch, "2026-10-07", "09:00")
        sweep = client.get("/api/loans").json()
        # 只过日未到点：两笔都不进逾期扫
        assert _find(sweep["active"], "宽限钟点笔")["overdue"] is False
        assert _find(sweep["active"], "宽限整日笔")["overdue"] is False
        # 已写下的钟点没被清掉
        assert _find(sweep["active"], "宽限钟点笔")["due_time"] == "18:00"

        _freeze(main, monkeypatch, "2026-10-07", "19:00")
        sweep = client.get("/api/loans").json()
        assert _find(sweep["overdue"], "宽限钟点笔")["overdue"] is True
        assert _find(sweep["active"], "宽限整日笔")["overdue"] is False
