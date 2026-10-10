"""Regression tests for the SQLite data layer; stdlib-only, no Kivy required."""
import csv
import errno
import os
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from storage import Storage


class StorageRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "appdata"
        self.storage = Storage(self.base)
        # Keep tests deterministic; backup scheduling is covered by separate app/device checks.
        self.storage.schedule_backup = lambda: None

    def tearDown(self):
        self.temp.cleanup()

    def add_record(self, weight=65.5, when="2026-10-10 08:30:00", note="test"):
        return self.storage.insert(weight, datetime.fromisoformat(when), note)

    def test_crud_and_duplicate_csv_import_are_idempotent(self):
        csv_path = self.base / "input.csv"
        csv_path.write_text(
            "weight,recorded_at,note\n65.5,2026-10-10 08:30:00,test\n"
            "66.0,2026-10-11 08:30:00,new\n"
            "not-a-number,2026-10-12 08:30:00,bad\n",
            encoding="utf-8",
        )
        self.assertEqual(self.storage.import_csv(csv_path), (2, 0, [(4, "could not convert string to float: 'not-a-number'")]))
        inserted, skipped, failed = self.storage.import_csv(csv_path)
        self.assertEqual((inserted, skipped, len(failed)), (0, 2, 1))
        rows = self.storage.list_records()
        self.assertEqual(len(rows), 2)
        rid = rows[0]["id"]
        self.storage.delete(rid)
        self.assertEqual(len(self.storage.list_records()), 1)
        self.assertEqual(len(self.storage.recycle()), 1)
        self.storage.restore(self.storage.recycle()[0]["id"])
        self.assertEqual(len(self.storage.list_records()), 2)

    def test_csv_missing_required_columns_fails_without_mutation(self):
        path = self.base / "bad.csv"
        path.write_text("name,value\na,b\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "至少需要"):
            self.storage.import_csv(path)
        self.assertEqual(self.storage.list_records(), [])

    def test_csv_database_error_rolls_back_entire_batch(self):
        self.storage.insert(60, datetime(2026, 1, 1), "existing")
        with self.storage._connect() as con:
            con.execute("CREATE TRIGGER fail_import BEFORE INSERT ON records "
                        "WHEN NEW.note='disk-full' BEGIN SELECT RAISE(ABORT, 'database or disk is full'); END")
        path = self.base / "diskfull.csv"
        path.write_text("weight,recorded_at,note\n61,2026-01-02 00:00:00,ok\n"
                        "62,2026-01-03 00:00:00,disk-full\n", encoding="utf-8")
        with self.assertRaises(sqlite3.IntegrityError):
            self.storage.import_csv(path)
        self.assertEqual(len(self.storage.list_records()), 1)

    def test_full_backup_restores_records_settings_workouts_and_photos(self):
        self.add_record()
        self.storage.set_setting("height_cm", 175)
        self.storage.set_workout("2026-10-10", True)
        photo = self.storage.body_photo_dir / "sample.jpg"
        photo.write_bytes(b"original-image-bytes")
        thumb = self.storage.body_photo_thumbnail_dir / "sample.jpg"
        thumb.write_bytes(b"thumbnail-bytes")
        self.storage.add_body_photo("2026-10-10", photo, datetime(2026, 10, 10, 9), thumb)
        archive = self.storage.create_full_backup()
        self.assertTrue(archive and archive.is_file())

        self.storage.insert(80, datetime(2026, 10, 11), "later")
        photo.write_bytes(b"modified")
        result = self.storage.restore_full_backup(archive)
        self.assertEqual(result["records"], 1)
        self.assertEqual(result["photos"], 1)
        self.assertEqual(len(self.storage.list_records()), 1)
        self.assertEqual(self.storage.get_setting("height_cm"), "175")
        self.assertTrue(self.storage.get_workout("2026-10-10"))
        self.assertEqual(photo.read_bytes(), b"original-image-bytes")
        self.assertEqual(thumb.read_bytes(), b"thumbnail-bytes")
        self.assertTrue(Path(result["safety_backup"]).is_file())

    def test_invalid_or_unsafe_backup_does_not_touch_live_data(self):
        self.add_record()
        before = self.storage.list_records()
        bad = self.base / "unsafe.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("../evil.txt", "evil")
            zf.writestr("weight_tracker.db", b"not-a-database")
        with self.assertRaises(ValueError):
            self.storage.restore_full_backup(bad)
        self.assertEqual(self.storage.list_records(), before)

    def test_low_disk_space_preflight_leaves_live_data_unchanged(self):
        self.add_record(63)
        archive = self.storage.create_full_backup()
        before = self.storage.list_records()
        with mock.patch("storage.shutil.disk_usage", return_value=mock.Mock(free=1)):
            with self.assertRaisesRegex(OSError, "存储空间不足"):
                self.storage.restore_full_backup(archive)
        self.assertEqual(self.storage.list_records(), before)

    def test_failed_install_rolls_back_existing_database_and_photos(self):
        self.add_record(61)
        old_photo = self.storage.body_photo_dir / "old.jpg"
        old_photo.write_bytes(b"keep")
        archive = self.storage.create_full_backup()
        self.add_record(62, "2026-10-11 08:30:00", "later")
        original_records = self.storage.list_records()
        original_replace = os.replace

        def fail_new_database_install(src, dst):
            src_path, dst_path = Path(src), Path(dst)
            if ".restore_stage_" in str(src_path) and src_path.name == "weight_tracker.db" and dst_path == self.storage.db_path:
                raise OSError(errno.ENOSPC, "No space left on device")
            return original_replace(src, dst)

        with mock.patch("storage.os.replace", side_effect=fail_new_database_install):
            with self.assertRaises(OSError):
                self.storage.restore_full_backup(archive)
        self.assertEqual(self.storage.list_records(), original_records)
        self.assertEqual(old_photo.read_bytes(), b"keep")

    def test_legacy_schema_migrates_without_losing_records(self):
        legacy = self.base / "legacy"
        legacy.mkdir()
        db = legacy / "weight_tracker.db"
        con = sqlite3.connect(db)
        con.executescript("""
            CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, weight REAL NOT NULL, recorded_at TEXT NOT NULL, note TEXT);
            CREATE TABLE recycle_bin (id INTEGER PRIMARY KEY AUTOINCREMENT, original_id INTEGER NOT NULL, weight REAL NOT NULL, recorded_at TEXT NOT NULL, note TEXT, deleted_at TEXT NOT NULL);
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE daily_activity (date TEXT PRIMARY KEY, workout INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE body_photos (id INTEGER PRIMARY KEY AUTOINCREMENT, photo_date TEXT NOT NULL, path TEXT NOT NULL, created_at TEXT NOT NULL);
            INSERT INTO records(weight, recorded_at, note) VALUES (70, '2025-01-01 10:00:00', 'legacy');
        """)
        con.commit()
        con.close()
        upgraded = Storage(legacy)
        self.assertEqual(len(upgraded.list_records()), 1)
        with upgraded._connect() as check:
            columns = {row[1] for row in check.execute("PRAGMA table_info(body_photos)")}
            indexes = {row[1] for row in check.execute("PRAGMA index_list(records)")}
        self.assertIn("thumbnail_path", columns)
        self.assertIn("idx_records_recorded_at", indexes)

    def test_partial_files_are_not_included_in_backup(self):
        self.add_record()
        (self.storage.body_photo_dir / "interrupted.jpg.part").write_bytes(b"partial")
        archive = self.storage.create_full_backup()
        with zipfile.ZipFile(archive) as zf:
            self.assertNotIn("body_photos/interrupted.jpg.part", zf.namelist())


if __name__ == "__main__":
    unittest.main(verbosity=2)
