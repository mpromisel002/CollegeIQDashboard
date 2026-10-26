"""Entry point. `python -m cfa` opens the window; `--self-test` checks sources and exits 0/1."""

from __future__ import annotations

import argparse
import asyncio
import logging
import multiprocessing
import sys

from cfa import __version__, config
from cfa.cache import CACHE

log = logging.getLogger("cfa")


def self_test() -> int:
    """Load the registry and ping each source. Used by the release workflow on the built exe."""
    from cfa.models.field_value import Status
    from cfa.pipeline import health_checks
    from cfa.sources.http import HttpClient
    from cfa.sources.registry import load_bundled, load_registry

    try:
        bundled = load_bundled()
    except Exception as exc:
        log.error("self-test: bundled registry unusable: %s", exc)
        return 1
    try:  # the document readers must be present in the frozen build
        import openpyxl  # noqa: F401
        import pdfplumber  # noqa: F401
        import pypdfium2

        pypdfium2.PdfDocument.new().close()  # loads the native pdfium library
    except Exception as exc:
        log.error("self-test: document readers unavailable: %s", exc)
        print(f"document readers: FAILED {type(exc).__name__}: {exc}")
        return 1
    print("document readers: OK")

    async def go() -> int:
        async with HttpClient(max_retries=1) as http:
            loaded = await load_registry(http)
        health = await health_checks(loaded.registry, config.scorecard_api_key())
        ok = True
        for src, res in health.items():
            log.info("self-test: %s -> %s (%s)", src, res.status.value, res.note)
            print(f"{src}: {res.status.value} {res.note}")
            if res.status not in (Status.OK, Status.AUTH_MISSING):
                ok = False
        print(f"registry: bundled {len(bundled.schools)} schools; loaded {loaded.origin}")
        return 0 if ok else 1

    try:
        return asyncio.run(go())
    except Exception as exc:
        log.error("self-test failed: %s", exc)
        return 1


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()  # CDS parsing uses a process pool in the frozen exe
    parser = argparse.ArgumentParser(prog="CollegeFitAdvisor")
    parser.add_argument("--self-test", action="store_true", help="check sources and exit 0/1")
    parser.add_argument("--version", action="version", version=__version__)
    args, qt_args = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    config.setup_logging()
    if args.self_test:
        return self_test()

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from cfa.pipeline import shutdown_pool
    from cfa.ui.main_window import MainWindow
    from cfa.ui.theme import apply_theme

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("College Fit Advisor")
    apply_theme(app)
    icon = config.bundled_path("cfa/ui/icon.png")
    if not icon.exists():
        icon = config.bundled_path("src/cfa/ui/icon.png")
    app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.show()
    try:
        return app.exec()
    finally:
        CACHE.clear()  # college data lives only in memory for the session
        shutdown_pool()


if __name__ == "__main__":
    sys.exit(main())
