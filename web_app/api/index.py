"""Vercel Python entrypoint for the CapCut-only API routes."""
from pathlib import Path
import sys

WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from server import app  # noqa: E402,F401
