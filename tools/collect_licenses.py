"""Collect license files of every redistributed component into one folder.

Usage: python tools/collect_licenses.py OUTPUT_DIR
Copies the license files shipped in the installed packages' .dist-info
folders, Python's own license, the static GPL/LGPL texts in
packaging/licenses and the Tesseract licenses.
"""

from __future__ import annotations

import shutil
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ["PySide6_Essentials", "shiboken6", "numpy", "pillow", "pypdfium2", "zxing-cpp", "pyinstaller"]


def main(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    copied = 0
    for name in PACKAGES:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            print(f"warning: {name} not installed", file=sys.stderr)
            continue
        target = out / f"{dist.metadata['Name']}-{dist.version}"
        for f in dist.files or []:
            parts = [p.lower() for p in f.parts]
            if any(p.endswith(".dist-info") for p in parts) and any(k in "/".join(parts) for k in
                                                                     ("licen", "copying", "notice")):
                src = Path(f.locate())
                if src.is_file():
                    rel = Path(*f.parts[1:]) if len(f.parts) > 1 else Path(f.name)
                    dest = target / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    copied += 1
        meta = target / "METADATA-license.txt"
        target.mkdir(parents=True, exist_ok=True)
        meta.write_text(f"{dist.metadata['Name']} {dist.version}\nLicense: "
                        f"{dist.metadata.get('License-Expression') or dist.metadata.get('License') or 'see files'}\n",
                        encoding="utf-8")
    py_license = Path(sysconfig.get_config_var("prefix") or sys.base_prefix) / "LICENSE.txt"
    if not py_license.exists():
        py_license = Path(sys.base_prefix) / "LICENSE.txt"
    if py_license.exists():
        shutil.copy2(py_license, out / "Python-LICENSE.txt")
        copied += 1
    for f in (ROOT / "packaging" / "licenses").glob("*.txt"):
        shutil.copy2(f, out / f.name)
        copied += 1
    tess = ROOT / "vendor" / "tesseract" / "licenses"
    if tess.is_dir():
        shutil.copytree(tess, out / "Tesseract")
        copied += len(list(tess.iterdir()))
    print(f"collected {copied} license files into {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "licenses")
