[app]

title = NEON VOID
package.name = neonvoid
package.domain = com.skysoftly

source.dir = .
source.include_exts = py,json,txt,png,jpg,ttf,otf
source.exclude_dirs = .git,.github,tests,build,dist,bin,__pycache__

version = 0.1.0
requirements = python3,pygame
orientation = landscape
fullscreen = 1

android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE
android.api = 35
android.minapi = 23
android.archs = arm64-v8a
android.accept_sdk_license = True

p4a.bootstrap = sdl2
p4a.branch = master

[buildozer]
log_level = 2
warn_on_root = 1
