# 体重追踪助手 Android 版

这是根据原桌面版 Python 程序重构的 Android 工程。核心改动：

- Tkinter/ttkbootstrap → Kivy Android UI
- CSV 主数据库 → SQLite，本地单文件数据库
- 操作前自动备份数据库，保留最近 10 份
- 删除、恢复、永久删除均通过事务更新数据库
- ID 使用 SQLite 自增，不再因为删除而复用
- 体重/身高/目标体重拒绝非正数和 NaN/Inf
- 统计范围与图表范围统一
- 同一天可以保存多个不同时间的测量
- 编辑时可以修改日期时间、体重和备注
- CSV 导出使用 UTF-8-SIG，方便 Windows Excel 打开
- CSV 导入会跳过完全重复记录，并返回失败行信息（底层已实现）

## 说明

当前环境没有 Android SDK/NDK 和 Buildozer，所以这里生成的是**可编译的 Android 工程源码**，不能在当前容器直接产出最终 APK。

### 在 Linux / WSL2 构建

```bash
python3 -m pip install --upgrade buildozer cython
buildozer android debug
```

APK 通常会出现在：

```text
bin/weighttracker-1.0.0-arm64-v8a_armeabi-v7a-debug.apk
```

### GitHub Actions

项目附带 `.github/workflows/build-apk.yml`，可以把工程上传到 GitHub 后自动构建 APK。

## 当前 Android 版限制

为了保证第一版构建链稳定，当前导入按钮还没有接 Android 系统文件选择器；导入的数据层已经实现，下一步可以接 ACTION_OPEN_DOCUMENT。导出文件暂存于应用私有目录。
