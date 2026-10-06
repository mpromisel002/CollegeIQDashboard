"""PyInstaller entry point (kept outside the package so multiprocessing's freeze_support runs first)."""

import sys

from cfa.app import main

if __name__ == "__main__":
    sys.exit(main())
