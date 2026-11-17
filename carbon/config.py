from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent   # raíz del repositorio
CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
DATA_DIR = ROOT / "data" / "carbon"
HIST_PATH = DATA_DIR / "historico" / "series.csv"
MANUAL_DIR = DATA_DIR / "manual"
REPORTS_DIR = ROOT / "reportes" / "carbon"


def load_config(path: Path | str = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
