"""TextSnap entry point (python main.py, or the packaged TextSnap.exe)."""

import sys

from textsnap.app.main import main

if __name__ == "__main__":
    sys.exit(main())
