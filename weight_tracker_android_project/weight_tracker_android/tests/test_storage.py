"""Regression tests for the SQLite data layer; stdlib-only, no Kivy required."""
import csv
import errno
import os
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta
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

    def test_csv_export_includes_all_historical_records(self):
        self.add_record(60.0, "2023-01-01 08:00:00", "oldest")
        self.add_record(65.0, "2024-06-15 12:30:00", "middle")
        self.add_record(70.0, "2026-10-10 08:30:00", "latest")
        output = self.base / "all_history.csv"
        all_rows = self.storage.list_records()
        self.storage.export_csv(output, all_rows)
        with output.open("r", encoding="utf-8-sig", newline="") as stream:
            exported = list(csv.DictReader(stream))
        self.assertEqual(len(exported), 3)
        self.assertEqual([row["note"] for row in exported], ["oldest", "middle", "latest"])
        self.assertEqual([row["recorded_at"] for row in exported], [
            "2023-01-01 08:00:00", "2024-06-15 12:30:00", "2026-10-10 08:30:00"
        ])

    def test_csv_missing_required_columns_fails_without_mutation(self):
        path = self.base / "bad.csv"
        path.write_text("name,value\na,b\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "至少需要"):
            self.storage.import_csv(path)
        self.assertEqual(self.storage.list_records(), [])

    def test_timezone_aware_csv_timestamp_is_normalized_for_duplicate_detection(self):
        local_time = datetime(2026, 10, 10, 8, 30, 0)
        self.storage.insert(65.5, local_time, "same")
        # Serialize that local wall time with an explicit device-local UTC offset.
        aware = local_time.astimezone()
        csv_path = self.base / "timezone_duplicate.csv"
        csv_path.write_text(
            "weight,recorded_at,note\n65.5," + aware.isoformat() + ",same\n",
            encoding="utf-8",
        )
        self.assertEqual(self.storage.import_csv(csv_path), (0, 1, []))
        self.assertEqual(len(self.storage.list_records()), 1)

    def test_csv_accepts_unambiguous_spreadsheet_date_formats(self):
        csv_path = self.base / "spreadsheet_dates.csv"
        csv_path.write_text(
            "weight,recorded_at,note\n"
            "65.0,2026/10/10 08:30,slash-date\n"
            "66.0,2026年10月11日 09:15,chinese-date\n"
            "67.0,2026-10-12,date-only\n",
            encoding="utf-8",
        )
        inserted, skipped, failed = self.storage.import_csv(csv_path)
        self.assertEqual((inserted, skipped, failed), (3, 0, []))
        self.assertEqual(
            [row["recorded_at"] for row in self.storage.list_records()],
            ["2026-10-10 08:30:00", "2026-10-11 09:15:00", "2026-10-12 00:00:00"],
        )

    def test_csv_rejects_ambiguous_us_style_date_without_guessing(self):
        csv_path = self.base / "ambiguous_date.csv"
        csv_path.write_text(
            "weight,recorded_at,note\n65.0,03/04/2026 08:30,ambiguous\n",
            encoding="utf-8",
        )
        inserted, skipped, failed = self.storage.import_csv(csv_path)
        self.assertEqual((inserted, skipped), (0, 0))
        self.assertEqual(len(failed), 1)
        self.assertIn("日期时间格式不支持", failed[0][1])
        self.assertEqual(self.storage.list_records(), [])

    def test_csv_reports_future_time_and_implausible_weight_as_failed_rows(self):
        future = (datetime.now() + timedelta(days=2)).replace(microsecond=0).isoformat(sep=" ")
        csv_path = self.base / "invalid_rows.csv"
        csv_path.write_text(
            f"weight,recorded_at,note\n5000,2026-10-10 08:30:00,unit-error\n"
            f"65,{future},future\n",
            encoding="utf-8",
        )
        inserted, skipped, failed = self.storage.import_csv(csv_path)
        self.assertEqual((inserted, skipped), (0, 0))
        self.assertEqual(len(failed), 2)
        self.assertEqual(self.storage.list_records(), [])

    def test_insert_update_and_settings_reject_obvious_input_errors(self):
        with self.assertRaisesRegex(ValueError, "体重应在"):
            self.storage.insert(5, datetime.now() - timedelta(days=1), "kg-vs-jin")
        with self.assertRaisesRegex(ValueError, "不能晚于当前时间"):
            self.storage.insert(65, datetime.now() + timedelta(days=1), "future")
        rid = self.storage.insert(65, datetime.now() - timedelta(days=1), "valid")
        with self.assertRaisesRegex(ValueError, "不能晚于当前时间"):
            self.storage.update(rid, 66, None, datetime.now() + timedelta(days=1))
        with self.assertRaisesRegex(ValueError, "身高应在"):
            self.storage.set_setting("height_cm", 25)
        with self.assertRaisesRegex(ValueError, "体重应在"):
            self.storage.set_setting("target_weight", 5000)

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

    def test_legacy_full_backup_without_thumbnail_column_is_migrated_before_validation(self):
        photo_bytes = b"legacy-original-image"
        legacy_db = self.base / "legacy_schema.db"
        con = sqlite3.connect(legacy_db)
        con.executescript("""
            CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, weight REAL NOT NULL, recorded_at TEXT NOT NULL);
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE body_photos (id INTEGER PRIMARY KEY AUTOINCREMENT, photo_date TEXT NOT NULL,
                                      path TEXT NOT NULL, created_at TEXT NOT NULL);
            INSERT INTO records(weight, recorded_at) VALUES (68.5, '2025-02-03 07:30:00');
            INSERT INTO settings(key, value) VALUES ('height_cm', '168');
            INSERT INTO body_photos(photo_date, path, created_at)
                VALUES ('2025-02-03', 'body_photos/legacy.jpg', '2025-02-03 08:00:00');
        """)
        con.commit()
        con.close()
        archive_path = self.base / "legacy_full_backup.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(legacy_db, "weight_tracker.db")
            archive.writestr("body_photos/legacy.jpg", photo_bytes)

        live_before_preview = self.storage.list_records()
        summary = self.storage.inspect_full_backup(archive_path)
        self.assertEqual(summary["records"], 1)
        self.assertEqual(summary["photos"], 1)
        self.assertIn("free_bytes", summary)
        self.assertIn("estimated_peak_bytes", summary)
        self.assertIn("space_sufficient", summary)
        self.assertEqual(self.storage.list_records(), live_before_preview)
        # Current data remains until the user confirms and calls restore.
        self.add_record(72, "2026-10-11 08:30:00", "current")
        result = self.storage.restore_full_backup(archive_path)
        self.assertEqual(result["records"], 1)
        self.assertEqual(result["photos"], 1)
        self.assertEqual(self.storage.list_records()[0]["weight"], 68.5)
        restored_photo = self.storage.body_photo_dir / "legacy.jpg"
        self.assertEqual(restored_photo.read_bytes(), photo_bytes)
        with self.storage._connect() as check:
            columns = {row[1] for row in check.execute("PRAGMA table_info(body_photos)")}
            tables = {row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("thumbnail_path", columns)
        self.assertIn("recycle_bin", tables)
        self.assertIn("daily_activity", tables)

    def test_backup_preview_rejects_unsafe_thumbnail_path_before_confirmation(self):
        original = self.storage.body_photo_dir / "valid.jpg"
        original.write_bytes(b"original-image-bytes")
        photo_id = self.storage.add_body_photo("2026-10-10", original)
        with self.storage._connect() as con:
            con.execute("UPDATE body_photos SET thumbnail_path=? WHERE id=?", ("body_photo_thumbnails/../outside.jpg", photo_id))
        archive_path = self.base / "unsafe_thumbnail_path.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(self.storage.db_path, "weight_tracker.db")
            archive.write(original, "body_photos/valid.jpg")
        before_records = self.storage.list_records()
        with self.assertRaisesRegex(ValueError, "不安全的缩略图路径"):
            self.storage.inspect_full_backup(archive_path)
        self.assertEqual(self.storage.list_records(), before_records)
        self.assertTrue(original.is_file())

    def test_full_backup_refuses_to_claim_success_when_original_photo_is_missing(self):
        with self.storage._connect() as con:
            con.execute(
                "INSERT INTO body_photos(photo_date, path, created_at, thumbnail_path) "
                "VALUES (?, ?, ?, ?)",
                ("2026-10-10", "body_photos/missing.jpg", "2026-10-10 08:00:00", None),
            )
        with self.assertRaisesRegex(FileNotFoundError, "原图不存在"):
            self.storage.create_full_backup()

    def test_full_backup_refuses_zero_byte_original_photo(self):
        photo = self.storage.body_photo_dir / "empty.jpg"
        photo.write_bytes(b"")
        self.storage.add_body_photo("2026-10-10", photo)
        with self.assertRaisesRegex(ValueError, "为空文件"):
            self.storage.create_full_backup()

    def test_legacy_backup_migrates_missing_workout_column(self):
        legacy_db = self.base / "legacy_workout_schema.db"
        con = sqlite3.connect(legacy_db)
        con.executescript("""
            CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, weight REAL NOT NULL, recorded_at TEXT NOT NULL);
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE daily_activity (date TEXT PRIMARY KEY);
            INSERT INTO records(weight, recorded_at) VALUES (69, '2025-03-04 07:30:00');
            INSERT INTO daily_activity(date) VALUES ('2025-03-04');
        """)
        con.commit()
        con.close()
        archive_path = self.base / "legacy_workout_backup.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(legacy_db, "weight_tracker.db")
        summary = self.storage.inspect_full_backup(archive_path)
        self.assertEqual(summary["records"], 1)
        self.assertEqual(summary["workout_days"], 0)
        self.storage.restore_full_backup(archive_path)
        self.assertEqual(self.storage.list_records()[0]["weight"], 69)
        self.assertFalse(self.storage.get_workout("2025-03-04"))

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
