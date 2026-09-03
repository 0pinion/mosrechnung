from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "mosrechnung"


def data_dir() -> Path:
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return data_dir() / "mosrechnung.sqlite3"


def default_invoice_dir() -> Path:
    return Path.home() / "Dokumente" / "Rechnungen"

