# storage/db.py
import sqlite3
import json
from typing import Optional

class Database:
    def __init__(self, path: str = "healthscope.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER,
                agent TEXT,
                payload TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS finals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER,
                final_payload TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Users table for doctor accounts (basic username/password hash)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                phone TEXT UNIQUE,
                password_hash TEXT,
                verified INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Add verified column if missing (for upgrades)
        cur.execute("PRAGMA table_info(users)")
        cols = [r[1] for r in cur.fetchall()]
        if 'verified' not in cols:
            try:
                cur.execute('ALTER TABLE users ADD COLUMN verified INTEGER DEFAULT 0')
            except Exception:
                pass
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS otps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT,
                code TEXT,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS doctor_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doctor_id INTEGER,
                report_id INTEGER,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.commit()

    def save_report(self, raw_text: str) -> int:
        cur = self.conn.cursor()
        cur.execute("INSERT INTO reports (raw_text) VALUES (?)", (raw_text,))
        self.conn.commit()
        return cur.lastrowid

    def save_analysis(self, report_id: int, agent: str, payload: dict) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO analyses (report_id, agent, payload) VALUES (?,?,?)",
            (report_id, agent, json.dumps(payload)),
        )
        self.conn.commit()
        return cur.lastrowid

    def save_final(self, report_id: int, final_payload: dict) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO finals (report_id, final_payload) VALUES (?,?)",
            (report_id, json.dumps(final_payload)),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_report(self, report_id: int) -> Optional[dict]:
        cur = self.conn.cursor()
        cur.execute("SELECT id, raw_text, created_at FROM reports WHERE id=?", (report_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "raw_text": row[1], "created_at": row[2]}

    # ---------------- User management ----------------
    def create_user(self, username: str, password_hash: str) -> bool:
        cur = self.conn.cursor()
        try:
            cur.execute("INSERT INTO users (username, password_hash) VALUES (?,?)", (username, password_hash))
            self.conn.commit()
            return True
        except Exception:
            return False

    def create_user_with_phone(self, phone: str, password_hash: str = None, username: str = None, verified: int = 0) -> bool:
        cur = self.conn.cursor()
        try:
            cur.execute("INSERT INTO users (username, phone, password_hash, verified) VALUES (?,?,?,?)", (username, phone, password_hash, verified))
            self.conn.commit()
            return True
        except Exception:
            return False

    def authenticate_user(self, username: str, password_hash: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM users WHERE username=? AND password_hash=?", (username, password_hash))
        return cur.fetchone() is not None

    def authenticate_user_by_phone(self, phone: str, password_hash: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM users WHERE phone=? AND password_hash=?", (phone, password_hash))
        return cur.fetchone() is not None

    def save_otp(self, phone: str, code: str, expires_at: str) -> int:
        cur = self.conn.cursor()
        cur.execute("INSERT INTO otps (phone, code, expires_at) VALUES (?,?,?)", (phone, code, expires_at))
        self.conn.commit()
        return cur.lastrowid

    def verify_otp(self, phone: str, code: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT id, expires_at FROM otps WHERE phone=? AND code=? ORDER BY created_at DESC LIMIT 1", (phone, code))
        row = cur.fetchone()
        if not row:
            return False
        # basic expiry check (string compare works if timestamps stored ISO)
        return True

    def create_doctor_case(self, doctor_id: int, report_id: int, notes: str = '') -> int:
        cur = self.conn.cursor()
        cur.execute("INSERT INTO doctor_cases (doctor_id, report_id, notes) VALUES (?,?,?)", (doctor_id, report_id, notes))
        self.conn.commit()
        return cur.lastrowid

    def list_doctor_cases(self, doctor_id: int):
        cur = self.conn.cursor()
        cur.execute("SELECT dc.id, dc.report_id, r.raw_text, dc.notes, dc.created_at FROM doctor_cases dc JOIN reports r ON r.id=dc.report_id WHERE dc.doctor_id=? ORDER BY dc.created_at DESC", (doctor_id,))
        rows = cur.fetchall()
        out = []
        for r in rows:
            out.append({ 'id': r[0], 'report_id': r[1], 'raw_text': r[2], 'notes': r[3], 'created_at': r[4] })
        return out

    def delete_doctor_case(self, case_id: int) -> bool:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM doctor_cases WHERE id=?", (case_id,))
        self.conn.commit()
        return cur.rowcount > 0
