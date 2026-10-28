# PyInstaller spec for the Mac app, "F1 Telemetry Hub.app". build_mac.sh runs it, on a Mac: PyInstaller can't
# build Mac apps anywhere else. The app is a folder bundle rather than one file, as PyInstaller recommends for
# Mac apps. F1TH_ARCH picks the processor (default universal2: Apple silicon and Intel in one app, which needs
# the python.org installer's Python). F1TH_SIGN_IDENTITY signs with a Developer ID instead of ad hoc.
import os
import sys

ROOT = os.path.dirname(SPECPATH)
sys.path.insert(0, ROOT)
from f1telemetry import APP_NAME, __version__  # noqa: E402

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "f1telemetry", "web"), "web"),
           (os.path.join(ROOT, "f1telemetry", "circuits.json"), "."),
           (os.path.join(ROOT, "GUIDE.md"), ".")],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="F1TelemetryHub",
    console=False,
    target_arch=os.environ.get("F1TH_ARCH") or "universal2",
    codesign_identity=os.environ.get("F1TH_SIGN_IDENTITY") or None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="F1TelemetryHub")
app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=os.path.join(ROOT, "assets", "app.icns"),
    bundle_identifier="io.github.williamcheong0616.f1telemetryhub",
    version=__version__,
    info_plist={
        "CFBundleDisplayName": APP_NAME,
        "CFBundleVersion": __version__,
        "LSMinimumSystemVersion": "10.13",
        "LSApplicationCategoryType": "public.app-category.sports",
        "NSHumanReadableCopyright": "MIT licence. Not affiliated with EA or Formula 1.",
        # App Nap would slow the app down whenever its window is hidden, as it is behind the dashboard
        "NSAppSleepDisabled": True,
        # macOS asks before the app sends to other devices, which only Settings > Forward UDP to does
        "NSLocalNetworkUsageDescription": "F1 Telemetry Hub passes the game's telemetry on to the devices "
                                          "you list under Forward UDP to.",
    },
)
