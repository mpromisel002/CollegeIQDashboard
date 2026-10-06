"""Settings and tunable constants.

Nothing in here is college data: only URLs, timeouts, and scoring thresholds.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date
from pathlib import Path

from cfa import __version__

APP_NAME = "CollegeFitAdvisor"
REPO_URL = "https://github.com/mpromisel002/CollegeIQDashboard"
USER_AGENT = f"{APP_NAME}/{__version__} (+{REPO_URL})"

# --- Registry -----------------------------------------------------------------
REGISTRY_REMOTE_URL = (
    "https://raw.githubusercontent.com/mpromisel002/CollegeIQDashboard/main/registry/schools.yaml"
)

# --- HTTP (PLAN §5.1 rule 2) --------------------------------------------------
CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 30.0
MAX_RETRIES = 3
BACKOFF_BASE_S = 1.0
BACKOFF_MAX_S = 20.0
MAX_CONCURRENCY_PER_HOST = 4

# --- CDS downloads (PLAN §5.1 rule 7) ------------------------------------------
CDS_MAX_BYTES = 25 * 1024 * 1024

# --- Session cache --------------------------------------------------------------
CACHE_TTL_S = 60 * 60
CACHE_MAX_ITEMS = 2048

# --- Data sources -----------------------------------------------------------------
URBAN_BASE_URL = "https://educationdata.urban.org/api/v1/college-university/ipeds"
SCORECARD_BASE_URL = "https://api.data.gov/ed/collegescorecard/v1/schools"
# Latest-year discovery: start at (current year - 1) and walk back this many more years.
URBAN_YEAR_WALKBACK = 4

KEYRING_SERVICE = APP_NAME
KEYRING_SCORECARD_USER = "scorecard_api_key"
SCORECARD_KEY_ENV = "CFA_SCORECARD_API_KEY"

# --- Academic fit thresholds (PLAN §6.2) -------------------------------------------
REACH_ADMIT_RATE_PCT = 15.0  # admit rate below this => always Reach
SAFETY_ADMIT_RATE_PCT = 50.0  # admit rate at/above this is required for Safety
GPA_BOTTOM_QUARTILE = 25.0  # student's GPA percentile below this => Reach
GPA_TOP_QUARTILE = 75.0  # student's GPA percentile at/above this needed for Safety
GPA_MEDIAN = 50.0

# --- Culture fit (PLAN §6.3) --------------------------------------------------------
GREEK_FULL_SCORE_PCT = 30.0  # >= this % Greek participation scores 100 for "wants Greek"
SIZE_BANDS = (5_000, 15_000, 30_000)  # <5k, 5-15k, 15-30k, >30k


def current_year() -> int:
    return date.today().year


def scorecard_api_key() -> str | None:
    """Return the Scorecard key from the environment or Windows Credential Manager."""
    env = os.environ.get(SCORECARD_KEY_ENV)
    if env:
        return env.strip()
    try:
        import keyring

        value = keyring.get_password(KEYRING_SERVICE, KEYRING_SCORECARD_USER)
    except Exception:  # no keyring backend available
        return None
    return value.strip() if value else None


def set_scorecard_api_key(key: str | None) -> bool:
    try:
        import keyring

        if key:
            keyring.set_password(KEYRING_SERVICE, KEYRING_SCORECARD_USER, key.strip())
        else:
            try:
                keyring.delete_password(KEYRING_SERVICE, KEYRING_SCORECARD_USER)
            except Exception:
                pass
    except Exception:
        return False
    return True


def bundled_path(relative: str) -> Path:
    """Locate a file shipped with the app (PyInstaller bundle or source checkout)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / relative
    return Path(__file__).resolve().parents[2] / relative


def log_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    base = Path(root) if root else Path.home() / ".local" / "share"
    return base / APP_NAME / "logs"


def setup_logging(level: int = logging.INFO) -> None:
    """Rotating log file. Only source/status/timing is logged; no student or college data."""
    from logging.handlers import RotatingFileHandler

    handlers: list[logging.Handler] = []
    if sys.stderr is not None:  # None in the windowed (no console) build
        handlers.append(logging.StreamHandler())
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(d / "cfa.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        )
    except OSError:
        pass
    logging.basicConfig(
        level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers, force=True
    )
