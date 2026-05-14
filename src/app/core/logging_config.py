"""Logging configuration."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path


def setup_logging(log_dir: str | Path | None = None, level: int = logging.INFO) -> Path:
    """Configure logging. Returns path to current log file."""
    if log_dir is None:
        log_dir = Path(__file__).resolve().parents[3] / "data" / "logs"
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"

    root = logging.getLogger()
    root.setLevel(level)

    # Clear existing handlers
    for h in root.handlers[:]:
        root.removeHandler(h)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    return log_file


def get_log_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "logs"
