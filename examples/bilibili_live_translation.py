#!/usr/bin/env python3
"""Translate audio from a Bilibili live room without sending chat messages."""

import argparse
import logging
from pathlib import Path
import sys
import time

logging.basicConfig(level=logging.INFO)
sys.path.insert(0, str(Path(__file__).parent.parent))

from streaming_transcribe_translate.desktop_app_example import desktop_app_integration


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("room_id", help="Bilibili live room ID or room URL")
    args = parser.parse_args()

    app = desktop_app_integration()
    app.configure_bilibili_stream(args.room_id)
    logging.info("Starting Bilibili translation session; chat posting is disabled.")

    try:
        app.start_session()
        while app.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Stopping translation session...")
    finally:
        app.stop_session()


if __name__ == "__main__":
    main()
