from app.db import connect


def _migrate(c):
    """既有库补列/补设置，不碰任何已写下的数据。"""
    cols = {r["name"] for r in c.execute("PRAGMA table_info(loans)")}
    if "due_time" not in cols:
        c.execute("ALTER TABLE loans ADD COLUMN due_time TEXT")
    if c.execute("SELECT COUNT(*) c FROM settings WHERE key='grace_days'").fetchone()["c"] == 0:
        c.execute("INSERT INTO settings(key,value) VALUES ('grace_days','0')")
    c.commit()  # 旧库非空时 seed 分支会跳过，迁移自身的改动必须在此落盘


def init_db():
    c = connect()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS items(
      id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, owner TEXT, status TEXT, data_quality TEXT
    );
    CREATE TABLE IF NOT EXISTS loans(
      id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INT, borrower TEXT, status TEXT,
      due_date TEXT, due_time TEXT, lent_at TEXT, returned_at TEXT
    );
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    """)
    _migrate(c)
    if c.execute("SELECT COUNT(*) c FROM items").fetchone()["c"] == 0:
        c.executemany("INSERT INTO items(title,owner,status,data_quality) VALUES (?,?,?,?)", [
            ("电钻", "老周", "available", "clean"),
            ("折叠桌", "小陈", "available", "clean"),
            ("脏数据-无主", "", "available", "dirty"),
            ("已外借样例", "阿强", "on_loan", "clean"),
        ])
        c.execute(
            "INSERT INTO loans(item_id,borrower,status,due_date,due_time,lent_at) VALUES (?,?,?,?,?,?)",
            (4, "邻居甲", "active", "2020-06-01", None, "2020-05-01"),
        )
        c.execute("INSERT INTO settings(key,value) VALUES ('board_name','木色邻里板')")
        c.commit()
    c.close()
