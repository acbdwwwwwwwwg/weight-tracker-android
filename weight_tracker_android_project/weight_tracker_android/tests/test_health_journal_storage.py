"""Behavior tests for Phase 3 local nutrition, training and body metrics."""
import csv
import sqlite3
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch
from datetime import date, datetime
from pathlib import Path

from storage import Storage


class HealthJournalStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "appdata"
        self.storage = Storage(self.base)
        self.storage.schedule_backup = lambda: None

    def tearDown(self):
        self.temp.cleanup()

    def add_weight(self, weight, timestamp, note=None):
        return self.storage.insert(weight, datetime.fromisoformat(timestamp), note)

    def test_food_portion_macros_and_custom_food_persist(self):
        row_id = self.storage.add_food_log(
            datetime(2026, 10, 18, 8, 30), "早餐", "燕麦", 50,
            380, 13, 68, 7,
        )
        rows = self.storage.list_food_logs("2026-10-18", "2026-10-18")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["id"], row_id)
        self.assertEqual(row["food_name"], "燕麦")
        self.assertAlmostEqual(row["calories_kcal"], 190.0)
        self.assertAlmostEqual(row["protein_g"], 6.5)
        self.assertAlmostEqual(row["carbs_g"], 34.0)
        self.assertAlmostEqual(row["fat_g"], 3.5)
        foods = self.storage.list_foods()
        self.assertEqual(len(foods), 1)
        self.assertEqual(foods[0]["name"], "燕麦")

    def test_food_validation_rejects_zero_portion_and_bad_meal(self):
        with self.assertRaisesRegex(ValueError, "份量必须大于 0"):
            self.storage.add_food_log(datetime(2026, 10, 18, 8), "早餐", "苹果", 0, 50)
        with self.assertRaisesRegex(ValueError, "请选择早餐"):
            self.storage.add_food_log(datetime(2026, 10, 18, 8), "夜宵", "苹果", 100, 50)
        self.assertEqual(self.storage.list_food_logs(), [])

    def test_food_update_delete_and_undo_restore(self):
        row_id = self.storage.add_food_log(datetime(2026, 10, 18, 8), "早餐", "鸡蛋", 100, 140)
        original = self.storage.list_food_logs()[0]
        self.storage.update_food_log(row_id, datetime(2026, 10, 18, 9), "加餐", "牛奶", 200, 60, 3, 5, 3)
        changed = self.storage.list_food_logs()[0]
        self.assertEqual(changed["food_name"], "牛奶")
        self.assertAlmostEqual(changed["calories_kcal"], 120)
        removed = self.storage.delete_food_log(row_id)
        self.assertEqual(self.storage.list_food_logs(), [])
        self.storage.restore_food_log(removed)
        restored = self.storage.list_food_logs()[0]
        self.assertEqual(restored["food_name"], "牛奶")
        self.assertEqual(restored["meal_type"], "加餐")

    def test_strength_log_validation_crud_and_workout_sync(self):
        log_id = self.storage.add_strength_log(
            datetime(2026, 10, 18, 18), "深蹲", 4, 10, 50, 35, "主训练",
        )
        rows = self.storage.list_strength_logs("2026-10-18", "2026-10-18")
        self.assertEqual(rows[0]["id"], log_id)
        self.assertTrue(self.storage.get_workout("2026-10-18"))
        self.storage.update_strength_log(log_id, datetime(2026, 10, 19, 7), "硬拉", 3, 8, 70, 40, None)
        changed = self.storage.list_strength_logs("2026-10-19", "2026-10-19")[0]
        self.assertEqual(changed["exercise_name"], "硬拉")
        self.assertEqual(changed["sets"], 3)
        removed = self.storage.delete_strength_log(log_id)
        self.assertEqual(self.storage.list_strength_logs(), [])
        self.storage.restore_strength_log(removed)
        self.assertEqual(self.storage.list_strength_logs()[0]["exercise_name"], "硬拉")
        with self.assertRaisesRegex(ValueError, "至少填写"):
            self.storage.add_strength_log(datetime(2026, 10, 18, 18), "空动作", 0, 0, 0, 0)

    def test_body_measurement_crud_and_bounds(self):
        measurement_id = self.storage.add_body_measurement("2026-10-18", 82, 96, 99, 24.5, "早晨")
        self.assertEqual(self.storage.list_body_measurements()[0]["id"], measurement_id)
        self.storage.update_body_measurement(measurement_id, "2026-10-19", 80, 95, None, 23.8, "空腹")
        row = self.storage.list_body_measurements()[0]
        self.assertEqual(row["measured_at"], "2026-10-19")
        self.assertEqual(row["chest_cm"], None)
        with self.assertRaisesRegex(ValueError, "至少填写一项"):
            self.storage.add_body_measurement("2026-10-18")
        with self.assertRaisesRegex(ValueError, "体脂率"):
            self.storage.add_body_measurement("2026-10-18", body_fat_pct=90)
        removed = self.storage.delete_body_measurement(measurement_id)
        self.assertEqual(self.storage.list_body_measurements(), [])
        self.storage.restore_body_measurement(removed)
        self.assertEqual(self.storage.list_body_measurements()[0]["measured_at"], "2026-10-19")

    def test_seven_day_average_uses_daily_means_not_each_reading_weighted(self):
        self.add_weight(60, "2026-10-18 07:00:00")
        self.add_weight(70, "2026-10-18 19:00:00")
        self.add_weight(66, "2026-10-19 07:00:00")
        result = self.storage.get_seven_day_weight_average(date(2026, 10, 19))
        self.assertAlmostEqual(result["average_jin"], 65.5)
        self.assertEqual(result["days"], 2)
        self.assertEqual(result["records"], 3)
        self.assertEqual(result["start"], "2026-10-13")
        self.assertEqual(result["end"], "2026-10-19")

    def test_report_scopes_measurements_and_photos_to_period(self):
        self.add_weight(70, "2026-10-19 08:00:00")
        self.add_weight(68, "2026-10-19 09:00:00")
        self.storage.add_body_measurement("2026-10-02", waist_cm=85)
        self.storage.add_body_measurement("2026-10-19", waist_cm=82)
        photo_path = self.storage.body_photo_dir / "period.jpg"
        photo_path.write_bytes(b"photo-data")
        self.storage.add_body_photo("2026-10-19", photo_path)
        self.storage.add_food_log(datetime(2026, 10, 19, 12), "午餐", "米饭", 200, 130)
        self.storage.add_strength_log(datetime(2026, 10, 19, 7), "卧推", 3, 8, 30, 25)
        report = self.storage.build_health_report("week", date(2026, 10, 19))
        self.assertEqual(report["start_date"], "2026-10-19")
        self.assertEqual(report["end_date"], "2026-10-19")
        self.assertEqual(report["photo_count"], 1)
        self.assertEqual(report["training_entries"], 1)
        self.assertEqual(report["food_entries"], 1)
        self.assertEqual(report["latest_measurement"]["measured_at"], "2026-10-19")

    def test_full_data_export_includes_csv_datasets_and_original_photos(self):
        self.add_weight(70, "2026-10-19 08:00:00", "weight")
        self.storage.add_food_log(datetime(2026, 10, 19, 12), "午餐", "米饭", 200, 130)
        self.storage.add_strength_log(datetime(2026, 10, 19, 7), "卧推", 3, 8, 30, 25)
        self.storage.add_body_measurement("2026-10-19", waist_cm=82)
        photo_path = self.storage.body_photo_dir / "original.jpg"
        photo_path.write_bytes(b"test-original-image")
        self.storage.add_body_photo("2026-10-19", photo_path)
        result = self.storage.create_data_export_archive()
        archive_path = Path(result["path"])
        self.assertTrue(archive_path.is_file())
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
            self.assertTrue({"weight_records.csv", "food_logs.csv", "food_catalog.csv",
                             "strength_logs.csv", "body_measurements.csv", "daily_activity.csv",
                             "settings.csv", "recycle_bin.csv", "photo_index.csv", "README.txt"}.issubset(names))
            self.assertIn("photos/photo_1.jpg", names)
            food_csv = archive.read("food_logs.csv").decode("utf-8-sig")
            self.assertIn("米饭", food_csv)
            index_csv = archive.read("photo_index.csv").decode("utf-8-sig")
            self.assertIn("2026-10-19", index_csv)
        self.assertEqual(result["weights"], 1)
        self.assertEqual(result["foods"], 1)
        self.assertEqual(result["training"], 1)
        self.assertEqual(result["measurements"], 1)
        self.assertEqual(result["photos"], 1)

    def test_data_export_fails_clearly_if_photo_original_is_missing(self):
        with self.storage._connect() as con:
            con.execute("INSERT INTO body_photos(photo_date, path, created_at) VALUES (?, ?, ?)",
                        ("2026-10-20", "body_photos/not-found.jpg", "2026-10-19 08:00:00"))
        with self.assertRaisesRegex(FileNotFoundError, "原图缺失"):
            self.storage.create_data_export_archive()

    def test_data_export_refuses_low_storage_before_creating_archive(self):
        # Full-data export stages originals and builds a ZIP alongside them, so
        # it must reject a low-space situation before creating temporary files.
        with patch("storage.shutil.disk_usage", return_value=SimpleNamespace(free=1)):
            with self.assertRaisesRegex(OSError, "存储空间不足"):
                self.storage.create_data_export_archive()
        self.assertEqual(list(self.storage.backup_dir.glob("weight_tracker_data_export_*.zip")), [])
        self.assertEqual(list(self.storage.backup_dir.glob(".data_export_*")), [])

    def test_weight_progress_summary_returns_history_endpoints_without_data_loss(self):
        self.add_weight(70, "2026-10-18 08:00:00")
        self.add_weight(68.5, "2026-10-19 07:30:00")
        summary = self.storage.get_weight_progress_summary()
        self.assertEqual(summary["count"], 2)
        self.assertAlmostEqual(summary["first_weight_jin"], 70)
        self.assertAlmostEqual(summary["current_weight_jin"], 68.5)
        self.assertEqual(summary["latest_recorded_at"], "2026-10-19 07:30:00")

    def test_existing_live_database_migration_adds_new_journal_tables(self):
        # The current DB migration should be safe for a legacy schema with the
        # old core tables but without nutrition/training/body-measurement tables.
        legacy_dir = Path(self.temp.name) / "legacy-appdata"
        legacy_dir.mkdir()
        con = sqlite3.connect(legacy_dir / "weight_tracker.db")
        con.executescript("""
            CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, weight REAL NOT NULL, recorded_at TEXT NOT NULL);
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE daily_activity (date TEXT PRIMARY KEY);
            CREATE TABLE body_photos (id INTEGER PRIMARY KEY AUTOINCREMENT, photo_date TEXT NOT NULL, path TEXT NOT NULL);
            CREATE TABLE recycle_bin (id INTEGER PRIMARY KEY AUTOINCREMENT, weight REAL NOT NULL, recorded_at TEXT NOT NULL);
            INSERT INTO records(weight, recorded_at) VALUES (70, '2026-10-18 08:00:00');
            INSERT INTO daily_activity(date) VALUES ('2026-10-18');
        """)
        con.commit(); con.close()
        upgraded = Storage(legacy_dir)
        rows = upgraded.list_records()
        self.assertEqual(len(rows), 1)
        with upgraded._connect() as check:
            tables = {row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            photo_columns = {row[1] for row in check.execute("PRAGMA table_info(body_photos)")}
            activity_columns = {row[1] for row in check.execute("PRAGMA table_info(daily_activity)")}
            recycle_columns = {row[1] for row in check.execute("PRAGMA table_info(recycle_bin)")}
            record_columns = {row[1] for row in check.execute("PRAGMA table_info(records)")}
        self.assertTrue({"foods", "food_logs", "strength_logs", "body_measurements"}.issubset(tables))
        self.assertIn("thumbnail_path", photo_columns)
        self.assertIn("created_at", photo_columns)
        self.assertIn("workout", activity_columns)
        self.assertTrue({"original_id", "note", "deleted_at"}.issubset(recycle_columns))
        self.assertIn("note", record_columns)
        self.assertFalse(upgraded.get_workout("2026-10-18"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
