[app]
title = 体重追踪助手
package.name = weighttracker
package.domain = org.local
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,csv,db,md
version = 1.0.0
requirements = python3,kivy
orientation = portrait
fullscreen = 0
android.api = 35
android.minapi = 24
android.archs = arm64-v8a,armeabi-v7a
android.permissions = READ_MEDIA_IMAGES,READ_MEDIA_VIDEO,READ_MEDIA_AUDIO
android.allow_backup = True
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 0

