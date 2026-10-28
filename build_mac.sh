#!/bin/sh
# Builds "dist/F1 Telemetry Hub.app" and dist/F1TelemetryHub-mac.dmg. Run it on a Mac: PyInstaller can't build Mac
# apps anywhere else (the GitHub workflow does it on GitHub's Macs). For an app that runs on Apple silicon and
# Intel Macs, use the python.org installer's Python (or set F1TH_ARCH=arm64 / x86_64 for one kind of Mac):
#   F1TH_PYTHON=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 ./build_mac.sh
set -eu
cd "$(dirname "$0")"
PY="${F1TH_PYTHON:-python3}"
APP="dist/F1 Telemetry Hub.app"
DMG="dist/F1TelemetryHub-mac.dmg"

if pgrep -x F1TelemetryHub >/dev/null; then
  echo "F1 Telemetry Hub is running. Quit it first, then build again."
  exit 1
fi
"$PY" -m PyInstaller --version >/dev/null 2>&1 || "$PY" -m pip install pyinstaller
"$PY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/macos.spec

# Apple silicon only runs signed code: without a Developer ID, sign the whole app ad hoc, then check it
if [ -z "${F1TH_SIGN_IDENTITY:-}" ]; then
  codesign --force --deep --sign - "$APP"
fi
codesign --verify --deep --strict "$APP"
lipo -archs "$APP/Contents/MacOS/F1TelemetryHub"

rm -rf build/dmg "$DMG"
mkdir -p build/dmg
cp -R "$APP" build/dmg/
ln -s /Applications build/dmg/Applications
# hdiutil now and then reports the new volume as busy; a second try works
for i in 1 2 3; do
  hdiutil create -volname "F1 Telemetry Hub" -srcfolder build/dmg -fs HFS+ -format UDZO -ov "$DMG" && break
  sleep 5
done
test -f "$DMG"
echo "Built $APP and $DMG"
