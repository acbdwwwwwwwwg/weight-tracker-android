"""Settings, CSV, recycle-bin and shared dialog behavior."""

from datetime import datetime
import os
from pathlib import Path
from uuid import uuid4

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView

from services.units import normalize_weight_unit
from services.android_bridge import (
    ANDROID_AVAILABLE, ANDROID_IMPORT_ERROR, IS_ANDROID, CSV_PICK_REQUEST,
    CSV_SAVE_REQUEST, DATA_EXPORT_SAVE_REQUEST, FULL_BACKUP_PICK_REQUEST, android_activity, autoclass,
    copy_path_to_uri, copy_uri_to_path, get_current_activity,
)
from ui.theme import BG, FONT_NAME, MUTED, PRIMARY, TEXT

class SettingsFeatureMixin:
    """Application settings, CSV import/export, recycle-bin and dialogs."""

    def _float_setting(self, key):
        v = self.storage.get_setting(key)
        try:
            return float(v) if v else None
        except Exception:
            return None

    def ask_height(self, *_):
        self.input_setting("保存身高(cm)", self.height_cm, lambda v: self.set_height(v))

    def set_height(self, v):
        x = self.storage.validate_height_cm(v)
        self.height_cm = x
        self.storage.set_setting("height_cm", x)
        self.refresh()
        self.refresh_profile_summary()

    def ask_target(self, *_):
        current = self.display_weight(self.target_weight) if self.target_weight is not None else None
        self.input_setting(f"保存目标体重({self.weight_unit_label()})", current, lambda v: self.set_target(v))

    def set_target(self, v):
        if str(v).strip() == "":
            self.target_weight = None
            self.storage.set_setting("target_weight", None)
        else:
            storage_value = self.weight_to_storage(v)
            x = self.storage.validate_target_weight(storage_value)
            self.target_weight = x
            self.storage.set_setting("target_weight", x)
        self.refresh()
        self.refresh_profile_summary()

    def input_setting(self, title, value, callback):
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        # These setting dialogs are used for height and target weight only.
        # Filter obvious non-numeric keystrokes, while keeping Storage validation
        # authoritative (including empty target to clear the goal).
        inp = self._field(
            text="" if value is None else str(value),
            input_filter="float",
            hint_text="请输入数值，可使用小数",
            size_hint_y=None,
            height=dp(44),
        )
        content.add_widget(inp)
        btn = self.button("保存", lambda *_: self._save_setting_popup(popup, inp.text, callback), 42, tone="primary")
        content.add_widget(btn)
        popup = Popup(title=title, title_font=FONT_NAME, content=content, size_hint=(.85, None), height=dp(170), background="", separator_color=(0, 0, 0, 0))
        popup.open()

    def _save_setting_popup(self, popup, value, callback):
        try:
            callback(value)
            popup.dismiss()
        except Exception as e:
            self.info("设置失败", str(e))

    def switch_theme(self, *_):
        # 当前版本统一使用健身深色主题，避免只切换窗口底色造成卡片与背景不一致。
        self.theme = "深色"
        self.storage.set_setting("theme", self.theme)
        Window.clearcolor = BG
        self.info("健身深色主题", "当前采用炭黑背景、圆角卡片与珊瑚红训练重点色。")

    def root_window_color(self, color):
        Window = __import__("kivy.core.window", fromlist=["Window"]).Window
        Window.clearcolor = color

    def export_csv(self, *_):
        """Export every historical weight record to a user-accessible destination."""
        filename = f"weight_records_{datetime.now():%Y%m%d_%H%M%S}.csv"
        if IS_ANDROID:
            if not ANDROID_AVAILABLE:
                self.info("无法导出 CSV", ANDROID_IMPORT_ERROR or "Android 文件接口不可用。")
                return
            try:
                try:
                    android_activity.unbind(on_activity_result=self.on_csv_save_result)
                except Exception:
                    pass
                android_activity.bind(on_activity_result=self.on_csv_save_result)
                Intent = autoclass("android.content.Intent")
                intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
                intent.addCategory(Intent.CATEGORY_OPENABLE)
                intent.setType("text/csv")
                intent.putExtra(Intent.EXTRA_TITLE, filename)
                intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION)
                get_current_activity().startActivityForResult(intent, CSV_SAVE_REQUEST)
            except Exception as exc:
                try:
                    android_activity.unbind(on_activity_result=self.on_csv_save_result)
                except Exception:
                    pass
                self.info("打开保存位置失败", f"{type(exc).__name__}: {exc}")
            return

        # Desktop/test builds cannot use Android's Storage Access Framework.
        path = Path(self.user_data_dir) / filename
        storage = self.storage

        def worker():
            rows = storage.list_records()
            storage.export_csv(path, rows)
            return {"path": str(path), "rows": len(rows), "bytes": path.stat().st_size}

        def complete(result):
            self.info("CSV 导出完成", f"已导出全部历史记录，共 {result['rows']} 条。\n文件：{result['path']}")

        self.run_background_task("正在导出全部历史记录", worker, on_success=complete,
                                 on_error=lambda exc: self.info("导出失败", f"{type(exc).__name__}: {exc}"))

    def on_csv_save_result(self, request_code, result_code, intent):
        if int(request_code) != CSV_SAVE_REQUEST:
            return
        try:
            android_activity.unbind(on_activity_result=self.on_csv_save_result)
        except Exception:
            pass
        try:
            Activity = autoclass("android.app.Activity")
            if int(result_code) != int(Activity.RESULT_OK) or intent is None:
                return  # User cancelled the document picker.
            uri = intent.getData()
            if uri is None:
                self.info("CSV 导出失败", "系统没有返回保存文件的位置。")
                return
            uri_text = str(uri.toString())
            Clock.schedule_once(lambda *_: self._export_csv_uri(uri_text), 0)
        except Exception as exc:
            self.info("CSV 导出失败", f"{type(exc).__name__}: {exc}")

    def _export_csv_uri(self, uri_text):
        """Write all records to a temporary file, then stream it to the picked URI."""
        temp_path = Path(self.user_data_dir) / f"csv_export_{uuid4().hex}.csv"
        storage = self.storage

        def worker():
            try:
                rows = storage.list_records()  # no active chart-window limit
                storage.export_csv(temp_path, rows)
                Uri = autoclass("android.net.Uri")
                copied = copy_path_to_uri(temp_path, Uri.parse(str(uri_text)))
                return {"rows": len(rows), "bytes": copied}
            finally:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

        def complete(result):
            size_kb = result["bytes"] / 1024
            self.info("CSV 导出完成", f"已保存全部历史记录，共 {result['rows']} 条（{size_kb:.1f} KB）。\n文件已保存到你选择的位置。")

        self.run_background_task("正在导出全部历史记录", worker, on_success=complete,
                                 on_error=lambda exc: self.info("CSV 导出失败", f"{type(exc).__name__}: {exc}"))

    def export_all_data(self, *_):
        """Export all user-facing datasets to a ZIP and then open Android SAF."""
        def complete(result):
            path = Path(result["path"])
            if not IS_ANDROID or not ANDROID_AVAILABLE:
                self.info("全部数据导出完成",
                          f"文件：{path}\n体重 {result['weights']} 条 · 饮食 {result['foods']} 条 · "
                          f"训练 {result['training']} 项 · 身体测量 {result['measurements']} 条 · 照片 {result['photos']} 张。")
                return
            self._open_data_export_save_picker(path)
        self.run_background_task("正在导出全部健康数据和照片", self.storage.create_data_export_archive,
                                 on_success=complete,
                                 on_error=lambda exc: self.info("全部数据导出失败", f"{type(exc).__name__}: {exc}"))

    def _open_data_export_save_picker(self, path):
        try:
            try:
                android_activity.unbind(on_activity_result=self.on_data_export_save_result)
            except Exception:
                pass
            android_activity.bind(on_activity_result=self.on_data_export_save_result)
            Intent = autoclass("android.content.Intent")
            intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType("application/zip")
            intent.putExtra(Intent.EXTRA_TITLE, path.name)
            intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION)
            self._pending_data_export_path = str(path)
            get_current_activity().startActivityForResult(intent, DATA_EXPORT_SAVE_REQUEST)
        except Exception as exc:
            try:
                android_activity.unbind(on_activity_result=self.on_data_export_save_result)
            except Exception:
                pass
            self.info("打开保存位置失败", f"导出包仍保留在应用内部。{type(exc).__name__}: {exc}")

    def on_data_export_save_result(self, request_code, result_code, intent):
        if int(request_code) != DATA_EXPORT_SAVE_REQUEST:
            return
        try:
            android_activity.unbind(on_activity_result=self.on_data_export_save_result)
        except Exception:
            pass
        try:
            Activity = autoclass("android.app.Activity")
            if int(result_code) != int(Activity.RESULT_OK) or intent is None:
                self.info("已取消导出", "取消保存不会修改或删除任何记录；导出包仍保留在应用内部。")
                return
            uri = intent.getData()
            source = getattr(self, "_pending_data_export_path", None)
            if uri is None or not source:
                raise OSError("系统没有返回保存位置或导出文件路径。")
            uri_text = str(uri.toString())
            self.run_background_task(
                "正在保存全部健康数据",
                lambda: copy_path_to_uri(source, autoclass("android.net.Uri").parse(uri_text)),
                on_success=lambda size: self.info("全部数据已导出", f"已保存 {size / (1024 * 1024):.1f} MB，包含 CSV 数据表、照片索引和照片原图。"),
                on_error=lambda exc: self.info("保存失败", f"{type(exc).__name__}: {exc}。应用内部仍保留导出包。"),
            )
        except Exception as exc:
            self.info("全部数据导出失败", f"{type(exc).__name__}: {exc}")

    def import_csv(self, *_):
        """Use Android's document picker and copy the selected URI off the UI thread."""
        if not IS_ANDROID or not ANDROID_AVAILABLE:
            self.info("需要 Android 文件选择器", ANDROID_IMPORT_ERROR or "当前环境不支持 Android 文件选择器。")
            return
        try:
            try:
                android_activity.unbind(on_activity_result=self.on_csv_activity_result)
            except Exception:
                pass
            android_activity.bind(on_activity_result=self.on_csv_activity_result)
            Intent = autoclass("android.content.Intent")
            intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType("*/*")
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            get_current_activity().startActivityForResult(intent, CSV_PICK_REQUEST)
        except Exception as exc:
            try:
                android_activity.unbind(on_activity_result=self.on_csv_activity_result)
            except Exception:
                pass
            self.info("打开文件选择器失败", f"{type(exc).__name__}: {exc}")

    def on_csv_activity_result(self, request_code, result_code, intent):
        if int(request_code) != CSV_PICK_REQUEST:
            return
        try:
            android_activity.unbind(on_activity_result=self.on_csv_activity_result)
        except Exception:
            pass
        try:
            Activity = autoclass("android.app.Activity")
            if int(result_code) != int(Activity.RESULT_OK) or intent is None:
                return
            uri = intent.getData()
            if uri is None:
                return
            uri_text = str(uri.toString())
            Clock.schedule_once(lambda *_: self._import_csv_uri(uri_text), 0)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            Clock.schedule_once(lambda *_args, text=message: self.info("读取 CSV 失败", text), 0)

    def _import_csv_uri(self, uri_text):
        """Copy and parse the selected content URI on a worker thread."""
        import_path = Path(self.user_data_dir) / f"csv_import_{uuid4().hex}.csv"
        partial_path = import_path.with_suffix(".csv.part")
        storage = self.storage

        def worker():
            try:
                Uri = autoclass("android.net.Uri")
                copy_uri_to_path(Uri.parse(str(uri_text)), partial_path)
                os.replace(partial_path, import_path)
                return storage.import_csv(import_path)
            finally:
                for path in (partial_path, import_path):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass

        def complete(result):
            inserted, skipped, failed = result
            self.refresh()
            self.refresh_profile_summary()
            if failed:
                details = (
                    f"CSV 部分导入完成：新增 {inserted} 条，跳过重复 {skipped} 条，"
                    f"{len(failed)} 行未导入。\n失败行不会写入数据库，其余有效行已导入。"
                )
                details += "\n前 5 个错误：\n" + "\n".join(
                    f"第 {line} 行：{reason}" for line, reason in failed[:5]
                )
                if len(failed) > 5:
                    details += f"\n另有 {len(failed) - 5} 行错误未在弹窗中展开。"
                self.info("CSV 部分导入", details)
            else:
                self.info("CSV 导入完成", f"新增 {inserted} 条，跳过重复 {skipped} 条，没有失败行。")

        self.run_background_task("正在读取并导入 CSV", worker, on_success=complete,
                                 on_error=lambda exc: self.info("CSV 导入失败", f"{type(exc).__name__}: {exc}"))

    def restore_full_backup(self, *_):
        """Choose a ZIP from Android documents or an existing app-private snapshot."""
        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        content.add_widget(self.label(
            "恢复前会先检查数据库、照片原图和备份完整性，再显示内容供你确认。"
            "确认后将替换当前记录、设置、训练打卡与体型照片。", 12
        ))
        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        popup = Popup(title="恢复完整备份", title_font=FONT_NAME, content=content,
                      size_hint=(.92, None), height=dp(252), background="",
                      separator_color=(0, 0, 0, 0), auto_dismiss=False)
        actions.add_widget(self.button("取消", lambda *_: popup.dismiss(), 42, tone="secondary"))
        actions.add_widget(self.button("从文件选择", lambda *_: self._open_full_backup_picker(popup), 42, tone="primary"))
        content.add_widget(actions)
        content.add_widget(self.button("选择应用内已有备份", lambda *_: self._choose_internal_full_backup(popup), 42, tone="secondary"))
        popup.open()

    def _choose_internal_full_backup(self, confirm_popup=None):
        backups = sorted(self.storage.backup_dir.glob("weight_tracker_full_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        if confirm_popup:
            confirm_popup.dismiss()
        if not backups:
            self.info("没有可恢复的本机备份", "请先创建完整备份，或从系统文件选择器选择之前导出的 ZIP。")
            return
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        scroll = ScrollView()
        items = GridLayout(cols=1, size_hint_y=None, spacing=dp(6))
        items.bind(minimum_height=items.setter("height"))
        scroll.add_widget(items)
        content.add_widget(scroll)
        popup = Popup(title="选择应用内备份", title_font=FONT_NAME, content=content,
                      size_hint=(.94, .78), background="", separator_color=(0, 0, 0, 0))
        content.add_widget(self.button("取消", lambda *_: popup.dismiss(), 42, tone="secondary"))
        for path in backups[:10]:
            try:
                detail = f"{path.name} · {path.stat().st_size / (1024 * 1024):.1f} MB"
            except OSError:
                detail = path.name
            items.add_widget(self.button(
                detail,
                lambda _btn, selected=path: self._restore_local_backup(selected, popup),
                46, tone="secondary"
            ))
        popup.open()

    def _open_full_backup_picker(self, confirm_popup=None):
        if not IS_ANDROID or not ANDROID_AVAILABLE:
            if confirm_popup:
                confirm_popup.dismiss()
            self.info("需要 Android 文件选择器", ANDROID_IMPORT_ERROR or "当前环境不支持 Android 文件选择器。")
            return
        try:
            try:
                android_activity.unbind(on_activity_result=self.on_full_backup_activity_result)
            except Exception:
                pass
            android_activity.bind(on_activity_result=self.on_full_backup_activity_result)
            Intent = autoclass("android.content.Intent")
            intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType("*/*")
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            get_current_activity().startActivityForResult(intent, FULL_BACKUP_PICK_REQUEST)
            if confirm_popup:
                confirm_popup.dismiss()
        except Exception as exc:
            try:
                android_activity.unbind(on_activity_result=self.on_full_backup_activity_result)
            except Exception:
                pass
            if confirm_popup:
                confirm_popup.dismiss()
            self.info("打开文件选择器失败", f"{type(exc).__name__}: {exc}")

    def on_full_backup_activity_result(self, request_code, result_code, intent):
        if int(request_code) != FULL_BACKUP_PICK_REQUEST:
            return
        try:
            android_activity.unbind(on_activity_result=self.on_full_backup_activity_result)
        except Exception:
            pass
        try:
            Activity = autoclass("android.app.Activity")
            if int(result_code) != int(Activity.RESULT_OK) or intent is None:
                return
            uri = intent.getData()
            if uri is None:
                return
            uri_text = str(uri.toString())
            Clock.schedule_once(lambda *_: self._restore_full_backup_uri(uri_text), 0)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            Clock.schedule_once(lambda *_args, text=message: self.info("读取备份失败", text), 0)

    def _restore_full_backup_uri(self, uri_text):
        """Copy a SAF URI to a temporary local ZIP, then preview before restoring."""
        archive_path = self.storage.backup_dir / f"restore_{uuid4().hex}.zip"
        partial_path = archive_path.with_suffix(".zip.part")
        storage = self.storage

        def worker():
            try:
                Uri = autoclass("android.net.Uri")
                copy_uri_to_path(Uri.parse(str(uri_text)), partial_path)
                os.replace(partial_path, archive_path)
                return str(archive_path)
            finally:
                try:
                    partial_path.unlink(missing_ok=True)
                except OSError:
                    pass

        started = self.run_background_task(
            "正在读取备份文件", worker,
            on_success=lambda path: self._preview_full_backup_restore(Path(path), delete_after=True),
            on_error=lambda exc: self.info("读取备份失败", f"{type(exc).__name__}: {exc}"),
        )
        if not started:
            for path in (partial_path, archive_path):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _restore_local_backup(self, path, popup=None):
        self._preview_full_backup_restore(Path(path), picker_popup=popup, delete_after=False)

    def _preview_full_backup_restore(self, path, picker_popup=None, delete_after=False):
        """Read and verify a candidate ZIP, without changing the active data."""
        if picker_popup:
            picker_popup.dismiss()
        path = Path(path)

        def worker():
            return self.storage.inspect_full_backup(path)

        def complete(summary):
            self._show_full_backup_confirmation(path, summary, delete_after)

        def failed(exc):
            if delete_after:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            self.info("备份检查失败", f"{type(exc).__name__}: {exc}\n\n当前数据没有被覆盖。")

        started = self.run_background_task("正在校验备份和照片文件", worker,
                                           on_success=complete, on_error=failed)
        if not started and delete_after:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _show_full_backup_confirmation(self, path, summary, delete_after):
        size_mb = summary["archive_bytes"] / (1024 * 1024)
        range_text = "暂无体重记录"
        if summary.get("records"):
            range_text = f"{summary.get('first_record') or '未知'} 至 {summary.get('last_record') or '未知'}"
        free_mb = summary.get("free_bytes", 0) / (1024 * 1024)
        estimated_mb = summary.get("estimated_peak_bytes", summary.get("unpacked_bytes", 0)) / (1024 * 1024)
        space_sufficient = bool(summary.get("space_sufficient", True))
        space_text = (
            f"存储检查：当前可用 {free_mb:.1f} MB，预计峰值需要约 {estimated_mb:.1f} MB。"
            if summary.get("free_bytes") is not None else "存储检查：恢复前会再次检查可用空间。"
        )
        if not space_sufficient:
            space_text += "\n可用空间不足，请先清理空间后重新选择备份。"
        preview_text = (
            f"备份文件：{path.name}\n文件大小：{size_mb:.1f} MB\n"
            f"体重记录：{summary['records']} 条（{range_text}）\n"
            f"体型照片：{summary['photos']} 张\n训练打卡天数：{summary['workout_days']} 天\n"
            f"饮食记录：{summary.get('food_logs', 0)} 条 · 训练日志：{summary.get('strength_logs', 0)} 项\n"
            f"身体测量：{summary.get('body_measurements', 0)} 条\n"
            f"{space_text}\n\n"
            "确认后，以上内容会覆盖当前应用数据。恢复前会先创建当前数据保护备份；"
            "恢复过程中会再次校验备份和存储空间。"
        )
        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        content.add_widget(self.label(preview_text, 11, TEXT))
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        popup = Popup(title="确认覆盖恢复？", title_font=FONT_NAME, content=content,
                      size_hint=(.94, None), height=dp(390), background="",
                      separator_color=(0, 0, 0, 0), auto_dismiss=False)

        def cleanup_temp():
            if delete_after:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

        def cancel(*_):
            popup.dismiss()
            cleanup_temp()

        def confirm(*_):
            popup.dismiss()

            def restore_worker():
                try:
                    return self.storage.restore_full_backup(path)
                finally:
                    cleanup_temp()

            if not self._run_full_backup_restore(restore_worker):
                cleanup_temp()

        actions.add_widget(self.button("取消，不覆盖", cancel, 44, tone="secondary"))
        confirm_button = self.button("确认恢复" if space_sufficient else "空间不足", confirm, 44, tone="primary")
        confirm_button.disabled = not space_sufficient
        actions.add_widget(confirm_button)
        content.add_widget(actions)
        popup.open()

    def _run_full_backup_restore(self, worker):
        def complete(result):
            self._reload_runtime_settings_after_restore()
            self._calendar_cache_month = None
            self._calendar_cache_workouts = {}
            self._calendar_cache_photo_counts = {}
            self._calendar_total_photo_count = None
            self._thumbnail_failed_ids.clear()
            self._thumbnail_recovery_attempts.clear()
            self.refresh()
            self.refresh_profile_summary()
            if getattr(self, "calendar_grid", None) is not None:
                self.render_calendar()
                self.refresh_calendar_photo_data(
                    preferred_date=getattr(self, "calendar_selected_date", datetime.now().date())
                )
            if getattr(self, "photo_browser_card", None) is not None:
                self.invalidate_photo_browser_cache()
                self.refresh_photo_browser(preferred_date=getattr(self, "progress_filter_date", None))
            self.info(
                "恢复完成",
                f"已恢复 {result['records']} 条体重记录、{result['photos']} 张照片、"
                f"{result.get('food_logs', 0)} 条饮食、{result.get('strength_logs', 0)} 项训练及"
                f"{result.get('body_measurements', 0)} 条身体测量。\n"
                f"恢复前保护备份：{result['safety_backup'].name}"
            )

        # Bump before the swap so thumbnail workers from the previous dataset
        # are invalidated. The actual restore still happens in a worker thread.
        if getattr(self, "_background_task_busy", False):
            self.info("正在处理中", "上一项操作尚未完成，请稍候再试。")
            return False
        self._photo_storage_generation = getattr(self, "_photo_storage_generation", 0) + 1
        self._thumbnail_jobs.clear()
        if hasattr(self, "invalidate_photo_browser_cache"):
            self.invalidate_photo_browser_cache()
        storage_lock = getattr(self, "_photo_storage_lock", None)

        def serialized_worker():
            if storage_lock is None:
                return worker()
            with storage_lock:
                return worker()

        return self.run_background_task(
            "正在验证并恢复完整备份", serialized_worker, on_success=complete,
            on_error=lambda exc: self.info(
                "恢复失败", f"{type(exc).__name__}: {exc}\n\n当前数据已尽力回滚保护。"
            )
        )

    def _reload_runtime_settings_after_restore(self):
        """Reload every DB-backed preference and synchronize any live controls."""
        values = self.storage.get_settings()
        try:
            days = int(values.get("window_days") or 30)
            self.window_days = days if days in (7, 14, 30, 60, 90, 180, 365) else 30
        except (TypeError, ValueError):
            self.window_days = 30
        self.end_date = datetime.now().date()
        try:
            self.height_cm = self.storage.validate_height_cm(values["height_cm"]) if values.get("height_cm") else None
        except (TypeError, ValueError):
            self.height_cm = None
            self.storage.set_setting("height_cm", None)
        try:
            self.target_weight = self.storage.validate_target_weight(values["target_weight"]) if values.get("target_weight") else None
        except (TypeError, ValueError):
            self.target_weight = None
            self.storage.set_setting("target_weight", None)
        self.theme = values.get("theme") or "深色"
        self.show_bmi = self._parse_bool_setting(values.get("show_bmi"), default=False) and bool(self.height_cm)
        self.show_labels = self._parse_bool_setting(values.get("show_labels"), default=False)
        self.weight_unit = normalize_weight_unit(values.get("weight_unit"))
        unit_spinner = getattr(self, "weight_unit_spinner", None)
        if unit_spinner is not None:
            self._syncing_weight_unit = True
            try:
                unit_spinner.text = self.weight_unit
            finally:
                self._syncing_weight_unit = False
        if not self.height_cm and self._parse_bool_setting(values.get("show_bmi"), default=False):
            self.storage.set_setting("show_bmi", False)

        spinner = getattr(self, "days_spinner", None)
        if spinner is not None:
            spinner.text = str(self.window_days)
        bmi_cb = getattr(self, "bmi_cb", None)
        if bmi_cb is not None:
            self._syncing_bmi_checkbox = True
            try:
                bmi_cb.active = self.show_bmi
            finally:
                self._syncing_bmi_checkbox = False
        labels_cb = getattr(self, "labels_cb", None)
        if labels_cb is not None:
            self._syncing_labels_checkbox = True
            try:
                labels_cb.active = self.show_labels
            finally:
                self._syncing_labels_checkbox = False

    def open_recycle(self, *_):
        """Open one persistent recycle-bin dialog and render an explicit empty state."""
        current = getattr(self, "_recycle_popup", None)
        if current is not None and getattr(current, "is_open", False):
            self._refresh_recycle_list()
            return

        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3))
        box = GridLayout(cols=1, size_hint_y=None, spacing=dp(6), padding=(0, dp(2)))
        box.bind(minimum_height=box.setter("height"))
        scroll.add_widget(box)
        root.add_widget(scroll)
        popup = Popup(title="回收站", title_font=FONT_NAME, content=root,
                      size_hint=(.95, .8), background="", separator_color=(0, 0, 0, 0))
        close_button = self.button("关闭", lambda *_: popup.dismiss(), 44)
        root.add_widget(close_button)
        self._recycle_popup = popup
        self._recycle_list_box = box
        popup.bind(on_dismiss=self._on_recycle_dismiss)
        popup.open()
        self._refresh_recycle_list()

    def _on_recycle_dismiss(self, popup, *_args):
        if getattr(self, "_recycle_popup", None) is popup:
            self._recycle_popup = None
            self._recycle_list_box = None

    def _refresh_recycle_list(self):
        """Refresh the existing dialog in-place instead of stacking stale windows."""
        box = getattr(self, "_recycle_list_box", None)
        popup = getattr(self, "_recycle_popup", None)
        if box is None or popup is None or not getattr(popup, "is_open", False):
            return
        box.clear_widgets()
        try:
            rows = self.storage.recycle()
        except Exception as exc:
            message = self.label(f"读取回收站失败：{exc}", 12, MUTED)
            message.size_hint_y = None
            message.height = dp(64)
            box.add_widget(message)
            return

        if not rows:
            empty = BoxLayout(orientation="vertical", padding=(dp(10), dp(24)), spacing=dp(8),
                              size_hint_y=None, height=dp(110))
            empty.add_widget(self.label("回收站为空", 15, TEXT, True))
            empty.add_widget(self.label("删除的体重记录会显示在这里，方便恢复。", 11, MUTED))
            box.add_widget(empty)
            return

        for row in rows:
            line = BoxLayout(size_hint_y=None, height=dp(76), spacing=dp(6))
            description = f"{self.display_weight(float(row['weight'])):.1f} {self.weight_unit_label()} · {row['recorded_at']}\n删除时间：{row['deleted_at']}"
            label = self.label(description, 10, TEXT)
            label.halign = "left"
            label.valign = "middle"
            label.bind(size=lambda widget, size: setattr(widget, "text_size", (size[0], None)))
            label.size_hint_x = 0.50
            line.add_widget(label)
            restore_button = self.button("恢复", lambda _btn, rid=row["id"]: self.restore_recycle(rid),
                                         44, tone="secondary")
            restore_button.size_hint_x = 0.22
            line.add_widget(restore_button)
            delete_button = self.button("永久删除", lambda _btn, rid=row["id"]: self.perm_recycle(rid),
                                        44, tone="secondary")
            delete_button.size_hint_x = 0.28
            line.add_widget(delete_button)
            box.add_widget(line)

    def restore_recycle(self, rid):
        try:
            self.storage.restore(rid)
            # Refresh the chart/data and the existing modal's list in place.
            self.refresh()
            self._refresh_recycle_list()
            self.info("恢复成功", "这条记录已恢复到体重历史记录中。")
        except Exception as exc:
            self.info("恢复失败", str(exc))

    def perm_recycle(self, rid):
        """Require an explicit confirmation before the irreversible recycle-bin delete."""
        rows = self.storage.recycle()
        row = next((item for item in rows if int(item["id"]) == int(rid)), None)
        if row is None:
            self._refresh_recycle_list()
            self.info("记录已不存在", "回收站已更新，请重新选择记录。")
            return

        body = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
        body.add_widget(self.label(
            f"确定永久删除这条 {self.display_weight(float(row['weight'])):.1f} {self.weight_unit_label()} 的记录吗？", 13, TEXT, True
        ))
        body.add_widget(self.label("永久删除后无法从回收站恢复。系统会先保存数据库保护备份。", 11, MUTED))
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        confirm = Popup(title="确认永久删除", title_font=FONT_NAME, content=body,
                        size_hint=(.9, None), height=dp(205), background="",
                        separator_color=(0, 0, 0, 0), auto_dismiss=False)
        actions.add_widget(self.button("取消", lambda *_: confirm.dismiss(), 44, tone="secondary"))

        def start_delete(*_args):
            confirm.dismiss()

            def worker():
                self.storage.permanently_delete(rid)
                return int(rid)

            def complete(_value):
                self._refresh_recycle_list()
                self.info("已永久删除", "记录已永久删除，删除前的数据库保护备份已保存。")

            self.run_background_task(
                "正在备份并永久删除记录", worker, on_success=complete,
                on_error=lambda exc: self.info("永久删除失败", f"{type(exc).__name__}: {exc}"),
            )

        actions.add_widget(self.button("确认永久删除", start_delete, 44, tone="primary"))
        body.add_widget(actions)
        confirm.open()

    def info(self, title, message):
        """Show a wrapped, dark-themed message dialog with a clear dismissal action."""
        from ui.theme import CARD

        body = BoxLayout(orientation="vertical", padding=(dp(16), dp(14)), spacing=dp(12))
        message_label = Label(
            text=str(message),
            color=TEXT,
            font_name=FONT_NAME,
            halign="left",
            valign="middle",
            size_hint_y=1,
        )
        message_label.bind(
            width=lambda widget, width: setattr(widget, "text_size", (max(1, width), None))
        )
        body.add_widget(message_label)

        popup = Popup(
            title=title,
            title_font=FONT_NAME,
            title_color=TEXT,
            content=body,
            size_hint=(.90, None),
            height=dp(250),
            background="atlas://data/images/defaulttheme/modalview-background",
            background_color=CARD,
            separator_color=(0, 0, 0, 0),
            auto_dismiss=True,
        )
        body.add_widget(self.button("知道了", lambda *_: popup.dismiss(), 44, tone="primary"))
        popup.open()
