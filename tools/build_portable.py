"""Build dist/TextSnap-Portable: a Smart App Control friendly portable folder.

Windows Smart App Control (and other application-control policies) block
unsigned executables without reputation - which includes every freshly built
PyInstaller bootloader. This layout contains no newly built executable at
all: TextSnap's Python code runs on the official, PSF-signed Python
embeddable runtime, next to the unmodified PyPI wheel binaries and the
UB Mannheim-signed Tesseract.

    TextSnap-Portable/
      TextSnap.bat         launcher (starts runtime/pythonw.exe app/main.py)
      runtime/             python-3.x-embed-amd64 + Lib/site-packages
      app/                 textsnap package, main.py, assets, vendor/tesseract, docs, licenses

Usage: python tools/build_portable.py [--embed-zip PATH] [--out DIR]
An existing output folder is replaced only when nothing runs from it.
The embeddable zip is downloaded from python.org when not given; its SHA-256
is pinned and the extracted python.exe/pythonw.exe must carry a valid
Python Software Foundation signature.
"""

from __future__ import annotations

import compileall
import hashlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "TextSnap-Portable"
EMBED = {
    "3.14.5": ("https://www.python.org/ftp/python/3.14.5/python-3.14.5-embed-amd64.zip",
               "ba6bd811c4eedb19195cf275770ef127e893d63701e24152606e2cb76f6d876a"),
}
PACKAGES = ["PySide6_Essentials", "shiboken6", "numpy", "pillow", "pypdfium2", "zxing-cpp"]
SKIP_PARTS = {"__pycache__", "tests", "include", "typesystems", "glue", "scripts", "translations", "qml",
              "doc", "examples", "f2py", "_pyinstaller"}
SKIP_NAMES = {"opengl32sw.dll"}
SKIP_SUFFIXES = {".exe", ".pyi", ".h", ".hpp", ".lib", ".a", ".cmake"}
PTH = "python{v}.zip\n.\nLib\\site-packages\n..\\app\nimport site\n"
LAUNCHER = ('@echo off\r\n'
            'rem Starts TextSnap with the bundled, signed Python runtime (no console window).\r\n'
            'start "" "%~dp0runtime\\pythonw.exe" "%~dp0app\\main.py" %*\r\n')


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def signer(path: Path) -> str:
    """Authenticode status and signer, via the standard PowerShell cmdlet (build time only)."""
    ps = (f"$s = Get-AuthenticodeSignature -LiteralPath '{path}'; "
          "\"$($s.Status)|$($s.SignerCertificate.Subject)\"")
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    return out


def embed_zip(arg: str | None, tmp: Path) -> Path:
    version = ".".join(map(str, sys.version_info[:3]))
    if version not in EMBED:
        raise SystemExit(f"no pinned embeddable runtime for Python {version}; add it to EMBED")
    url, digest = EMBED[version]
    path = Path(arg) if arg else tmp / Path(url).name
    if not arg:
        print(f"downloading {url}")
        with urllib.request.urlopen(url, timeout=120) as r, open(path, "wb") as f:
            shutil.copyfileobj(r, f)
    if sha256(path) != digest:
        raise SystemExit(f"hash mismatch for {path.name}")
    return path


# PySide6 Essentials ships the whole QML/Quick stack; TextSnap needs only these.
QT_MODULES = {"Core", "Gui", "Widgets", "Network", "Svg"}
QT_PLUGINS = {"platforms", "imageformats", "styles", "iconengines"}


def keep_pyside(rel: Path) -> bool:
    name = rel.name
    if len(rel.parts) == 2 and rel.suffix.lower() in (".dll", ".pyd"):
        if name.startswith("Qt6"):
            return name[3:-4] in QT_MODULES
        if name.startswith("Qt") and rel.suffix.lower() == ".pyd":
            return name[2:-4] in QT_MODULES - {"Svg"}
        return name != "pyside6qml.abi3.dll"  # pyside6.abi3.dll and the MSVC runtime
    if len(rel.parts) > 2 and rel.parts[1] == "plugins":
        return rel.parts[2] in QT_PLUGINS
    return True


def keep(rel: Path) -> bool:
    parts = set(rel.parts)
    if parts & SKIP_PARTS or rel.name.lower() in SKIP_NAMES or rel.suffix.lower() in SKIP_SUFFIXES:
        return False
    return keep_pyside(rel) if rel.parts[0] == "PySide6" else True


def copy_packages(site: Path) -> int:
    count = 0
    for name in PACKAGES:
        dist = metadata.distribution(name)
        for f in dist.files or []:
            rel = Path(*f.parts)
            if rel.parts[0] == ".." or not keep(rel):
                continue
            src = Path(f.locate())
            if src.is_file():
                dest = site / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                count += 1
    return count


def file_in_use(folder: Path) -> Path | None:
    """The first executable or DLL inside ``folder`` that a running process has loaded, if any."""
    for path in folder.rglob("*"):
        if path.suffix.lower() in (".exe", ".dll", ".pyd") and path.is_file():
            try:
                with open(path, "r+b"):
                    pass
            except PermissionError:
                return path
    return None


def remove_previous(out: Path) -> None:
    """Delete an earlier build, but never one that is in use.

    Deleting file by file would remove the unlocked .py files of a TextSnap that is running from the folder
    before failing on its locked runtime (and Windows lets the folder be renamed meanwhile), so check first.
    """
    if not out.exists():
        return
    busy = file_in_use(out)
    if busy is not None:
        raise SystemExit(f"{out} is in use ({busy.name} is loaded by a running process - is TextSnap running "
                         f"from it?). Quit that TextSnap first, or build elsewhere with --out DIR.")
    shutil.rmtree(out)


def main() -> int:
    global OUT
    arg = sys.argv[sys.argv.index("--embed-zip") + 1] if "--embed-zip" in sys.argv else None
    if "--out" in sys.argv:
        OUT = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
    remove_previous(OUT)
    runtime, app = OUT / "runtime", OUT / "app"
    with tempfile.TemporaryDirectory(prefix="textsnap-portable-") as tmp:
        with zipfile.ZipFile(embed_zip(arg, Path(tmp))) as z:
            z.extractall(runtime)
    for exe in ("python.exe", "pythonw.exe"):
        status = signer(runtime / exe)
        if not status.startswith("Valid|") or "Python Software Foundation" not in status:
            raise SystemExit(f"{exe} is not validly signed by the PSF: {status}")
    v = f"{sys.version_info.major}{sys.version_info.minor}"
    (runtime / f"python{v}._pth").write_text(PTH.format(v=v), encoding="ascii")
    site = runtime / "Lib" / "site-packages"
    site.mkdir(parents=True)
    n = copy_packages(site)
    print(f"runtime packages: {n} files")

    app.mkdir()
    shutil.copytree(ROOT / "textsnap", app / "textsnap", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("main.py", "README.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, app / name)
    shutil.copytree(ROOT / "assets", app / "assets")
    shutil.copytree(ROOT / "vendor", app / "vendor")
    licenses = ROOT / "build" / "licenses"
    subprocess.run([sys.executable, str(ROOT / "tools" / "collect_licenses.py"), str(licenses)], check=True)
    shutil.copytree(licenses, app / "licenses")
    shutil.copy2(runtime / "LICENSE.txt", app / "licenses" / "Python-embeddable-LICENSE.txt")
    (OUT / "TextSnap.bat").write_bytes(LAUNCHER.encode("ascii"))
    compileall.compile_dir(str(app / "textsnap"), quiet=1)
    compileall.compile_dir(str(site), quiet=1, workers=0)
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"built {OUT} ({size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
