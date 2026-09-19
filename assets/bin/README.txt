# Place portable FFmpeg binaries here for the packaged app.
#
# The app looks for ffmpeg/ffprobe in this order:
#   1. assets/bin/ffmpeg(.exe) next to the executable (portable installer)
#   2. system PATH (developer machines — e.g. gyan.dev builds)
#
# For a release build, drop these two files in this folder before running
# PyInstaller (see docs/RELEASE_FA.md):
#   assets/bin/ffmpeg.exe
#   assets/bin/ffprobe.exe
# from https://www.gyan.dev/ffmpeg/builds/ (ffmpeg-release-essentials.zip)
#
# This folder intentionally contains no binaries in git (see .gitignore):
# they are ~80MB and are added at build time on the release machine / CI.
