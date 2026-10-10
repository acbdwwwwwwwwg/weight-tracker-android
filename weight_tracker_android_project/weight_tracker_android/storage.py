from __future__ import annotations

import csv
import logging
import os
import shutil
import sqlite3
import zipfile
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


class _ClosingConnection(sqlite3.Connection):
    """SQLite connection that also closes when used with a context manager."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


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
CREATE TABLE IF NOT EXISTS daily_activity (
    date TEXT PRIMARY KEY,
    workout INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS body_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_date TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    thumbnail_path TEXT
);
"""


class Storage:
    def __init__(self, base_dir: str | os.PathLike[str]):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_dir / "weight_tracker.db"
        self.backup_dir = self.base_dir / "backup"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.body_photo_dir = self.base_dir / "body_photos"
        self.body_photo_dir.mkdir(parents=True, exist_ok=True)
        self.body_photo_thumbnail_dir = self.base_dir / "body_photo_thumbnails"
        self.body_photo_thumbnail_dir.mkdir(parents=True, exist_ok=True)
        self._backup_lock = threading.RLock()
        self._backup_worker_active = False
        self._init_db()

    def _connect(self):
        con = sqlite3.connect(self.db_path, factory=_ClosingConnection)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _init_db(self):
        with self._connect() as con:
            con.executescript(SCHEMA)
            # Safe in-place migration for databases created by earlier APK versions.
            columns = {row[1] for row in con.execute("PRAGMA table_info(body_photos)").fetchall()}
            if "thumbnail_path" not in columns:
                con.execute("ALTER TABLE body_photos ADD COLUMN thumbnail_path TEXT")
            con.execute("CREATE INDEX IF NOT EXISTS idx_records_recorded_at ON records(recorded_at, id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_photos_date_created ON body_photos(photo_date, created_at, id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_recycle_deleted_at ON recycle_bin(deleted_at, id)")

    def backup(self, force: bool = False):
        """Create a consistent SQLite snapshot periodically for routine writes.

        Destructive operations may pass force=True. SQLite's online backup API is
        safer than copying a live database file and also works when connections
        are active. Routine writes schedule this in a worker, rate-limited to a
        six-hour interval; the newest twenty snapshots are retained.
        """
        if not self.db_path.exists():
            return None
        with self._backup_lock:
            backups = sorted(self.backup_dir.glob("weight_tracker_*.db"), key=lambda p: p.stat().st_mtime)
            now = time.time()
            if not force and backups and now - backups[-1].stat().st_mtime < 6 * 60 * 60:
                return backups[-1]
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            dst = self.backup_dir / f"weight_tracker_{stamp}.db"
            temp = dst.with_suffix(".db.part")
            try:
                source = self._connect()
                target = sqlite3.connect(str(temp))
                try:
                    source.backup(target)
                    target.commit()
                finally:
                    target.close()
                    source.close()
                os.replace(temp, dst)
            finally:
                try:
                    temp.unlink()
                except OSError:
                    pass
            backups = sorted(self.backup_dir.glob("weight_tracker_*.db"), key=lambda p: p.stat().st_mtime)
            for old in backups[:-20]:
                try:
                    old.unlink()
                except OSError:
                    pass
            return dst

    def schedule_backup(self):
        """Schedule a rate-limited database snapshot without blocking the UI thread."""
        with self._backup_lock:
            if self._backup_worker_active:
                return
            self._backup_worker_active = True

        def run():
            try:
                self.backup(force=False)
            except Exception:
                # Routine snapshots must never crash the app from a daemon thread.
                logging.exception("Scheduled database backup failed")
            finally:
                with self._backup_lock:
                    self._backup_worker_active = False

        threading.Thread(target=run, name="weight-db-backup", daemon=True).start()

    def create_full_backup(self):
        """Create a consistent ZIP snapshot with DB, originals, and thumbnails.

        Intended to be called by the background-task runner from UI actions.
        The database is snapshotted via SQLite's backup API; partially imported
        `.part` files are deliberately excluded.
        """
        if not self.db_path.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dst = self.backup_dir / f"weight_tracker_full_{stamp}.zip"
        temp_zip = dst.with_suffix(".zip.part")
        temp_db = self.backup_dir / f".snapshot_{stamp}.db.part"
        source = target = None
        try:
            source = self._connect()
            target = sqlite3.connect(str(temp_db))
            source.backup(target)
            target.commit()
            target.close()
            target = None
            source.close()
            source = None
            with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
                zf.write(temp_db, arcname="weight_tracker.db")
                for folder, archive_name in (
                    (self.body_photo_dir, "body_photos"),
                    (self.body_photo_thumbnail_dir, "body_photo_thumbnails"),
                ):
                    if not folder.exists():
                        continue
                    for item in sorted(folder.rglob("*")):
                        if item.is_file() and not item.name.endswith((".part", ".tmp")):
                            zf.write(item, arcname=str(Path(archive_name) / item.relative_to(folder)))
            os.replace(temp_zip, dst)
        finally:
            if target is not None:
                target.close()
            if source is not None:
                source.close()
            for temp_path in (temp_db, temp_zip):
                try:
                    temp_path.unlink()
                except OSError:
                    pass
        backups = sorted(self.backup_dir.glob("weight_tracker_full_*.zip"), key=lambda p: p.stat().st_mtime)
        for old in backups[:-10]:
            try:
                old.unlink()
            except OSError:
                pass
        return dst

    def restore_full_backup(self, backup_path: str | os.PathLike[str]):
        """Validate and restore a full ZIP backup, preserving rollback copies on failure.

        The archive is never extracted with ``extractall``. Paths are checked,
        the SQLite database is integrity-checked, and all referenced photo files
        must be present before the current data is touched. The existing data is
        backed up first; directory/database swaps are rolled back if installation
        or schema migration fails.
        """
        archive_path = Path(backup_path)
        if not archive_path.is_file():
            raise FileNotFoundError(f"备份文件不存在：{archive_path}")
        # Estimate the temporary extraction footprint before allocating disk space.
        with zipfile.ZipFile(archive_path, "r") as archive_check:
            required_bytes = sum(info.file_size for info in archive_check.infolist() if not info.is_dir())
        free_bytes = shutil.disk_usage(self.base_dir).free
        if required_bytes > free_bytes:
            raise OSError(f"可用存储空间不足：备份展开约需 {required_bytes / (1024 * 1024):.1f} MB。")

        token = uuid.uuid4().hex
        stage = self.base_dir / f".restore_stage_{token}"
        rollback = self.base_dir / f".restore_rollback_{token}"
        stage.mkdir(parents=True, exist_ok=False)
        try:
            rollback.mkdir(parents=True, exist_ok=False)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        stage_db = stage / "weight_tracker.db"
        staged_photo_dir = stage / "body_photos"
        staged_thumb_dir = stage / "body_photo_thumbnails"
        try:
            staged_photo_dir.mkdir()
            staged_thumb_dir.mkdir()
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            shutil.rmtree(rollback, ignore_errors=True)
            raise
        old_db_moved = old_photos_moved = old_thumbs_moved = False
        new_db_installed = new_photos_installed = new_thumbs_installed = False
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                infos = zf.infolist()
                names = set()
                for info in infos:
                    name = info.filename.replace("\\", "/")
                    parts = Path(name).parts
                    if name.startswith("/") or any(part in ("..", "") for part in parts):
                        raise ValueError("备份包含不安全的文件路径")
                    if info.is_dir():
                        continue
                    if name in names:
                        raise ValueError(f"备份包含重复文件：{name}")
                    names.add(name)
                    if name != "weight_tracker.db" and not (
                        name.startswith("body_photos/") or name.startswith("body_photo_thumbnails/")
                    ):
                        raise ValueError(f"备份包含不支持的文件：{name}")
                if "weight_tracker.db" not in names:
                    raise ValueError("备份中没有 weight_tracker.db")
                for name in names:
                    target = stage / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name, "r") as source, open(target, "wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)

            # Validate database before touching the live installation.
            check = sqlite3.connect(str(stage_db))
            try:
                integrity = check.execute("PRAGMA integrity_check").fetchone()
                if not integrity or integrity[0] != "ok":
                    raise ValueError("备份数据库完整性检查失败")
                tables = {r[0] for r in check.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()}
                required = {"records", "recycle_bin", "settings", "daily_activity", "body_photos"}
                if not required.issubset(tables):
                    raise ValueError("备份数据库版本不兼容，缺少必要的数据表")
                photo_columns = {r[1] for r in check.execute("PRAGMA table_info(body_photos)")}
                if not {"id", "photo_date", "path", "created_at"}.issubset(photo_columns):
                    raise ValueError("备份中的照片索引表结构不完整")
                for row in check.execute("SELECT path, thumbnail_path FROM body_photos").fetchall():
                    for index, value in enumerate(row):
                        if not value:
                            continue
                        relative = Path(str(value))
                        if relative.is_absolute() or ".." in relative.parts:
                            raise ValueError("备份数据库中包含不安全的照片路径")
                        archive_name = relative.as_posix()
                        if archive_name not in names:
                            # A thumbnail may be absent in older backups; the original may not.
                            if index == 0:
                                raise ValueError(f"备份缺少照片原图：{archive_name}")
                check.execute("PRAGMA foreign_key_check").fetchall()
            finally:
                check.close()

            # Pre-restore snapshot is the recovery point if the swap is interrupted.
            safety_backup = self.create_full_backup()
            if safety_backup is None:
                raise OSError("无法创建恢复前保护备份，已取消恢复")

            if self.db_path.exists():
                os.replace(self.db_path, rollback / "weight_tracker.db")
                old_db_moved = True
            if self.body_photo_dir.exists():
                os.replace(self.body_photo_dir, rollback / "body_photos")
                old_photos_moved = True
            if self.body_photo_thumbnail_dir.exists():
                os.replace(self.body_photo_thumbnail_dir, rollback / "body_photo_thumbnails")
                old_thumbs_moved = True

            os.replace(staged_photo_dir, self.body_photo_dir)
            new_photos_installed = True
            os.replace(staged_thumb_dir, self.body_photo_thumbnail_dir)
            new_thumbs_installed = True
            os.replace(stage_db, self.db_path)
            new_db_installed = True
            self._init_db()
            with self._connect() as con:
                integrity = con.execute("PRAGMA integrity_check").fetchone()
                if not integrity or integrity[0] != "ok":
                    raise sqlite3.DatabaseError("恢复后的数据库完整性检查失败")
            return {"safety_backup": safety_backup, "records": len(self.list_records()),
                    "photos": self.count_body_photos()}
        except Exception:
            # Best-effort rollback to the exact pre-restore paths.
            for installed, path in (
                (new_db_installed, self.db_path),
                (new_photos_installed, self.body_photo_dir),
                (new_thumbs_installed, self.body_photo_thumbnail_dir),
            ):
                if installed:
                    try:
                        if path.is_dir():
                            shutil.rmtree(path)
                        else:
                            path.unlink(missing_ok=True)
                    except OSError:
                        logging.exception("Could not remove partially restored path %s", path)
            for moved, name, destination in (
                (old_db_moved, "weight_tracker.db", self.db_path),
                (old_photos_moved, "body_photos", self.body_photo_dir),
                (old_thumbs_moved, "body_photo_thumbnails", self.body_photo_thumbnail_dir),
            ):
                source = rollback / name
                if moved and source.exists():
                    try:
                        os.replace(source, destination)
                    except OSError:
                        logging.exception("Could not roll back restored path %s", destination)
            raise
        finally:
            for directory in (stage, rollback):
                try:
                    shutil.rmtree(directory)
                except OSError:
                    logging.exception("Could not clean restore temporary directory %s", directory)

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
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO records(weight, recorded_at, note) VALUES (?, ?, ?)",
                (weight, recorded_at.isoformat(sep=" "), note),
            )
            record_id = int(cur.lastrowid)
        self.schedule_backup()
        return record_id

    def update(self, record_id: int, weight: float, note: Optional[str], recorded_at: datetime):
        weight = self._validate_weight(weight)
        # Editing overwrites an existing value, so preserve the prior database state.
        self.backup(force=True)
        with self._connect() as con:
            cur = con.execute(
                "UPDATE records SET weight=?, note=?, recorded_at=? WHERE id=?",
                (weight, note, recorded_at.isoformat(sep=" "), int(record_id)),
            )
            if cur.rowcount == 0:
                raise KeyError("记录不存在")
        self.schedule_backup()

    def delete(self, record_id: int):
        """Move to recycle bin; the operation is reversible, so don't snapshot synchronously."""
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
        self.schedule_backup()

    def recycle(self):
        with self._connect() as con:
            return [dict(r) for r in con.execute(
                "SELECT id, original_id, weight, recorded_at, note, deleted_at FROM recycle_bin ORDER BY deleted_at DESC, id DESC"
            ).fetchall()]

    def restore(self, recycle_id: int):
        with self._connect() as con:
            row = con.execute("SELECT * FROM recycle_bin WHERE id=?", (int(recycle_id),)).fetchone()
            if row is None:
                raise KeyError("回收站记录不存在")
            con.execute(
                "INSERT INTO records(weight, recorded_at, note) VALUES (?, ?, ?)",
                (row["weight"], row["recorded_at"], row["note"]),
            )
            con.execute("DELETE FROM recycle_bin WHERE id=?", (int(recycle_id),))
        self.schedule_backup()

    def permanently_delete(self, recycle_id: int):
        self.backup(force=True)
        with self._connect() as con:
            cur = con.execute("DELETE FROM recycle_bin WHERE id=?", (int(recycle_id),))
            if cur.rowcount == 0:
                raise KeyError("回收站记录不存在")

    def get_setting(self, key: str):
        with self._connect() as con:
            row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return None if row is None else row["value"]

    def set_setting(self, key: str, value):
        with self._connect() as con:
            con.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, None if value is None else str(value)),
            )
        self.schedule_backup()

    def set_workout(self, date_value: str, workout: bool):
        with self._connect() as con:
            con.execute(
                "INSERT INTO daily_activity(date, workout) VALUES (?, ?) "
                "ON CONFLICT(date) DO UPDATE SET workout=excluded.workout",
                (str(date_value), 1 if workout else 0),
            )
        self.schedule_backup()

    def get_workout(self, date_value: str) -> bool:
        with self._connect() as con:
            row = con.execute("SELECT workout FROM daily_activity WHERE date=?", (str(date_value),)).fetchone()
            return bool(row["workout"]) if row else False

    def list_workouts_for_month(self, year: int, month: int):
        prefix = f"{int(year):04d}-{int(month):02d}-"
        with self._connect() as con:
            rows = con.execute(
                "SELECT date, workout FROM daily_activity WHERE date LIKE ? ORDER BY date ASC",
                (prefix + "%",),
            ).fetchall()
            return {r["date"]: bool(r["workout"]) for r in rows}

    def list_workouts_between(self, start_date: str, end_date: str):
        with self._connect() as con:
            rows = con.execute(
                "SELECT date, workout FROM daily_activity WHERE date BETWEEN ? AND ? ORDER BY date ASC",
                (str(start_date), str(end_date)),
            ).fetchall()
            return {r["date"]: bool(r["workout"]) for r in rows}

    def count_body_photos(self) -> int:
        with self._connect() as con:
            row = con.execute("SELECT COUNT(*) AS count FROM body_photos").fetchone()
            return int(row["count"])

    def count_body_photos_for_date(self, date_value: str) -> int:
        with self._connect() as con:
            row = con.execute(
                "SELECT COUNT(*) AS count FROM body_photos WHERE photo_date=?", (str(date_value),)
            ).fetchone()
            return int(row["count"])

    def body_photo_counts_for_month(self, year: int, month: int):
        start = f"{int(year):04d}-{int(month):02d}-01"
        if int(month) == 12:
            end = f"{int(year) + 1:04d}-01-01"
        else:
            end = f"{int(year):04d}-{int(month) + 1:02d}-01"
        with self._connect() as con:
            rows = con.execute(
                "SELECT photo_date, COUNT(*) AS cnt FROM body_photos "
                "WHERE photo_date >= ? AND photo_date < ? GROUP BY photo_date",
                (start, end),
            ).fetchall()
            return {r["photo_date"]: int(r["cnt"]) for r in rows}

    def add_body_photo(self, photo_date: str, path: str | os.PathLike[str], created_at: Optional[datetime] = None,
                       thumbnail_path: Optional[str | os.PathLike[str]] = None):
        created_at = created_at or datetime.now()
        absolute = Path(path).resolve()
        base = self.base_dir.resolve()
        try:
            relative = absolute.relative_to(base)
        except ValueError as exc:
            raise ValueError("照片必须保存在应用数据目录中") from exc
        thumbnail_relative = None
        if thumbnail_path is not None:
            thumb_absolute = Path(thumbnail_path).resolve()
            try:
                thumbnail_relative = str(thumb_absolute.relative_to(base))
            except ValueError as exc:
                raise ValueError("缩略图必须保存在应用数据目录中") from exc
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO body_photos(photo_date, path, created_at, thumbnail_path) VALUES (?, ?, ?, ?)",
                (str(photo_date), str(relative), created_at.isoformat(sep=" "), thumbnail_relative),
            )
            photo_id = int(cur.lastrowid)
        self.schedule_backup()
        return photo_id

    def list_body_photos(self):
        with self._connect() as con:
            return [dict(r) for r in con.execute(
                "SELECT id, photo_date, path, created_at, thumbnail_path FROM body_photos "
                "ORDER BY photo_date ASC, created_at ASC, id ASC"
            ).fetchall()]

    def set_body_photo_thumbnail(self, photo_id: int, thumbnail_path: str | os.PathLike[str]):
        absolute = Path(thumbnail_path).resolve()
        base = self.base_dir.resolve()
        try:
            relative = str(absolute.relative_to(base))
        except ValueError as exc:
            raise ValueError("缩略图必须保存在应用数据目录中") from exc
        with self._connect() as con:
            cur = con.execute("UPDATE body_photos SET thumbnail_path=? WHERE id=?", (relative, int(photo_id)))
            if cur.rowcount == 0:
                raise KeyError("照片记录不存在")
        self.schedule_backup()

    def body_photo_thumbnail_path(self, row):
        value = row.get("thumbnail_path") if hasattr(row, "get") else None
        if value:
            relative = Path(str(value))
            candidate = (self.base_dir / relative).resolve()
            base = self.base_dir.resolve()
            try:
                candidate.relative_to(base)
            except ValueError as exc:
                raise ValueError("检测到非法缩略图路径") from exc
            if candidate.exists():
                return candidate
        # Stable fallback location used to lazily create thumbnails for old records.
        return self.body_photo_thumbnail_dir / f"{int(row['id'])}.jpg"

    def body_photo_counts(self):
        with self._connect() as con:
            rows = con.execute(
                "SELECT photo_date, COUNT(*) AS cnt FROM body_photos GROUP BY photo_date"
            ).fetchall()
            return {r["photo_date"]: int(r["cnt"]) for r in rows}

    def body_photo_path(self, row):
        relative = Path(str(row["path"]))
        candidate = (self.base_dir / relative).resolve()
        base = self.base_dir.resolve()
        try:
            candidate.relative_to(base)
        except ValueError as exc:
            raise ValueError("检测到非法照片路径") from exc
        return candidate

    def delete_body_photo(self, photo_id: int):
        with self._connect() as con:
            row = con.execute("SELECT id, path, thumbnail_path FROM body_photos WHERE id=?", (int(photo_id),)).fetchone()
            if row is None:
                raise KeyError("照片不存在")
            con.execute("DELETE FROM body_photos WHERE id=?", (int(photo_id),))
        try:
            self.body_photo_path(row).unlink()
        except OSError:
            pass
        thumb_values = [row["thumbnail_path"], str(self.body_photo_thumbnail_dir / f"{int(photo_id)}.jpg")]
        for value in thumb_values:
            if not value:
                continue
            candidate = Path(str(value))
            if not candidate.is_absolute():
                candidate = self.base_dir / candidate
            try:
                candidate = candidate.resolve()
                candidate.relative_to(self.base_dir.resolve())
                candidate.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass
        self.schedule_backup()

    def import_csv(self, path: str | os.PathLike[str]):
        """Import valid CSV rows idempotently; DB/storage failures roll back the batch."""
        inserted = 0
        skipped = 0
        failed = []
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
                    except (ValueError, TypeError, KeyError, AttributeError) as exc:
                        failed.append((line_no, str(exc)))
                        continue
                    exists = con.execute(
                        "SELECT 1 FROM records WHERE weight=? AND recorded_at=? AND COALESCE(note,'')=COALESCE(?, '') LIMIT 1",
                        (w, dt.isoformat(sep=" "), note),
                    ).fetchone()
                    if exists:
                        skipped += 1
                        continue
                    # sqlite errors (including disk-full) intentionally escape and roll back.
                    con.execute(
                        "INSERT INTO records(weight, recorded_at, note) VALUES (?, ?, ?)",
                        (w, dt.isoformat(sep=" "), note),
                    )
                    inserted += 1
        if inserted:
            self.schedule_backup()
        return inserted, skipped, failed

    def export_csv(self, path: str | os.PathLike[str], rows):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "weight", "recorded_at", "note"])
            for r in rows:
                writer.writerow([r["id"], r["weight"], r["recorded_at"], r.get("note") or ""])
