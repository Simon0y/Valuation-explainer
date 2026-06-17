"""Permanent guard: importing the app must never raise (catches deploy-killing ImportErrors).

Streamlit Cloud runs ``app.py`` at startup. A renamed/removed/misspelled top-level import
crashes the whole app with a red ImportError before a single widget renders, the exact class
of failure that has bitten this deploy repeatedly.

``app.py``'s ``main()`` sits behind ``if __name__ == "__main__"``, so simply importing the
module resolves EVERY top-level import (the full ``data.*`` / ``engine.*`` / ``content.*``
chain) WITHOUT launching Streamlit. This runs that exact check in a clean subprocess, mirroring
``python -c "import app"``, and fails loudly with the real traceback if anything breaks.
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_app_imports_cleanly():
    """`python -c "import app"` must exit 0 — run this BEFORE every commit and push."""
    result = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"`python -c 'import app'` failed (exit {result.returncode}) — do NOT push.\n"
        f"--- stderr ---\n{result.stderr}"
    )
