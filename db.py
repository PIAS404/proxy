# db.py
import sqlite3
from typing import Optional, Dict, Any

def init_db(db_path: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        tg_user_id INTEGER PRIMARY KEY,
        api_key_enc TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    )
    """)
    conn.commit()
    conn.close()

def set_user_key(db_path: str, tg_user_id: int, api_key_enc: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO users(tg_user_id, api_key_enc, updated_at)
    VALUES(?,?,datetime('now'))
    ON CONFLICT(tg_user_id) DO UPDATE SET
      api_key_enc=excluded.api_key_enc,
      updated_at=datetime('now')
    """, (tg_user_id, api_key_enc))
    conn.commit()
    conn.close()

def get_user_key_enc(db_path: str, tg_user_id: int) -> Optional[str]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT api_key_enc FROM users WHERE tg_user_id=?", (tg_user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row and row[0] else None

def delete_user(db_path: str, tg_user_id: int):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE tg_user_id=?", (tg_user_id,))
    conn.commit()
    conn.close()
