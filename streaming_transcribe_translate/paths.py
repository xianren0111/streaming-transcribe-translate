"""Stable project paths, independent of the process working directory."""

from pathlib import Path
import sys


ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", ROOT))
LOGS_ROOT = ROOT / "logs"
LOG_FILE = LOGS_ROOT / "streaming_live_translation.log"
