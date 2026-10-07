from __future__ import annotations

import csv
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    weight REAL NOT NULL,
    recorded_at TEXT NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS recycle_bin (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_id INTEGER NOT NULL,
    weight REAL NOT NULL,
    recorded_at TEXT NOT NULL,
    note TEXT,
    deleted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class Storage:
    def __init__(self, base_dir: str | os.PathLike[str]):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_dir / "weight_tracker.db"
        self.backup_dir = self.base_dir / "backup"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _init_db(self):
        with self._connect() as con:
            con.executescript(SCHEMA)

    def backup(self):
        if not self.db_path.exists():
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dst = self.backup_dir / f"weight_tracker_{stamp}.db"
        shutil.copy2(self.db_path, dst)
        backups = sorted(self.backup_dir.glob("weight_tracker_*.db"))
        for old in backups[:-10]:
            try:
                old.unlink()
            except OSError:
                pass

    @staticmethod
    def _validate_weight(weight: float) -> float:
        weight = float(weight)
        if not (weight > 0.0):
            raise ValueError("体重必须大于 0")
        if weight != weight or weight in (float("inf"), float("-inf")):
            raise ValueError("体重必须是有限数字")
        return weight

    def list_records(self, start: Optional[datetime] = None, end: Optional[datetime] = None):
        sql = "SELECT id, weight, recorded_at, note FROM records"
        args = []
        if start is not None and end is not None:
            sql += " WHERE recorded_at BETWEEN ? AND ?"
            args.extend([start.isoformat(sep=" "), end.isoformat(sep=" ")])
        sql += " ORDER BY recorded_at ASC, id ASC"
        with self._connect() as con:
            return [dict(r) for r in con.execute(sql, args).fetchall()]

    def insert(self, weight: float, recorded_at: datetime, note: Optional[str] = None):
        weight = self._validate_weight(weight)
        self.backup()
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO records(weight, recorded_at, note) VALUES (?, ?, ?)",
                (weight, recorded_at.isoformat(sep=" "), note),
            )
            return int(cur.lastrowid)

    def update(self, record_id: int, weight: float, note: Optional[str], recorded_at: datetime):
        weight = self._validate_weight(weight)
        self.backup()
        with self._connect() as con:
            cur = con.execute(
                "UPDATE records SET weight=?, note=?, recorded_at=? WHERE id=?",
                (weight, note, recorded_at.isoformat(sep=" "), int(record_id)),
            )
            if cur.rowcount == 0:
                raise KeyError("记录不存在")

    def delete(self, record_id: int):
        self.backup()
        now = datetime.now().isoformat(sep=" ")
        with self._connect() as con:
            row = con.execute(
                "SELECT id, weight, recorded_at, note FROM records WHERE id=?",
                (int(record_id),),
            ).fetchone()
            if row is None:
                raise KeyError("记录不存在")
            con.execute(
                "INSERT INTO recycle_bin(original_id, weight, recorded_at, note, deleted_at) VALUES (?, ?, ?, ?, ?)",
                (row["id"], row["weight"], row["recorded_at"], row["note"], now),
            )
            con.execute("DELETE FROM records WHERE id=?", (int(record_id),))

    def recycle(self):
        with self._connect() as con:
            return [dict(r) for r in con.execute(
                "SELECT id, original_id, weight, recorded_at, note, deleted_at FROM recycle_bin ORDER BY deleted_at DESC, id DESC"
            ).fetchall()]

    def restore(self, recycle_id: int):
        self.backup()
        with self._connect() as con:
            row = con.execute("SELECT * FROM recycle_bin WHERE id=?", (int(recycle_id),)).fetchone()
            if row is None:
                raise KeyError("回收站记录不存在")
            con.execute(
                "INSERT INTO records(weight, recorded_at, note) VALUES (?, ?, ?)",
                (row["weight"], row["recorded_at"], row["note"]),
            )
            con.execute("DELETE FROM recycle_bin WHERE id=?", (int(recycle_id),))

    def permanently_delete(self, recycle_id: int):
        self.backup()
        with self._connect() as con:
            cur = con.execute("DELETE FROM recycle_bin WHERE id=?", (int(recycle_id),))
            if cur.rowcount == 0:
                raise KeyError("回收站记录不存在")

    def get_setting(self, key: str):
        with self._connect() as con:
            row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return None if row is None else row["value"]

    def set_setting(self, key: str, value):
        self.backup()
        with self._connect() as con:
            con.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, None if value is None else str(value)),
            )

    def import_csv(self, path: str | os.PathLike[str]):
        inserted = 0
        skipped = 0
        failed = []
        self.backup()
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            cols = {str(c).strip().lower(): c for c in (reader.fieldnames or [])}
            weight_key = next((cols[k] for k in ("weight", "体重") if k in cols), None)
            time_key = next((cols[k] for k in ("recorded_at", "datetime", "date", "时间", "日期") if k in cols), None)
            note_key = next((cols[k] for k in ("note", "备注") if k in cols), None)
            if not weight_key or not time_key:
                raise ValueError("CSV 至少需要“体重”和“日期/时间”列")
            with self._connect() as con:
                for line_no, row in enumerate(reader, start=2):
                    try:
                        w = self._validate_weight(row[weight_key])
                        dt = datetime.fromisoformat(str(row[time_key]).strip().replace("Z", "+00:00"))
                        note = (str(row[note_key]).strip() if note_key and row.get(note_key) else None) or None
                        exists = con.execute(
                            "SELECT 1 FROM records WHERE weight=? AND recorded_at=? AND COALESCE(note,'')=COALESCE(?, '') LIMIT 1",
                            (w, dt.isoformat(sep=" "), note),
                        ).fetchone()
                        if exists:
                            skipped += 1
                            continue
                        con.execute(
                            "INSERT INTO records(weight, recorded_at, note) VALUES (?, ?, ?)",
                            (w, dt.isoformat(sep=" "), note),
                        )
                        inserted += 1
                    except Exception as e:
                        failed.append((line_no, str(e)))
        return inserted, skipped, failed

    def export_csv(self, path: str | os.PathLike[str], rows):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "weight", "recorded_at", "note"])
            for r in rows:
                writer.writerow([r["id"], r["weight"], r["recorded_at"], r.get("note") or ""])
