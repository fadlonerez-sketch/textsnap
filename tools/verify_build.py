"""Run a built distribution's self-test and print a summary.

    python tools/verify_build.py                 # dist/TextSnap/TextSnap.exe (PyInstaller)
    python tools/verify_build.py --portable      # dist/TextSnap-Portable (signed Python runtime)
    add --clipboard to include the clipboard round trip (restores your clipboard text)
    add --dir DIR to verify a build in another folder

The build runs with an isolated temporary data folder and synthetic images.
Exit codes: 0 passed, 1 failed, 3 blocked by Windows application control
(Smart App Control / WDAC refuse unsigned executables such as a fresh
PyInstaller bootloader; use the portable build on such machines).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKED = 3


def folder_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main() -> int:
    portable = "--portable" in sys.argv
    custom = Path(sys.argv[sys.argv.index("--dir") + 1]).resolve() if "--dir" in sys.argv else None
    if portable:
        dist = custom or ROOT / "dist" / "TextSnap-Portable"
        cmd = [str(dist / "runtime" / "python.exe"), str(dist / "app" / "main.py")]
    else:
        dist = custom or ROOT / "dist" / "TextSnap"
        cmd = [str(dist / "TextSnap.exe")]
    if not Path(cmd[0]).exists():
        print(f"missing: {cmd[0]}")
        return 1
    report = ROOT / "build" / ("selftest-portable.json" if portable else "selftest-report.json")
    report.unlink(missing_ok=True)
    data = Path(tempfile.mkdtemp(prefix="textsnap-verify-"))
    cmd += ["--data-dir", str(data), "--self-test", str(report)]
    if "--clipboard" in sys.argv:
        cmd.append("--self-test-clipboard")
    try:
        code = subprocess.run(cmd, timeout=300).returncode
    except OSError as exc:
        if getattr(exc, "winerror", None) == 4551:
            print(f"BLOCKED: Windows application control refused to run {cmd[0]}")
            print("  (Smart App Control blocks unsigned executables without reputation.)")
            print("  Use dist\\TextSnap-Portable on this machine; it runs on the signed Python runtime.")
            return BLOCKED
        raise
    if not report.exists():
        print(f"self-test produced no report (exit code {code})")
        return 1
    result = json.loads(report.read_text(encoding="utf-8"))
    for c in result["checks"]:
        mark = "PASS" if c["ok"] else "FAIL"
        print(f"  [{mark}] {c['name']} ({c['ms']} ms)" + ("" if c["ok"] else f" -> {c['error']}"))
        if c["ok"] and isinstance(c.get("detail"), list):
            for r in c["detail"]:
                print(f"         {r['name']:<18} {r['accuracy']:.1%} accuracy, {r['ms']:.0f} ms")
    print(f"frozen={result['frozen']}  exit code={code}")
    print(f"package: {dist}  size: {folder_size(dist) / 1e6:.0f} MB in "
          f"{sum(1 for p in dist.rglob('*') if p.is_file())} files")
    ok = code == 0 and result["passed"]
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
