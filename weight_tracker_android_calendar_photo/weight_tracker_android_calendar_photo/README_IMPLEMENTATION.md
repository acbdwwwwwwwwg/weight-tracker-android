# 日历 / 健身 / 体型照片功能完整实现包

这个包是在当前 Run #11 成功的 APK 工具链基础上，新增以下功能：

- 月历浏览与前后月份切换
- 点击日期
- 每天记录是否健身，日历显示 `✓`
- 每天可保存多张体型照片
- Android 13+ 使用系统 Photo Picker；较低版本使用 ACTION_OPEN_DOCUMENT 回退
- 选择的照片会复制到 App 专属 `body_photos/` 目录，不依赖原图库路径
- 所有体型照片按日期+时间从早到晚排列
- 下方使用 Kivy Carousel，左右滑动浏览全部照片
- Carousel 只加载当前页及相邻页的图片，降低大量照片导致的内存压力
- 可删除当前照片
- 可跳转到所选日期的第一张照片
- 可创建包含 SQLite 数据库和所有照片的完整 ZIP 备份
- 保留之前的中文字体修复

## 替换文件

把下面三个文件替换到现有项目中：

```text
weight_tracker_android_project/weight_tracker_android/main.py
weight_tracker_android_project/weight_tracker_android/storage.py
weight_tracker_android_project/weight_tracker_android/buildozer.spec
```

并确保字体存在：

```text
weight_tracker_android_project/weight_tracker_android/fonts/NotoSansCJKsc-Regular.ttf
```

不要删除现有 GitHub Actions 中已经验证成功的 Java 17 环境设置：

```yaml
env:
  JAVA_HOME: /usr/lib/jvm/temurin-17-jdk-amd64
```

## 数据库新增表

```sql
CREATE TABLE IF NOT EXISTS daily_activity (
    date TEXT PRIMARY KEY,
    workout INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS body_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_date TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

旧的 `records`、`recycle_bin`、`settings` 数据不会被删除，首次启动会自动补建新表。

## 新照片目录

```text
App 数据目录/
├── weight_tracker.db
├── body_photos/
│   ├── 20261007_220801_xxxxxxxx.jpg
│   └── ...
└── backup/
```

## 构建

仍使用原来的命令：

```bash
buildozer -v android debug
```

本包没有修改已经验证成功的：

```text
Ubuntu 22.04
Python 3.11
Java 17
Android API 35
minapi 24
arm64-v8a
p4a develop + 固定 commit
```

## 本地静态检查

本包已经通过：

```bash
python -m py_compile main.py storage.py
```

并对 Storage 的新表、健身记录、照片索引、删除照片、完整备份流程做了独立 SQLite/文件系统测试。

Android 端照片选择使用 `android.activity` 的 `on_activity_result` 回调；python-for-android 文档说明该接口由默认 `PythonActivity` 提供。Android 官方 Photo Picker 在不可用时推荐回退到 `ACTION_OPEN_DOCUMENT`。
