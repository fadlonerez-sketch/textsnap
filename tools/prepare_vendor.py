"""Prepare or verify the bundled OCR engine in vendor/tesseract.

    python tools/prepare_vendor.py           # download, check pinned hashes, extract, write manifest
    python tools/prepare_vendor.py --verify  # check vendor/tesseract against MANIFEST.json

Nothing is installed and no installer is run: the UB Mannheim NSIS
installer is unpacked with 7-Zip (itself unpacked from the official 7-Zip
release with 7zr.exe). Every download is checked against a pinned SHA-256
before use. Only tesseract.exe and the DLLs it imports (found by walking the
PE import tables) are kept, unmodified.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "tesseract"
MANIFEST = VENDOR / "MANIFEST.json"

DOWNLOADS = {
    "7zr.exe": ("https://github.com/ip7z/7zip/releases/download/26.04/7zr.exe",
                "256feca8e274e5da655e2a284fabafd9f554365eb164862089dacd4e8276d282"),
    "7z-x64.exe": ("https://github.com/ip7z/7zip/releases/download/26.04/7z2604-x64.exe",
                   "d54bf805f9f3704d1e8db2fa3498ae7ef2df0312b40b558e7c71c734430a665d"),
    "tesseract-setup.exe": (
        "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/"
        "tesseract-ocr-w64-setup-5.4.0.20240606.exe",
        "c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9"),
}
MODELS = {
    ("best", "eng"): "8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba",
    ("best", "heb"): "dbaa827aea6bc21215638447f17783a1004987c2d0bf5573d111fee397abdae5",
    ("fast", "eng"): "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    ("fast", "heb"): "11f9e43ab227f786352a50f75c94c2e9906f1baba86d93276da19da7ce0904db",
}
MODEL_URL = "https://github.com/tesseract-ocr/tessdata_{model}/raw/main/{lang}.traineddata"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, expected: str) -> None:
    print(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    actual = sha256(dest)
    if actual != expected:
        dest.unlink()
        raise SystemExit(f"hash mismatch for {dest.name}: {actual} (expected {expected})")


def dll_closure(folder: Path, start: str = "tesseract.exe") -> list[str]:
    import pefile
    local = {p.name.lower(): p.name for p in folder.iterdir() if p.is_file()}
    seen: set[str] = set()
    todo = [start.lower()]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        pe = pefile.PE(str(folder / local[name]), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            dll = entry.dll.decode().lower()
            if dll in local and dll not in seen:
                todo.append(dll)
        pe.close()
    return sorted(local[n] for n in seen)


def write_manifest() -> None:
    files = {str(p.relative_to(VENDOR)).replace("\\", "/"): sha256(p)
             for p in sorted(VENDOR.rglob("*")) if p.is_file() and p != MANIFEST}
    MANIFEST.write_text(json.dumps({"tesseract": "5.4.0.20240606 (UB Mannheim)", "files": files}, indent=1),
                        encoding="utf-8")
    print(f"manifest: {len(files)} files")


def verify() -> int:
    if not MANIFEST.exists():
        print("vendor/tesseract/MANIFEST.json missing - run tools/prepare_vendor.py")
        return 1
    files = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
    bad = [name for name, digest in files.items()
           if not (VENDOR / name).is_file() or sha256(VENDOR / name) != digest]
    if bad:
        print("vendor files missing or changed:", ", ".join(bad))
        return 1
    print(f"vendor/tesseract verified ({len(files)} files)")
    return 0


def prepare() -> int:
    with tempfile.TemporaryDirectory(prefix="textsnap-vendor-") as tmp:
        tmp_path = Path(tmp)
        dl = tmp_path / "downloads"
        dl.mkdir()
        for name, (url, digest) in DOWNLOADS.items():
            download(url, dl / name, digest)
        seven = tmp_path / "7zip"
        subprocess.run([str(dl / "7zr.exe"), "x", str(dl / "7z-x64.exe"), f"-o{seven}", "-y"],
                       check=True, stdout=subprocess.DEVNULL)
        tess = tmp_path / "tesseract"
        subprocess.run([str(seven / "7z.exe"), "x", str(dl / "tesseract-setup.exe"), f"-o{tess}", "-y"],
                       check=True, stdout=subprocess.DEVNULL)
        if VENDOR.exists():
            shutil.rmtree(VENDOR)
        (VENDOR / "licenses").mkdir(parents=True)
        for name in dll_closure(tess):
            shutil.copy2(tess / name, VENDOR / name)
        shutil.copy2(tess / "doc" / "LICENSE", VENDOR / "licenses" / "tesseract-LICENSE.txt")
        shutil.copy2(tess / "doc" / "AUTHORS", VENDOR / "licenses" / "tesseract-AUTHORS.txt")
        for (model, lang), digest in MODELS.items():
            folder = VENDOR / "tessdata" / model
            folder.mkdir(parents=True, exist_ok=True)
            download(MODEL_URL.format(model=model, lang=lang), folder / f"{lang}.traineddata", digest)
            if not (folder / "configs").exists():
                shutil.copytree(tess / "tessdata" / "configs", folder / "configs")
    write_manifest()
    return verify()


if __name__ == "__main__":
    sys.exit(verify() if "--verify" in sys.argv else prepare())
