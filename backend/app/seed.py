from app.db import connect

def _has_column(c, table: str, column: str) -> bool:
    return any(r["name"] == column for r in c.execute(f"PRAGMA table_info({table})"))

def init_db():
    c = connect()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS items(
      id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, owner TEXT, status TEXT, data_quality TEXT
    );
    CREATE TABLE IF NOT EXISTS loans(
      id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INT, borrower TEXT, status TEXT,
      due_date TEXT, lent_at TEXT, returned_at TEXT
    );
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    """)
    # 轻量迁移：截止钟点 + 归还时刻钉死的逾期结论
    if not _has_column(c, "loans", "due_time"):
        c.execute("ALTER TABLE loans ADD COLUMN due_time TEXT NOT NULL DEFAULT ''")
    if not _has_column(c, "loans", "was_overdue"):
        c.execute("ALTER TABLE loans ADD COLUMN was_overdue INTEGER NOT NULL DEFAULT 0")
    if c.execute("SELECT COUNT(*) c FROM items").fetchone()["c"] == 0:
        c.executemany("INSERT INTO items(title,owner,status,data_quality) VALUES (?,?,?,?)", [
            ("电钻", "老周", "available", "clean"),
            ("折叠桌", "小陈", "available", "clean"),
            ("脏数据-无主", "", "available", "dirty"),
            ("已外借样例", "阿强", "on_loan", "clean"),
        ])
        c.execute(
            "INSERT INTO loans(item_id,borrower,status,due_date,due_time,lent_at) "
            "VALUES (?,?,?,?,?,?)",
            (4, "邻居甲", "active", "2020-06-01", "", "2020-05-01"),
        )
        c.execute("INSERT INTO settings(key,value) VALUES ('board_name','木色邻里板')")
        c.commit()
    c.close()
