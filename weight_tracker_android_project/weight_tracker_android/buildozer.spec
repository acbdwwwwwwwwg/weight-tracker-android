[app]
title = 体重追踪助手
package.name = weighttracker
package.domain = org.local
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,csv,db,md,ttf
version = 1.0.0
requirements = python3,kivy,charset-normalizer==2.1.1
orientation = portrait
fullscreen = 0

android.api = 35
android.minapi = 24
android.archs = arm64-v8a

p4a.branch = develop
p4a.commit = 94ffd5f31d816414ad1fe66c0fe587c61daac757

android.permissions = READ_MEDIA_IMAGES,READ_MEDIA_VIDEO,READ_MEDIA_AUDIO
android.allow_backup = True
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 0
