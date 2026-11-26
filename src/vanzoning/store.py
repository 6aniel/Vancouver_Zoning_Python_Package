"""Save / load parsed schedules. JSON is the source of truth (diffable in git);
Parquet/CSV are derived flat tables for analysis."""
from __future__ import annotations

from importlib import resources
from pathlib import Path

from .models import DistrictSchedule

DATA_PKG = "vanzoning.data.districts"


def save(sched: DistrictSchedule, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sched.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_file(path: str | Path) -> DistrictSchedule:
    return DistrictSchedule.model_validate_json(Path(path).read_text(encoding="utf-8"))


def available() -> list[str]:
    return sorted(p.name.removesuffix(".json") for p in resources.files(DATA_PKG).iterdir() if p.name.endswith(".json"))


def load(district: str) -> DistrictSchedule:
    """Load a bundled, reviewed district, e.g. load('R1-1')."""
    return DistrictSchedule.model_validate_json(resources.files(DATA_PKG).joinpath(f"{district}.json").read_text("utf-8"))


def load_all() -> list[DistrictSchedule]:
    """Every bundled district."""
    return [load(d) for d in available()]


def regulations_table(schedules: list[DistrictSchedule] | None = None):
    """One long DataFrame of rules for several districts (default: all bundled)."""
    import pandas as pd

    schedules = load_all() if schedules is None else schedules
    return pd.concat([s.regulations_df() for s in schedules], ignore_index=True)
