# PyInstaller spec: one-folder build (fast start-up; OCR engine files stay as plain files).
# Build with build_exe.bat, which also verifies the result.
from pathlib import Path

ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "vendor" / "tesseract"), "vendor/tesseract"),
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "build" / "licenses"), "licenses"),
]

excludes = [
    "tkinter", "unittest", "pydoc_data", "test", "lib2to3", "pytest", "_pytest", "pytestqt",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtDesigner", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtConcurrent", "PySide6.QtDBus",
    "PySide6.QtHelp", "PySide6.QtPrintSupport", "PySide6.QtXml", "PySide6.QtUiTools",
    "PIL._avif", "ssl", "_ssl",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    excludes=excludes,
    noarchive=False,
)
# PyInstaller analyses binaries found in data folders and would copy the whole
# Tesseract DLL set a second time into _internal; tesseract.exe loads them from
# its own folder, so drop those duplicates. Also drop Qt parts TextSnap never
# loads (software OpenGL, Qt's own translations, TLS / network-information).
VENDOR_DLLS = {p.name.lower() for p in (ROOT / "vendor" / "tesseract").glob("*.dll")}
UNUSED = ("opengl32sw.dll", "/translations/", "/plugins/tls/", "/plugins/networkinformation/")


def keep(entry) -> bool:
    dest = entry[0].replace("\\", "/").lower()
    if dest.startswith("vendor/"):
        return True
    if "/" not in dest and dest in VENDOR_DLLS:
        return False
    return not any(u in "/" + dest for u in UNUSED)


a.binaries = [b for b in a.binaries if keep(b)]
a.datas = [d for d in a.datas if keep(d)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TextSnap",
    icon=str(ROOT / "assets" / "textsnap.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
    console=False,
    upx=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="TextSnap", upx=False)
