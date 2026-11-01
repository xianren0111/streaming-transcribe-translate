"""Stable project paths, independent of the process working directory."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LOGS_ROOT = ROOT / "logs"
LOG_FILE = LOGS_ROOT / "streaming_live_translation.log"
