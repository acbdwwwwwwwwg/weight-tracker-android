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
from time import perf_counter

from services.performance import mark
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
CREATE TABLE IF NOT EXISTS foods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    calories_per_100g REAL NOT NULL DEFAULT 0,
    protein_per_100g REAL NOT NULL DEFAULT 0,
    carbs_per_100g REAL NOT NULL DEFAULT 0,
    fat_per_100g REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS food_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at TEXT NOT NULL,
    meal_type TEXT NOT NULL,
    food_name TEXT NOT NULL,
    amount_g REAL NOT NULL,
    calories_kcal REAL NOT NULL,
    protein_g REAL NOT NULL DEFAULT 0,
    carbs_g REAL NOT NULL DEFAULT 0,
    fat_g REAL NOT NULL DEFAULT 0,
    food_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strength_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    performed_at TEXT NOT NULL,
    exercise_name TEXT NOT NULL,
    sets INTEGER NOT NULL DEFAULT 0,
    reps INTEGER NOT NULL DEFAULT 0,
    load_kg REAL NOT NULL DEFAULT 0,
    duration_minutes REAL NOT NULL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS body_measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    measured_at TEXT NOT NULL,
    waist_cm REAL,
    hip_cm REAL,
    chest_cm REAL,
    body_fat_pct REAL,
    note TEXT,
    created_at TEXT NOT NULL
);
"""


class Storage:
    # The app's entered weight unit is 斤. These deliberately broad bounds catch
    # obvious unit/decimal mistakes without trying to judge a user's goal.
    MIN_WEIGHT_JIN = 20.0
    MAX_WEIGHT_JIN = 1000.0
    MIN_HEIGHT_CM = 80.0
    MAX_HEIGHT_CM = 250.0
    FUTURE_TIME_GRACE = timedelta(seconds=0)

    def __init__(self, base_dir: str | os.PathLike[str]):
        startup_started = perf_counter()
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
        mark("storage_initialized", startup_started)

    def _connect(self):
        con = sqlite3.connect(self.db_path, factory=_ClosingConnection)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _init_db(self):
        init_started = perf_counter()
        with self._connect() as con:
            con.executescript(SCHEMA)
            # Idempotent in-place migration for core tables created by older APKs.
            # CREATE TABLE IF NOT EXISTS does not add new columns to an existing DB.
            def columns(table):
                return {row[1] for row in con.execute(f'PRAGMA table_info("{table}")').fetchall()}

            record_columns = columns("records")
            if "note" not in record_columns:
                con.execute("ALTER TABLE records ADD COLUMN note TEXT")

            activity_columns = columns("daily_activity")
            if "workout" not in activity_columns:
                # The previous schema did not encode a completion flag; default
                # to unchecked rather than inventing a completed workout.
                con.execute("ALTER TABLE daily_activity ADD COLUMN workout INTEGER NOT NULL DEFAULT 0")

            recycle_columns = columns("recycle_bin")
            if "original_id" not in recycle_columns:
                con.execute("ALTER TABLE recycle_bin ADD COLUMN original_id INTEGER NOT NULL DEFAULT 0")
            if "note" not in recycle_columns:
                con.execute("ALTER TABLE recycle_bin ADD COLUMN note TEXT")
            if "deleted_at" not in recycle_columns:
                con.execute("ALTER TABLE recycle_bin ADD COLUMN deleted_at TEXT NOT NULL DEFAULT ''")

            photo_columns = columns("body_photos")
            if "created_at" not in photo_columns:
                con.execute("ALTER TABLE body_photos ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
            if "thumbnail_path" not in photo_columns:
                con.execute("ALTER TABLE body_photos ADD COLUMN thumbnail_path TEXT")

            con.execute("CREATE INDEX IF NOT EXISTS idx_records_recorded_at ON records(recorded_at, id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_photos_date_created ON body_photos(photo_date, created_at, id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_recycle_deleted_at ON recycle_bin(deleted_at, id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_food_logs_date ON food_logs(logged_at, id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_strength_logs_date ON strength_logs(performed_at, id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_body_measurements_date ON body_measurements(measured_at, id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_foods_name ON foods(name COLLATE NOCASE)")
        mark("storage_schema_ready", init_started)

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

    @staticmethod
    def _safe_archive_names(archive: zipfile.ZipFile):
        """Validate ZIP paths before reading or extracting any member."""
        names = set()
        total_uncompressed = 0
        for info in archive.infolist():
            if "\\" in info.filename:
                raise ValueError("备份包含不规范的文件路径")
            normalized = info.filename
            path = Path(normalized)
            if (not normalized or normalized.startswith("/") or
                    any(part in ("..", "") for part in path.parts) or
                    (len(normalized) >= 2 and normalized[1] == ":") or "\x00" in normalized):
                raise ValueError("备份包含不安全的文件路径")
            if info.is_dir():
                continue
            if normalized in names:
                raise ValueError(f"备份包含重复文件：{normalized}")
            if normalized != "weight_tracker.db" and not (
                normalized.startswith("body_photos/") or
                normalized.startswith("body_photo_thumbnails/")
            ):
                raise ValueError(f"备份包含不支持的文件：{normalized}")
            names.add(normalized)
            total_uncompressed += int(info.file_size)
        if "weight_tracker.db" not in names:
            raise ValueError("备份中没有 weight_tracker.db")
        return names, total_uncompressed

    @staticmethod
    def _migrate_backup_database(db_path: Path):
        """Migrate a staged legacy database without touching the live database.

        Older full backups did not always have `body_photos.thumbnail_path`,
        and some omitted the recycle-bin/workout tables entirely. Run the same
        idempotent schema creation against the staged copy before validating it.
        """
        con = sqlite3.connect(str(db_path))
        try:
            tables = {row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            if "records" not in tables:
                raise ValueError("备份数据库缺少体重记录表，不能恢复")
            con.executescript(SCHEMA)

            def columns(table):
                return {row[1] for row in con.execute(f'PRAGMA table_info("{table}")').fetchall()}

            record_columns = columns("records")
            if not {"id", "weight", "recorded_at"}.issubset(record_columns):
                raise ValueError("备份中的体重记录表结构不完整")
            if "note" not in record_columns:
                con.execute("ALTER TABLE records ADD COLUMN note TEXT")

            photo_columns = columns("body_photos")
            if not {"id", "photo_date", "path"}.issubset(photo_columns):
                raise ValueError("备份中的照片索引表结构不完整")
            if "created_at" not in photo_columns:
                con.execute("ALTER TABLE body_photos ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
            if "thumbnail_path" not in photo_columns:
                con.execute("ALTER TABLE body_photos ADD COLUMN thumbnail_path TEXT")

            recycle_columns = columns("recycle_bin")
            if not {"id", "weight", "recorded_at"}.issubset(recycle_columns):
                raise ValueError("备份中的回收站表结构不完整")
            if "original_id" not in recycle_columns:
                con.execute("ALTER TABLE recycle_bin ADD COLUMN original_id INTEGER NOT NULL DEFAULT 0")
            if "note" not in recycle_columns:
                con.execute("ALTER TABLE recycle_bin ADD COLUMN note TEXT")
            if "deleted_at" not in recycle_columns:
                con.execute("ALTER TABLE recycle_bin ADD COLUMN deleted_at TEXT NOT NULL DEFAULT '1970-01-01 00:00:00'")

            settings_columns = columns("settings")
            if not {"key", "value"}.issubset(settings_columns):
                raise ValueError("备份中的设置表结构不完整")
            activity_columns = columns("daily_activity")
            if "date" not in activity_columns:
                raise ValueError("备份中的训练日历表结构不完整")
            if "workout" not in activity_columns:
                con.execute("ALTER TABLE daily_activity ADD COLUMN workout INTEGER NOT NULL DEFAULT 0")

            con.execute("CREATE INDEX IF NOT EXISTS idx_records_recorded_at ON records(recorded_at, id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_photos_date_created ON body_photos(photo_date, created_at, id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_recycle_deleted_at ON recycle_bin(deleted_at, id)")
            con.commit()
            integrity = con.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ValueError("备份数据库完整性检查失败")
        finally:
            con.close()

    @staticmethod
    def _photo_archive_path(value):
        relative = Path(str(value))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("备份数据库中包含不安全的照片路径")
        normalized = relative.as_posix()
        if not normalized.startswith("body_photos/"):
            raise ValueError(f"照片路径不在应用照片目录中：{normalized}")
        return normalized

    def _validate_live_originals(self):
        """Refuse to call a backup complete if any indexed original is missing."""
        if not self.db_path.exists():
            return
        with self._connect() as con:
            tables = {row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            if "body_photos" not in tables:
                return
            cols = {row[1] for row in con.execute("PRAGMA table_info(body_photos)").fetchall()}
            if not {"id", "path"}.issubset(cols):
                raise ValueError("当前照片索引表结构不完整，无法创建完整备份")
            rows = con.execute("SELECT id, path FROM body_photos").fetchall()
        for row in rows:
            relative = self._photo_archive_path(row["path"])
            original = (self.base_dir / relative).resolve()
            try:
                original.relative_to(self.body_photo_dir.resolve())
            except ValueError as exc:
                raise ValueError(f"照片 #{row['id']} 的原图路径不安全") from exc
            if not original.is_file():
                raise FileNotFoundError(f"照片 #{row['id']} 的原图不存在，无法创建完整备份：{relative}")
            if original.stat().st_size <= 0:
                raise ValueError(f"照片 #{row['id']} 的原图为空文件，无法创建完整备份：{relative}")

    def _restore_space_estimate(self, target_unpacked_bytes: int):
        """Estimate peak free space for staging the target plus protecting current data.

        The estimate intentionally treats the protected backup as nearly the size
        of the current live data. Photos usually compress little, so using only
        the existing ZIP size would underestimate required space.
        """
        free_bytes = int(shutil.disk_usage(self.base_dir).free)
        current_db_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        current_live_bytes = current_db_bytes
        for folder in (self.body_photo_dir, self.body_photo_thumbnail_dir):
            if folder.exists():
                for item in folder.rglob("*"):
                    try:
                        if item.is_file() and not item.name.endswith((".part", ".tmp")):
                            current_live_bytes += int(item.stat().st_size)
                    except OSError:
                        # Missing/inaccessible files will be handled by the
                        # backup-integrity preflight; do not underestimate sizes
                        # for files that were successfully measured.
                        continue
        reserve = max(8 * 1024 * 1024, int(current_live_bytes * 0.08))
        estimated_peak = int(target_unpacked_bytes) + current_live_bytes + current_db_bytes + reserve
        return {
            "free_bytes": free_bytes,
            "current_live_bytes": current_live_bytes,
            "current_db_bytes": current_db_bytes,
            "reserve_bytes": reserve,
            "estimated_peak_bytes": estimated_peak,
            "space_sufficient": estimated_peak <= free_bytes,
        }

    def inspect_full_backup(self, backup_path: str | os.PathLike[str]):
        """Read-only preflight used by the UI before asking to overwrite data.

        This verifies ZIP CRCs, staged SQLite integrity/schema, every referenced
        original photo, and returns a compact preview. It never changes live data.
        """
        archive_path = Path(backup_path)
        if not archive_path.is_file():
            raise FileNotFoundError(f"备份文件不存在：{archive_path}")
        with zipfile.ZipFile(archive_path, "r") as archive:
            names, unpacked_bytes = self._safe_archive_names(archive)
            infos = {info.filename: info for info in archive.infolist() if not info.is_dir()}
            corrupt_name = archive.testzip()
            if corrupt_name:
                raise ValueError(f"备份文件校验失败，损坏条目：{corrupt_name}")
            db_info = next(info for info in archive.infolist() if info.filename == "weight_tracker.db")
            free_bytes = shutil.disk_usage(self.base_dir).free
            if int(db_info.file_size) + 4 * 1024 * 1024 > free_bytes:
                raise OSError("可用空间不足，无法安全检查备份数据库。请释放空间后重试。")
            temp_db = self.base_dir / f".backup_inspect_{uuid.uuid4().hex}.db"
            try:
                with archive.open("weight_tracker.db", "r") as source, open(temp_db, "wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                self._migrate_backup_database(temp_db)
                check = sqlite3.connect(str(temp_db))
                check.row_factory = sqlite3.Row
                try:
                    integrity = check.execute("PRAGMA integrity_check").fetchone()
                    if not integrity or integrity[0] != "ok":
                        raise ValueError("备份数据库完整性检查失败")
                    photo_rows = check.execute(
                        "SELECT id, photo_date, path, thumbnail_path FROM body_photos ORDER BY photo_date, id"
                    ).fetchall()
                    missing = []
                    for row in photo_rows:
                        original = self._photo_archive_path(row["path"])
                        if original not in names:
                            missing.append(original)
                        elif int(infos[original].file_size) <= 0:
                            raise ValueError(f"备份中的照片原图为空文件：{original}")
                        thumb_value = row["thumbnail_path"]
                        if thumb_value:
                            thumb = Path(str(thumb_value))
                            if thumb.is_absolute() or ".." in thumb.parts:
                                raise ValueError("备份数据库中包含不安全的缩略图路径")
                            thumb_name = thumb.as_posix()
                            if not thumb_name.startswith("body_photo_thumbnails/"):
                                raise ValueError("备份数据库中的缩略图路径不在缩略图目录中")
                            # Missing thumbnails are recoverable and are recreated
                            # from the verified original after restore.
                    if missing:
                        raise ValueError(f"备份缺少 {len(missing)} 张照片原图，示例：{missing[0]}")
                    fk_errors = check.execute("PRAGMA foreign_key_check").fetchall()
                    if fk_errors:
                        raise ValueError("备份数据库存在未满足的外键关系")
                    record_summary = check.execute(
                        "SELECT COUNT(*) AS count, MIN(recorded_at) AS first, MAX(recorded_at) AS last FROM records"
                    ).fetchone()
                    workout_count = check.execute(
                        "SELECT COUNT(*) FROM daily_activity WHERE workout != 0"
                    ).fetchone()[0]
                    settings_count = check.execute("SELECT COUNT(*) FROM settings").fetchone()[0]
                    food_count = check.execute("SELECT COUNT(*) FROM food_logs").fetchone()[0]
                    strength_count = check.execute("SELECT COUNT(*) FROM strength_logs").fetchone()[0]
                    measurement_count = check.execute("SELECT COUNT(*) FROM body_measurements").fetchone()[0]
                    summary = {
                        "path": str(archive_path),
                        "archive_bytes": archive_path.stat().st_size,
                        "unpacked_bytes": unpacked_bytes,
                        "records": int(record_summary["count"]),
                        "first_record": record_summary["first"],
                        "last_record": record_summary["last"],
                        "photos": len(photo_rows),
                        "workout_days": int(workout_count),
                        "food_logs": int(food_count),
                        "strength_logs": int(strength_count),
                        "body_measurements": int(measurement_count),
                        "settings": int(settings_count),
                    }
                finally:
                    check.close()
                summary.update(self._restore_space_estimate(unpacked_bytes))
                return summary
            finally:
                try:
                    temp_db.unlink(missing_ok=True)
                except OSError:
                    pass

    def create_full_backup(self):
        """Create a consistent ZIP snapshot with DB, originals, and thumbnails.

        Intended to be called by the background-task runner from UI actions.
        The database is snapshotted via SQLite's backup API; partially imported
        `.part` files are deliberately excluded.
        """
        if not self.db_path.exists():
            return None
        self._validate_live_originals()
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
            with zipfile.ZipFile(dst, "r") as check_zip:
                names, _ = self._safe_archive_names(check_zip)
                damaged = check_zip.testzip()
                if damaged:
                    raise ValueError(f"新建备份校验失败：{damaged}")
                # Verify every indexed original is present in the final archive.
                snapshot = self.backup_dir / f".backup_check_{stamp}.db.part"
                try:
                    with check_zip.open("weight_tracker.db", "r") as db_stream, open(snapshot, "wb") as out:
                        shutil.copyfileobj(db_stream, out, length=1024 * 1024)
                    db_check = sqlite3.connect(str(snapshot))
                    try:
                        photo_rows = db_check.execute("SELECT id, path FROM body_photos").fetchall()
                        for _photo_id, photo_path in photo_rows:
                            archived = self._photo_archive_path(photo_path)
                            if archived not in names:
                                raise ValueError(f"完整备份缺少照片原图：{archived}")
                    finally:
                        db_check.close()
                finally:
                    snapshot.unlink(missing_ok=True)
        except Exception:
            try:
                dst.unlink(missing_ok=True)
            except OSError:
                pass
            raise
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
        # Verify CRC/path layout and conservatively estimate peak temporary space.
        with zipfile.ZipFile(archive_path, "r") as archive_check:
            _, required_bytes = self._safe_archive_names(archive_check)
            damaged = archive_check.testzip()
            if damaged:
                raise ValueError(f"备份文件校验失败，损坏条目：{damaged}")
        space = self._restore_space_estimate(required_bytes)
        free_bytes = space["free_bytes"]
        estimated_peak = space["estimated_peak_bytes"]
        if not space["space_sufficient"]:
            raise OSError(
                f"可用存储空间不足：备份展开约需 {required_bytes / (1024 * 1024):.1f} MB；"
                f"考虑恢复前保护备份和临时数据库，建议至少预留 "
                f"{estimated_peak / (1024 * 1024):.1f} MB，当前可用 "
                f"{free_bytes / (1024 * 1024):.1f} MB。"
            )

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
                archive_sizes = {info.filename: int(info.file_size) for info in infos if not info.is_dir()}
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

            # Migrate and validate a staged copy before touching live data.
            self._migrate_backup_database(stage_db)
            check = sqlite3.connect(str(stage_db))
            try:
                integrity = check.execute("PRAGMA integrity_check").fetchone()
                if not integrity or integrity[0] != "ok":
                    raise ValueError("备份数据库完整性检查失败")
                for row in check.execute("SELECT path, thumbnail_path FROM body_photos").fetchall():
                    if row[0]:
                        archive_name = self._photo_archive_path(row[0])
                        if archive_name not in names:
                            raise ValueError(f"备份缺少照片原图：{archive_name}")
                        # Database references to a zero-byte “original” are not recoverable.
                        if archive_sizes.get(archive_name, 0) <= 0:
                            raise ValueError(f"备份中的照片原图为空文件：{archive_name}")
                    if row[1]:
                        relative = Path(str(row[1]))
                        if relative.is_absolute() or ".." in relative.parts:
                            raise ValueError("备份数据库中包含不安全的缩略图路径")
                        thumbnail_name = relative.as_posix()
                        if not thumbnail_name.startswith("body_photo_thumbnails/"):
                            raise ValueError("备份数据库中的缩略图路径不在缩略图目录中")
                        # Older full backups may omit thumbnails; the app can regenerate
                        # them from the validated original after restore.
                fk_errors = check.execute("PRAGMA foreign_key_check").fetchall()
                if fk_errors:
                    raise ValueError("备份数据库存在未满足的外键关系")
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
                    "photos": self.count_body_photos(),
                    "food_logs": len(self.list_food_logs()),
                    "strength_logs": len(self.list_strength_logs()),
                    "body_measurements": len(self.list_body_measurements())}
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
        if weight != weight or weight in (float("inf"), float("-inf")):
            raise ValueError("体重必须是有限数字")
        if not (Storage.MIN_WEIGHT_JIN <= weight <= Storage.MAX_WEIGHT_JIN):
            raise ValueError(
                f"体重应在 {Storage.MIN_WEIGHT_JIN:g}–{Storage.MAX_WEIGHT_JIN:g} 斤之间；"
                "请检查是否误用了 kg 或输错小数点。"
            )
        return weight

    @staticmethod
    def validate_height_cm(value: float) -> float:
        height = float(value)
        if height != height or height in (float("inf"), float("-inf")):
            raise ValueError("身高必须是有限数字")
        if not (Storage.MIN_HEIGHT_CM <= height <= Storage.MAX_HEIGHT_CM):
            raise ValueError(
                f"身高应在 {Storage.MIN_HEIGHT_CM:g}–{Storage.MAX_HEIGHT_CM:g} cm 之间，"
                "请检查输入单位。"
            )
        return height

    @classmethod
    def validate_target_weight(cls, value: float) -> float:
        return cls._validate_weight(value)

    @classmethod
    def normalize_recorded_at(cls, value) -> datetime:
        """Parse a timestamp and normalize aware values to device-local naive time.

        The database historically stores local, timezone-naive timestamps. CSVs
        may contain ISO-8601 `Z`/offset forms; normalizing before persistence
        prevents lexicographic ordering and duplicate checks from diverging.
        """
        if isinstance(value, datetime):
            parsed = value
        else:
            raw = str(value).strip()
            if not raw:
                raise ValueError("日期时间不能为空")
            if raw.endswith(("Z", "z")):
                raw = raw[:-1] + "+00:00"
            try:
                # Preferred format: ISO-8601, including optional timezone offsets.
                parsed = datetime.fromisoformat(raw)
            except ValueError as iso_error:
                # Some spreadsheet apps export unambiguous year-first dates with
                # slashes or Chinese date markers. Support these explicitly; do
                # not guess ambiguous formats such as 03/04/2026.
                parsed = None
                for fmt in (
                    "%Y/%m/%d %H:%M:%S",
                    "%Y/%m/%d %H:%M",
                    "%Y/%m/%d",
                    "%Y年%m月%d日 %H:%M:%S",
                    "%Y年%m月%d日 %H:%M",
                    "%Y年%m月%d日",
                ):
                    try:
                        parsed = datetime.strptime(raw, fmt)
                        break
                    except ValueError:
                        continue
                if parsed is None:
                    raise ValueError(
                        f"日期时间格式不支持：{raw}。请使用 YYYY-MM-DD HH:MM[:SS]、"
                        "ISO 8601（可带时区）、YYYY/MM/DD 或 YYYY年M月D日。"
                    ) from iso_error
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        # App precision is minutes/seconds; canonical precision makes export,
        # import and duplicate matching deterministic.
        return parsed.replace(microsecond=0)

    @classmethod
    def validate_recorded_at(cls, value) -> datetime:
        parsed = cls.normalize_recorded_at(value)
        if parsed > datetime.now() + cls.FUTURE_TIME_GRACE:
            raise ValueError("记录时间不能晚于当前时间，请检查日期和时间。")
        return parsed

    def list_records(self, start: Optional[datetime] = None, end: Optional[datetime] = None):
        sql = "SELECT id, weight, recorded_at, note FROM records"
        args = []
        if start is not None and end is not None:
            sql += " WHERE recorded_at BETWEEN ? AND ?"
            args.extend([start.isoformat(sep=" "), end.isoformat(sep=" ")])
        sql += " ORDER BY recorded_at ASC, id ASC"
        with self._connect() as con:
            return [dict(r) for r in con.execute(sql, args).fetchall()]

    def latest_record(self):
        """Read only the most recent row for the quick-entry controls."""
        with self._connect() as con:
            row = con.execute(
                "SELECT id, weight, recorded_at, note FROM records "
                "ORDER BY recorded_at DESC, id DESC LIMIT 1"
            ).fetchone()
            return None if row is None else dict(row)

    def insert(self, weight: float, recorded_at: datetime, note: Optional[str] = None):
        weight = self._validate_weight(weight)
        recorded_at = self.validate_recorded_at(recorded_at)
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
        recorded_at = self.validate_recorded_at(recorded_at)
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

    def get_settings(self):
        """Read all low-volume preferences in one DB round trip."""
        with self._connect() as con:
            rows = con.execute("SELECT key, value FROM settings").fetchall()
            return {str(row["key"]): row["value"] for row in rows}

    def set_setting(self, key: str, value):
        if key == "height_cm" and value not in (None, ""):
            value = format(self.validate_height_cm(value), ".15g")
        elif key == "target_weight" and value not in (None, ""):
            value = format(self.validate_target_weight(value), ".15g")
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

    # ------------------------------------------------------------------
    # Nutrition, structured training and body measurements (all local).
    # Stored body weights remain in 斤 for backwards compatibility; gym load
    # is stored in kg, body measurements in cm, energy in kcal.
    # ------------------------------------------------------------------
    @staticmethod
    def _finite_nonnegative(value, label, maximum=100000.0):
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}必须是数字") from exc
        if number != number or number in (float("inf"), float("-inf")) or not 0 <= number <= maximum:
            raise ValueError(f"{label}应在 0–{maximum:g} 范围内")
        return number

    def upsert_food(self, name, calories_per_100g, protein_per_100g=0,
                    carbs_per_100g=0, fat_per_100g=0):
        name = str(name or "").strip()
        if not name or len(name) > 120:
            raise ValueError("食物名称不能为空，且不能超过 120 个字符")
        kcal = self._finite_nonnegative(calories_per_100g, "每 100 克热量", 1000)
        protein = self._finite_nonnegative(protein_per_100g, "蛋白质", 100)
        carbs = self._finite_nonnegative(carbs_per_100g, "碳水", 100)
        fat = self._finite_nonnegative(fat_per_100g, "脂肪", 100)
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        with self._connect() as con:
            con.execute(
                "INSERT INTO foods(name, calories_per_100g, protein_per_100g, carbs_per_100g, fat_per_100g, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
                "calories_per_100g=excluded.calories_per_100g, protein_per_100g=excluded.protein_per_100g, "
                "carbs_per_100g=excluded.carbs_per_100g, fat_per_100g=excluded.fat_per_100g",
                (name, kcal, protein, carbs, fat, now),
            )
            row = con.execute("SELECT id FROM foods WHERE name=? COLLATE NOCASE", (name,)).fetchone()
            return int(row["id"])

    def list_foods(self, limit=200):
        limit = max(1, min(int(limit), 1000))
        with self._connect() as con:
            return [dict(row) for row in con.execute(
                "SELECT id, name, calories_per_100g, protein_per_100g, carbs_per_100g, fat_per_100g, created_at "
                "FROM foods ORDER BY name COLLATE NOCASE LIMIT ?", (limit,)
            ).fetchall()]

    def add_food_log(self, logged_at, meal_type, food_name, amount_g, calories_per_100g,
                     protein_per_100g=0, carbs_per_100g=0, fat_per_100g=0):
        stamp = self.validate_recorded_at(logged_at).isoformat(sep=" ", timespec="seconds")
        meal = str(meal_type or "").strip()
        if meal not in {"早餐", "午餐", "晚餐", "加餐"}:
            raise ValueError("请选择早餐、午餐、晚餐或加餐")
        name = str(food_name or "").strip()
        if not name or len(name) > 120:
            raise ValueError("食物名称不能为空，且不能超过 120 个字符")
        amount = self._finite_nonnegative(amount_g, "食用份量", 10000)
        if amount <= 0:
            raise ValueError("食用份量必须大于 0 克")
        kcal100 = self._finite_nonnegative(calories_per_100g, "每 100 克热量", 1000)
        protein100 = self._finite_nonnegative(protein_per_100g, "每 100 克蛋白质", 100)
        carbs100 = self._finite_nonnegative(carbs_per_100g, "每 100 克碳水", 100)
        fat100 = self._finite_nonnegative(fat_per_100g, "每 100 克脂肪", 100)
        food_id = self.upsert_food(name, kcal100, protein100, carbs100, fat100)
        factor = amount / 100.0
        totals = (round(kcal100 * factor, 2), round(protein100 * factor, 2),
                  round(carbs100 * factor, 2), round(fat100 * factor, 2))
        created = datetime.now().isoformat(sep=" ", timespec="seconds")
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO food_logs(logged_at, meal_type, food_name, amount_g, calories_kcal, protein_g, carbs_g, fat_g, food_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (stamp, meal, name, amount, *totals, food_id, created),
            )
            log_id = int(cur.lastrowid)
        self.schedule_backup()
        return log_id

    def list_food_logs(self, start_date=None, end_date=None, limit=5000):
        limit = max(1, min(int(limit), 20000))
        sql = ("SELECT id, logged_at, meal_type, food_name, amount_g, calories_kcal, protein_g, carbs_g, fat_g, food_id "
               "FROM food_logs")
        args = []
        if start_date and end_date:
            sql += " WHERE logged_at >= ? AND logged_at <= ?"
            args.extend([str(start_date) + " 00:00:00", str(end_date) + " 23:59:59"])
        sql += " ORDER BY logged_at DESC, id DESC LIMIT ?"
        args.append(limit)
        with self._connect() as con:
            return [dict(row) for row in con.execute(sql, args).fetchall()]

    def delete_food_log(self, log_id):
        with self._connect() as con:
            row = con.execute("SELECT * FROM food_logs WHERE id=?", (int(log_id),)).fetchone()
            if row is None:
                raise KeyError("饮食记录不存在")
            con.execute("DELETE FROM food_logs WHERE id=?", (int(log_id),))
            deleted = dict(row)
        self.schedule_backup()
        return deleted

    def update_food_log(self, log_id, logged_at, meal_type, food_name, amount_g, calories_per_100g,
                        protein_per_100g=0, carbs_per_100g=0, fat_per_100g=0):
        stamp = self.validate_recorded_at(logged_at).isoformat(sep=" ", timespec="seconds")
        meal = str(meal_type or "").strip()
        if meal not in {"早餐", "午餐", "晚餐", "加餐"}:
            raise ValueError("请选择早餐、午餐、晚餐或加餐")
        name = str(food_name or "").strip()
        if not name or len(name) > 120:
            raise ValueError("食物名称不能为空，且不能超过 120 个字符")
        amount = self._finite_nonnegative(amount_g, "食用份量", 10000)
        if amount <= 0:
            raise ValueError("食用份量必须大于 0 克")
        kcal100 = self._finite_nonnegative(calories_per_100g, "每 100 克热量", 1000)
        protein100 = self._finite_nonnegative(protein_per_100g, "每 100 克蛋白质", 100)
        carbs100 = self._finite_nonnegative(carbs_per_100g, "每 100 克碳水", 100)
        fat100 = self._finite_nonnegative(fat_per_100g, "每 100 克脂肪", 100)
        food_id = self.upsert_food(name, kcal100, protein100, carbs100, fat100)
        factor = amount / 100.0
        totals = (round(kcal100 * factor, 2), round(protein100 * factor, 2),
                  round(carbs100 * factor, 2), round(fat100 * factor, 2))
        with self._connect() as con:
            cur = con.execute(
                "UPDATE food_logs SET logged_at=?, meal_type=?, food_name=?, amount_g=?, calories_kcal=?, "
                "protein_g=?, carbs_g=?, fat_g=?, food_id=? WHERE id=?",
                (stamp, meal, name, amount, *totals, food_id, int(log_id)),
            )
            if cur.rowcount == 0:
                raise KeyError("饮食记录不存在")
        self.schedule_backup()

    def restore_food_log(self, row):
        """Restore an item removed from the UI's short-lived undo action."""
        keys = ("logged_at", "meal_type", "food_name", "amount_g", "calories_kcal", "protein_g",
                "carbs_g", "fat_g", "food_id", "created_at")
        values = [row.get(key) for key in keys]
        if not values[9]:
            values[9] = datetime.now().isoformat(sep=" ", timespec="seconds")
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO food_logs(logged_at, meal_type, food_name, amount_g, calories_kcal, protein_g, carbs_g, fat_g, food_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values,
            )
            new_id = int(cur.lastrowid)
        self.schedule_backup()
        return new_id

    def add_strength_log(self, performed_at, exercise_name, sets=0, reps=0, load_kg=0,
                         duration_minutes=0, note=None):
        stamp = self.validate_recorded_at(performed_at).isoformat(sep=" ", timespec="seconds")
        name = str(exercise_name or "").strip()
        if not name or len(name) > 120:
            raise ValueError("训练动作/项目名称不能为空，且不能超过 120 个字符")
        try:
            set_count, rep_count = int(sets or 0), int(reps or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("组数和次数必须是整数") from exc
        if not (0 <= set_count <= 100 and 0 <= rep_count <= 1000):
            raise ValueError("组数应为 0–100，次数应为 0–1000")
        load = self._finite_nonnegative(load_kg, "训练重量(kg)", 2000)
        duration = self._finite_nonnegative(duration_minutes, "训练时长(分钟)", 1440)
        if set_count == 0 and rep_count == 0 and duration <= 0:
            raise ValueError("请至少填写组数/次数，或填写训练时长")
        note_text = str(note or "").strip()[:500] or None
        created = datetime.now().isoformat(sep=" ", timespec="seconds")
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO strength_logs(performed_at, exercise_name, sets, reps, load_kg, duration_minutes, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (stamp, name, set_count, rep_count, load, duration, note_text, created),
            )
            log_id = int(cur.lastrowid)
            day = stamp[:10]
            con.execute("INSERT INTO daily_activity(date, workout) VALUES (?, 1) "
                        "ON CONFLICT(date) DO UPDATE SET workout=1", (day,))
        self.schedule_backup()
        return log_id

    def list_strength_logs(self, start_date=None, end_date=None, limit=5000):
        limit = max(1, min(int(limit), 20000))
        sql = ("SELECT id, performed_at, exercise_name, sets, reps, load_kg, duration_minutes, note FROM strength_logs")
        args = []
        if start_date and end_date:
            sql += " WHERE performed_at >= ? AND performed_at <= ?"
            args.extend([str(start_date) + " 00:00:00", str(end_date) + " 23:59:59"])
        sql += " ORDER BY performed_at DESC, id DESC LIMIT ?"
        args.append(limit)
        with self._connect() as con:
            return [dict(row) for row in con.execute(sql, args).fetchall()]

    def delete_strength_log(self, log_id):
        with self._connect() as con:
            row = con.execute("SELECT * FROM strength_logs WHERE id=?", (int(log_id),)).fetchone()
            if row is None:
                raise KeyError("训练记录不存在")
            con.execute("DELETE FROM strength_logs WHERE id=?", (int(log_id),))
            deleted = dict(row)
        self.schedule_backup()
        return deleted

    def update_strength_log(self, log_id, performed_at, exercise_name, sets=0, reps=0, load_kg=0,
                            duration_minutes=0, note=None):
        stamp = self.validate_recorded_at(performed_at).isoformat(sep=" ", timespec="seconds")
        name = str(exercise_name or "").strip()
        if not name or len(name) > 120:
            raise ValueError("训练动作/项目名称不能为空，且不能超过 120 个字符")
        try:
            set_count, rep_count = int(sets or 0), int(reps or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("组数和次数必须是整数") from exc
        if not (0 <= set_count <= 100 and 0 <= rep_count <= 1000):
            raise ValueError("组数应为 0–100，次数应为 0–1000")
        load = self._finite_nonnegative(load_kg, "训练重量(kg)", 2000)
        duration = self._finite_nonnegative(duration_minutes, "训练时长(分钟)", 1440)
        if set_count == 0 and rep_count == 0 and duration <= 0:
            raise ValueError("请至少填写组数/次数，或填写训练时长")
        note_text = str(note or "").strip()[:500] or None
        with self._connect() as con:
            cur = con.execute(
                "UPDATE strength_logs SET performed_at=?, exercise_name=?, sets=?, reps=?, load_kg=?, "
                "duration_minutes=?, note=? WHERE id=?",
                (stamp, name, set_count, rep_count, load, duration, note_text, int(log_id)),
            )
            if cur.rowcount == 0:
                raise KeyError("训练记录不存在")
            con.execute("INSERT INTO daily_activity(date, workout) VALUES (?, 1) "
                        "ON CONFLICT(date) DO UPDATE SET workout=1", (stamp[:10],))
        self.schedule_backup()

    def restore_strength_log(self, row):
        keys = ("performed_at", "exercise_name", "sets", "reps", "load_kg", "duration_minutes", "note", "created_at")
        values = [row.get(key) for key in keys]
        if not values[7]:
            values[7] = datetime.now().isoformat(sep=" ", timespec="seconds")
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO strength_logs(performed_at, exercise_name, sets, reps, load_kg, duration_minutes, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values,
            )
            new_id = int(cur.lastrowid)
            con.execute("INSERT INTO daily_activity(date, workout) VALUES (?, 1) "
                        "ON CONFLICT(date) DO UPDATE SET workout=1", (str(values[0])[:10],))
        self.schedule_backup()
        return new_id

    @staticmethod
    def _optional_measurement(value, label, low, high):
        if value is None or str(value).strip() == "":
            return None
        number = Storage._finite_nonnegative(value, label, high)
        if number < low:
            raise ValueError(f"{label}应在 {low:g}–{high:g} 范围内")
        return number

    def add_body_measurement(self, measured_at, waist_cm=None, hip_cm=None, chest_cm=None,
                             body_fat_pct=None, note=None):
        raw = str(measured_at or "").strip()
        try:
            day = datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("测量日期请使用 YYYY-MM-DD 格式") from exc
        if day > datetime.now().date():
            raise ValueError("测量日期不能晚于今天")
        waist = self._optional_measurement(waist_cm, "腰围(cm)", 20, 250)
        hip = self._optional_measurement(hip_cm, "臀围(cm)", 20, 300)
        chest = self._optional_measurement(chest_cm, "胸围(cm)", 20, 300)
        fat = self._optional_measurement(body_fat_pct, "体脂率(%)", 1, 75)
        if all(value is None for value in (waist, hip, chest, fat)):
            raise ValueError("腰围、臀围、胸围或体脂率至少填写一项")
        note_text = str(note or "").strip()[:500] or None
        created = datetime.now().isoformat(sep=" ", timespec="seconds")
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO body_measurements(measured_at, waist_cm, hip_cm, chest_cm, body_fat_pct, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (day.isoformat(), waist, hip, chest, fat, note_text, created),
            )
            measurement_id = int(cur.lastrowid)
        self.schedule_backup()
        return measurement_id

    def list_body_measurements(self, limit=2000, start_date=None, end_date=None):
        limit = max(1, min(int(limit), 10000))
        sql = ("SELECT id, measured_at, waist_cm, hip_cm, chest_cm, body_fat_pct, note, created_at "
               "FROM body_measurements")
        args = []
        if start_date and end_date:
            sql += " WHERE measured_at BETWEEN ? AND ?"
            args.extend([str(start_date), str(end_date)])
        sql += " ORDER BY measured_at DESC, id DESC LIMIT ?"
        args.append(limit)
        with self._connect() as con:
            return [dict(row) for row in con.execute(sql, args).fetchall()]

    def get_weight_progress_summary(self):
        """Return weight-record count and endpoints without loading all history."""
        with self._connect() as con:
            count = int(con.execute("SELECT COUNT(*) FROM records").fetchone()[0])
            first = con.execute(
                "SELECT id, weight, recorded_at FROM records ORDER BY recorded_at ASC, id ASC LIMIT 1"
            ).fetchone()
            latest = con.execute(
                "SELECT id, weight, recorded_at FROM records ORDER BY recorded_at DESC, id DESC LIMIT 1"
            ).fetchone()
        return {
            "count": count,
            "first_weight_jin": float(first["weight"]) if first else None,
            "current_weight_jin": float(latest["weight"]) if latest else None,
            "latest_recorded_at": str(latest["recorded_at"]) if latest else None,
        }

    def update_body_measurement(self, measurement_id, measured_at, waist_cm=None, hip_cm=None, chest_cm=None,
                                body_fat_pct=None, note=None):
        raw = str(measured_at or "").strip()
        try:
            day = datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("测量日期请使用 YYYY-MM-DD 格式") from exc
        if day > datetime.now().date():
            raise ValueError("测量日期不能晚于今天")
        waist = self._optional_measurement(waist_cm, "腰围(cm)", 20, 250)
        hip = self._optional_measurement(hip_cm, "臀围(cm)", 20, 300)
        chest = self._optional_measurement(chest_cm, "胸围(cm)", 20, 300)
        fat = self._optional_measurement(body_fat_pct, "体脂率(%)", 1, 75)
        if all(value is None for value in (waist, hip, chest, fat)):
            raise ValueError("腰围、臀围、胸围或体脂率至少填写一项")
        note_text = str(note or "").strip()[:500] or None
        with self._connect() as con:
            cur = con.execute(
                "UPDATE body_measurements SET measured_at=?, waist_cm=?, hip_cm=?, chest_cm=?, body_fat_pct=?, note=? WHERE id=?",
                (day.isoformat(), waist, hip, chest, fat, note_text, int(measurement_id)),
            )
            if cur.rowcount == 0:
                raise KeyError("身体围度记录不存在")
        self.schedule_backup()

    def restore_body_measurement(self, row):
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO body_measurements(measured_at, waist_cm, hip_cm, chest_cm, body_fat_pct, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row.get("measured_at"), row.get("waist_cm"), row.get("hip_cm"), row.get("chest_cm"),
                 row.get("body_fat_pct"), row.get("note"), row.get("created_at") or datetime.now().isoformat(sep=" ", timespec="seconds")),
            )
            new_id = int(cur.lastrowid)
        self.schedule_backup()
        return new_id

    def delete_body_measurement(self, measurement_id):
        with self._connect() as con:
            row = con.execute("SELECT * FROM body_measurements WHERE id=?", (int(measurement_id),)).fetchone()
            if row is None:
                raise KeyError("身体围度记录不存在")
            con.execute("DELETE FROM body_measurements WHERE id=?", (int(measurement_id),))
            result = dict(row)
        self.schedule_backup()
        return result

    def update_body_photo_date(self, photo_id, photo_date):
        raw = str(photo_date or "").strip()
        try:
            day = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("照片日期请使用 YYYY-MM-DD 格式") from exc
        if day > datetime.now().date():
            raise ValueError("照片日期不能晚于今天")
        with self._connect() as con:
            cur = con.execute("UPDATE body_photos SET photo_date=? WHERE id=?", (day.isoformat(), int(photo_id)))
            if cur.rowcount == 0:
                raise KeyError("照片记录不存在")
        self.schedule_backup()

    def get_seven_day_weight_average(self, reference_date=None):
        end_day = reference_date or datetime.now().date()
        start_day = end_day - timedelta(days=6)
        rows = self.list_records(datetime.combine(start_day, datetime.min.time()),
                                 datetime.combine(end_day, datetime.max.time()))
        if not rows:
            return {"average_jin": None, "days": 0, "records": 0, "start": start_day.isoformat(), "end": end_day.isoformat()}
        by_day = {}
        for row in rows:
            by_day.setdefault(str(row["recorded_at"])[:10], []).append(float(row["weight"]))
        daily_means = [sum(values) / len(values) for values in by_day.values()]
        return {"average_jin": sum(daily_means) / len(daily_means), "days": len(daily_means),
                "records": len(rows), "start": start_day.isoformat(), "end": end_day.isoformat()}

    def build_health_report(self, period="week", reference_date=None):
        """Build a reproducible local weekly or monthly health summary."""
        today = reference_date or datetime.now().date()
        if period == "month":
            start_day = today.replace(day=1)
            period_title = f"{today.year}年{today.month}月"
        else:
            start_day = today - timedelta(days=today.weekday())
            period_title = f"{start_day.isoformat()} 至 {today.isoformat()} 周报"
        start_text, end_text = start_day.isoformat(), today.isoformat()
        start_dt = datetime.combine(start_day, datetime.min.time())
        end_dt = datetime.combine(today, datetime.max.time())
        weight_rows = self.list_records(start_dt, end_dt)
        by_day = {}
        for row in weight_rows:
            by_day.setdefault(str(row["recorded_at"])[:10], []).append(float(row["weight"]))
        daily = [(day, sum(values) / len(values)) for day, values in sorted(by_day.items())]
        food_rows = self.list_food_logs(start_text, end_text)
        strength_rows = self.list_strength_logs(start_text, end_text)
        workouts = self.list_workouts_between(start_text, end_text)
        measurements = [row for row in self.list_body_measurements()
                        if start_text <= str(row["measured_at"]) <= end_text]
        photos = self.count_body_photos_for_period(start_text, end_text)
        calorie_total = sum(float(row["calories_kcal"]) for row in food_rows)
        protein_total = sum(float(row["protein_g"]) for row in food_rows)
        active_days = len({str(row["logged_at"])[:10] for row in food_rows})
        strength_days = len({str(row["performed_at"])[:10] for row in strength_rows})
        exercise_minutes = sum(float(row["duration_minutes"]) for row in strength_rows)
        records_by_day = len(daily)
        seven_day = self.get_seven_day_weight_average(today)
        all_rows = self.list_records()
        start_weight = float(all_rows[0]["weight"]) if all_rows else None
        latest = self.latest_record()
        current_weight = float(latest["weight"]) if latest else None
        target = self.get_setting("target_weight")
        target = float(target) if target else None
        progress = None
        if start_weight is not None and current_weight is not None and target is not None and abs(target - start_weight) > 1e-8:
            progress = (current_weight - start_weight) / (target - start_weight) * 100.0
        week_groups = {}
        for day_text, average in daily:
            day = datetime.strptime(day_text, "%Y-%m-%d").date()
            if period == "month":
                key = f"{day.isocalendar().year}-W{day.isocalendar().week:02d}"
            else:
                key = day_text
            week_groups.setdefault(key, []).append(average)
        grouped_trend = [(key, sum(values) / len(values)) for key, values in sorted(week_groups.items())]
        return {
            "period": period, "title": period_title, "start_date": start_text, "end_date": end_text,
            "weight_count": len(weight_rows), "weight_average_jin": (sum(float(r["weight"]) for r in weight_rows) / len(weight_rows)) if weight_rows else None,
            "daily_average_change_jin": (daily[-1][1] - daily[0][1]) if len(daily) >= 2 else None,
            "daily_trend": daily, "grouped_trend": grouped_trend,
            "seven_day_average_jin": seven_day["average_jin"], "seven_day_days": seven_day["days"],
            "calories_total": calorie_total, "calories_logged_days": active_days,
            "calories_daily_average": (calorie_total / active_days) if active_days else None,
            "protein_total_g": protein_total, "food_entries": len(food_rows),
            "training_entries": len(strength_rows),
            "training_days": len({str(row["performed_at"])[:10] for row in strength_rows}),
            "workout_days": sum(1 for value in workouts.values() if value),
            "training_minutes": exercise_minutes, "photo_count": photos,
            "latest_measurement": measurements[0] if measurements else None,
            "start_weight_jin": start_weight, "current_weight_jin": current_weight,
            "target_weight_jin": target, "goal_progress_percent": progress,
        }

    def count_body_photos_for_period(self, start_date, end_date):
        with self._connect() as con:
            row = con.execute(
                "SELECT COUNT(*) AS total FROM body_photos WHERE photo_date BETWEEN ? AND ?",
                (str(start_date), str(end_date)),
            ).fetchone()
            return int(row["total"])

    def create_data_export_archive(self):
        """Create a portable ZIP of CSV exports and all readable original photos.

        This is an interchange/reporting bundle, distinct from the full backup
        format: it has user-facing CSV files plus a photo index and originals.
        Use full backup/restore for in-app recovery.
        """
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dest = self.backup_dir / f"weight_tracker_data_export_{stamp}.zip"
        # Export currently stages CSVs and original images before creating the ZIP.
        # Preflight an intentionally conservative peak-space estimate so an export
        # cannot silently exhaust app storage on a phone with many large photos.
        photo_rows = self.list_body_photos()
        original_photo_bytes = 0
        for row in photo_rows:
            original = self.body_photo_path(row)
            if not original.is_file() or original.stat().st_size <= 0:
                raise FileNotFoundError(f"照片 #{row['id']} 的原图缺失，无法完整导出所有数据")
            original_photo_bytes += int(original.stat().st_size)
        database_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        estimated_peak = 2 * original_photo_bytes + database_bytes + 8 * 1024 * 1024
        free_bytes = shutil.disk_usage(self.backup_dir).free
        if free_bytes < estimated_peak:
            raise OSError(
                f"应用存储空间不足，预计至少需要 {estimated_peak / (1024 * 1024):.1f} MB，"
                f"当前可用 {free_bytes / (1024 * 1024):.1f} MB。请先释放空间后重试。"
            )
        work = self.backup_dir / f".data_export_{uuid.uuid4().hex}"
        work.mkdir(parents=True, exist_ok=False)
        try:
            with self._connect() as con:
                tables = {
                    "weight_records.csv": ("SELECT id, weight AS weight_jin, recorded_at, note FROM records ORDER BY recorded_at, id",),
                    "food_logs.csv": ("SELECT id, logged_at, meal_type, food_name, amount_g, calories_kcal, protein_g, carbs_g, fat_g FROM food_logs ORDER BY logged_at, id",),
                    "food_catalog.csv": ("SELECT name, calories_per_100g, protein_per_100g, carbs_per_100g, fat_per_100g, created_at FROM foods ORDER BY name COLLATE NOCASE",),
                    "strength_logs.csv": ("SELECT id, performed_at, exercise_name, sets, reps, load_kg, duration_minutes, note FROM strength_logs ORDER BY performed_at, id",),
                    "body_measurements.csv": ("SELECT id, measured_at, waist_cm, hip_cm, chest_cm, body_fat_pct, note FROM body_measurements ORDER BY measured_at, id",),
                    "daily_activity.csv": ("SELECT date, workout FROM daily_activity ORDER BY date",),
                    "settings.csv": ("SELECT key, value FROM settings ORDER BY key",),
                    "recycle_bin.csv": ("SELECT id, original_id, weight AS weight_jin, recorded_at, note, deleted_at FROM recycle_bin ORDER BY deleted_at, id",),
                }
                for filename, (query,) in tables.items():
                    target = work / filename
                    with target.open("w", encoding="utf-8-sig", newline="") as stream:
                        writer = csv.writer(stream)
                        rows = con.execute(query).fetchall()
                        if rows:
                            writer.writerow(rows[0].keys())
                            writer.writerows([tuple(row) for row in rows])
                        else:
                            columns = [col[1] for col in con.execute(
                                f"PRAGMA table_info('{filename[:-4].replace('-', '_')}')"
                            ).fetchall()]
                            if not columns:
                                # Explicit headers for empty tables.
                                columns = {
                                    "weight_records.csv": ["id", "weight_jin", "recorded_at", "note"],
                                    "food_logs.csv": ["id", "logged_at", "meal_type", "food_name", "amount_g", "calories_kcal", "protein_g", "carbs_g", "fat_g"],
                                    "food_catalog.csv": ["name", "calories_per_100g", "protein_per_100g", "carbs_per_100g", "fat_per_100g", "created_at"],
                                    "strength_logs.csv": ["id", "performed_at", "exercise_name", "sets", "reps", "load_kg", "duration_minutes", "note"],
                                    "body_measurements.csv": ["id", "measured_at", "waist_cm", "hip_cm", "chest_cm", "body_fat_pct", "note"],
                                    "daily_activity.csv": ["date", "workout"], "settings.csv": ["key", "value"],
                                    "recycle_bin.csv": ["id", "original_id", "weight_jin", "recorded_at", "note", "deleted_at"],
                                }[filename]
                            writer.writerow(columns)
            photos_dir = work / "photos"
            photos_dir.mkdir()
            photo_index = work / "photo_index.csv"
            with photo_index.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["photo_id", "photo_date", "created_at", "archive_path", "original_exists", "byte_size"])
                for row in photo_rows:
                    original = self.body_photo_path(row)
                    filename = f"photo_{int(row['id'])}{original.suffix.lower() or '.jpg'}"
                    archive_relative = f"photos/{filename}"
                    shutil.copy2(original, photos_dir / filename)
                    writer.writerow([row["id"], row["photo_date"], row["created_at"], archive_relative, True, original.stat().st_size])
            (work / "README.txt").write_text(
                "Weight Tracker user export bundle\n"
                "- weight_records.csv: weight_jin is stored in 斤 for backwards compatibility.\n"
                "- food_logs.csv: calories_kcal and macro totals belong to the recorded serving.\n"
                "- strength_logs.csv: gym load is kg; duration is minutes.\n"
                "- body_measurements.csv: circumference is cm; body_fat_pct is percent.\n"
                "- photo_index.csv maps records to original image paths included under photos/.\n"
                "- settings.csv may include personal target/height and reminder preferences.\n"
                "This bundle is for export/interchange, not directly restorable as a full backup.\n",
                encoding="utf-8",
            )
            with zipfile.ZipFile(dest.with_suffix(".zip.part"), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for item in work.rglob("*"):
                    if item.is_file():
                        archive.write(item, item.relative_to(work).as_posix())
            temp = dest.with_suffix(".zip.part")
            with zipfile.ZipFile(temp, "r") as archive:
                bad = archive.testzip()
                if bad:
                    raise ValueError(f"导出压缩包校验失败：{bad}")
            os.replace(temp, dest)
            # Retain only the three most recent internal export bundles. They are
            # fallback copies if the Android save picker is cancelled, but must
            # not grow without bound across repeated full-data exports.
            export_archives = sorted(
                self.backup_dir.glob("weight_tracker_data_export_*.zip"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for old_archive in export_archives[3:]:
                try:
                    old_archive.unlink()
                except OSError:
                    pass
            return {"path": str(dest), "bytes": dest.stat().st_size,
                    "weights": len(self.list_records()), "foods": len(self.list_food_logs()),
                    "training": len(self.list_strength_logs()), "measurements": len(self.list_body_measurements()),
                    "photos": self.count_body_photos()}
        finally:
            shutil.rmtree(work, ignore_errors=True)
            try:
                dest.with_suffix(".zip.part").unlink(missing_ok=True)
            except OSError:
                pass

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
        """Import valid CSV rows idempotently; DB/storage failures roll back the batch.

        Timestamp values with explicit zones are converted into device-local
        time, then stored in the same canonical format as native UI entries.
        Invalid rows are skipped with their physical CSV line numbers; a disk
        or database failure rolls back the complete batch.
        """
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
                    if not row or not any(str(value or "").strip() for value in row.values()):
                        continue
                    try:
                        w = self._validate_weight(row[weight_key])
                        dt = self.validate_recorded_at(row[time_key])
                        note = (str(row[note_key]).strip() if note_key and row.get(note_key) else None) or None
                    except (ValueError, TypeError, KeyError, AttributeError) as exc:
                        failed.append((line_no, str(exc)))
                        continue
                    canonical_time = dt.isoformat(sep=" ", timespec="seconds")
                    possible_duplicates = con.execute(
                        "SELECT recorded_at FROM records WHERE weight=? "
                        "AND trim(COALESCE(note,''))=trim(COALESCE(?, ''))",
                        (w, note),
                    ).fetchall()
                    duplicate = False
                    for existing in possible_duplicates:
                        try:
                            existing_time = self.normalize_recorded_at(existing["recorded_at"])
                        except (TypeError, ValueError, OverflowError):
                            existing_time = None
                        if existing_time == dt:
                            duplicate = True
                            break
                    if duplicate:
                        skipped += 1
                        continue
                    # sqlite errors (including disk-full) intentionally escape and roll back.
                    con.execute(
                        "INSERT INTO records(weight, recorded_at, note) VALUES (?, ?, ?)",
                        (w, canonical_time, note),
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
