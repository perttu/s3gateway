#!/usr/bin/env python3
"""
Polling worker that processes pending replication jobs using the proxy metadata DB.
"""
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app import db, replication  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    interval = int(os.getenv("REPLICATION_WORKER_INTERVAL", "2"))
    logging.info("Starting replication worker (interval=%ss)", interval)
    while True:
        conn = db.get_connection()
        try:
            processed = replication.process_pending_jobs(conn)
        finally:
            conn.close()
        if processed == 0:
            time.sleep(interval)


if __name__ == "__main__":
    main()
