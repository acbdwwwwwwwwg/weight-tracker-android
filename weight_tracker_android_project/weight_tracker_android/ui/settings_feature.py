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

from services.android_bridge import (
    ANDROID_AVAILABLE, ANDROID_IMPORT_ERROR, IS_ANDROID, CSV_PICK_REQUEST,
    FULL_BACKUP_PICK_REQUEST, android_activity, autoclass, copy_uri_to_path,
    get_current_activity,
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
        x = float(v)
        if not (x > 0 and x == x and x != float("inf") and x != float("-inf")):
            raise ValueError("身高必须是大于 0 的有限数字")
        self.height_cm = x
        self.storage.set_setting("height_cm", x)
        self.refresh()
        self.refresh_profile_summary()

    def ask_target(self, *_):
        self.input_setting("保存目标体重(斤)", self.target_weight, lambda v: self.set_target(v))

    def set_target(self, v):
        if str(v).strip() == "":
            self.target_weight = None
            self.storage.set_setting("target_weight", None)
        else:
            x = float(v)
            if not (x > 0 and x == x and x != float("inf") and x != float("-inf")):
                raise ValueError("目标体重必须是大于 0 的有限数字")
            self.target_weight = x
            self.storage.set_setting("target_weight", x)
        self.refresh()
        self.refresh_profile_summary()

    def input_setting(self, title, value, callback):
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        inp = self._field(text="" if value is None else str(value))
        content.add_widget(inp)
        btn = self.button("保存", lambda *_: self._save_setting_popup(popup, inp.text, callback), 42)
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
        path = Path(self.user_data_dir) / f"weight_export_{datetime.now():%Y%m%d_%H%M%S}.csv"
        try:
            self.storage.export_csv(path, self.rows)
            self.info("导出完成", f"文件已保存到应用数据目录：\n{path.name}\n\n可在系统文件管理器中访问或导出。")
        except Exception as e:
            self.info("导出失败", str(e))

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
            details = f"新增 {inserted} 条，跳过重复 {skipped} 条，失败 {len(failed)} 行。"
            if failed:
                details += "\n前 5 个错误：\n" + "\n".join(
                    f"第 {line} 行：{reason}" for line, reason in failed[:5]
                )
            self.info("CSV 导入完成", details)

        self.run_background_task("正在读取并导入 CSV", worker, on_success=complete,
                                 on_error=lambda exc: self.info("CSV 导入失败", f"{type(exc).__name__}: {exc}"))

    def restore_full_backup(self, *_):
        """Choose a ZIP from Android documents or an existing app-private snapshot."""
        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        content.add_widget(self.label("恢复会替换当前记录、设置、健身打卡和体型照片。恢复前会自动生成一份当前数据保护备份。", 12))
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
            items.add_widget(self.button(detail, lambda _btn, selected=path: self._restore_local_backup(selected, popup), 46, tone="secondary"))
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
        archive_path = self.storage.backup_dir / f"restore_{uuid4().hex}.zip"
        partial_path = archive_path.with_suffix(".zip.part")
        storage = self.storage

        def worker():
            try:
                Uri = autoclass("android.net.Uri")
                copy_uri_to_path(Uri.parse(str(uri_text)), partial_path)
                os.replace(partial_path, archive_path)
                return storage.restore_full_backup(archive_path)
            finally:
                for path in (partial_path, archive_path):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass

        self._run_full_backup_restore(worker)

    def _restore_local_backup(self, path, popup=None):
        if popup:
            popup.dismiss()
        self._run_full_backup_restore(lambda: self.storage.restore_full_backup(path))

    def _run_full_backup_restore(self, worker):
        def complete(result):
            # The trend refresh owns record reloading asynchronously; do not query
            # the entire records table again on the UI thread after a restore.
            self._calendar_cache_month = None
            self._calendar_cache_workouts = {}
            self._calendar_cache_photo_counts = {}
            self._calendar_total_photo_count = None
            self.refresh()
            self.refresh_profile_summary()
            if getattr(self, "calendar_grid", None) is not None:
                self.render_calendar()
                self.refresh_calendar_photo_data(preferred_date=getattr(self, "calendar_selected_date", datetime.now().date()))
            if getattr(self, "photo_browser_card", None) is not None:
                self.invalidate_photo_browser_cache()
                self.refresh_photo_browser(preferred_date=getattr(self, "progress_filter_date", None))
            self.info("恢复完成", f"已恢复 {result['records']} 条体重记录和 {result['photos']} 张照片。\n恢复前保护备份：{result['safety_backup'].name}")

        self.run_background_task("正在验证并恢复完整备份", worker, on_success=complete,
                                 on_error=lambda exc: self.info("恢复失败", f"{type(exc).__name__}: {exc}\n\n当前数据已尽力回滚保护。"))

    def open_recycle(self, *_):
        rows = self.storage.recycle()
        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(5))
        scroll = ScrollView()
        box = GridLayout(cols=1, size_hint_y=None, spacing=dp(5))
        box.bind(minimum_height=box.setter("height"))
        for r in rows:
            line = BoxLayout(size_hint_y=None, height=dp(74), spacing=dp(4))
            text = f"#{r['original_id']}  {float(r['weight']):.1f}斤\n{r['recorded_at']}\n删除：{r['deleted_at']}"
            line.add_widget(self.label(text, 11))
            line.add_widget(self.button("恢复", lambda _, x=r['id']: self.restore_recycle(x), 40))
            line.add_widget(self.button("永久删除", lambda _, x=r['id']: self.perm_recycle(x), 40))
            box.add_widget(line)
        scroll.add_widget(box)
        root.add_widget(scroll)
        root.add_widget(self.button("关闭", lambda *_: popup.dismiss(), 42))
        popup = Popup(title="回收站", title_font=FONT_NAME, content=root, size_hint=(.95, .8), background="", separator_color=(0, 0, 0, 0))
        popup.open()

    def restore_recycle(self, rid):
        try:
            self.storage.restore(rid)
            self.refresh()
            self.open_recycle()
        except Exception as e:
            self.info("恢复失败", str(e))

    def perm_recycle(self, rid):
        def worker():
            self.storage.permanently_delete(rid)
            return int(rid)
        self.run_background_task(
            "正在备份并永久删除记录",
            worker,
            on_success=lambda _value: self.info("已永久删除", "记录已永久删除，删除前的数据库快照已保存。"),
        )

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
