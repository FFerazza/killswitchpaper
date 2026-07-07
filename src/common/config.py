"""Load and expose the two YAML config files (config/phases.yaml, config/sources.yaml)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.common.timeutil import to_unix

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data"
OUTPUTS_DIR = REPO_ROOT / "outputs"


@dataclass(frozen=True)
class Window:
    """A named half-open time window [start, end) in unix seconds."""

    name: str
    start: int
    end: int


class Config:
    """Typed access to phases.yaml + sources.yaml."""

    def __init__(self, phases: dict[str, Any], sources: dict[str, Any]):
        self._phases = phases
        self._sources = sources

    @classmethod
    def load(cls, config_dir: Path = CONFIG_DIR) -> "Config":
        with open(config_dir / "phases.yaml") as f:
            phases = yaml.safe_load(f)
        with open(config_dir / "sources.yaml") as f:
            sources = yaml.safe_load(f)
        return cls(phases, sources)

    # --- time windows ---

    def _window(self, name: str, block: dict[str, str]) -> Window:
        return Window(name=name, start=to_unix(block["start"]), end=to_unix(block["end"]))

    @property
    def study_period(self) -> Window:
        return self._window("study_period", self._phases["study_period"])

    @property
    def test_week(self) -> Window:
        return self._window("test_week", self._phases["test_week"])

    @property
    def event_windows(self) -> list[Window]:
        return [self._window(name, block) for name, block in self._phases["event_windows"].items()]

    def phase_window(self, name: str) -> Window:
        """Return a phase (P0..P4) as a Window."""
        return self._window(name, self._phases["phases"][name])

    def window_by_name(self, name: str) -> Window:
        """Resolve a named window: an event window, 'test_week', or 'study_period'."""
        if name == "test_week":
            return self.test_week
        if name == "study_period":
            return self.study_period
        for w in self.event_windows:
            if w.name == name:
                return w
        raise KeyError(f"Unknown window {name!r}; known: "
                       f"{[w.name for w in self.event_windows] + ['test_week', 'study_period']}")

    # --- stage settings ---

    @property
    def collectors(self) -> list[str]:
        """Collector list for update-stream (event) pulls."""
        return list(self._phases["bgp"]["collectors"])

    @property
    def rib_collectors(self) -> list[str]:
        """Collector list for RIB/visibility runs (D-002: broker RIB coverage constraint)."""
        return list(self._phases["bgp"]["rib_collectors"])

    @property
    def ris_backfill_collectors(self) -> list[str]:
        """RIS collectors fetched directly from data.ris.ripe.net (D-012)."""
        return list(self._phases["bgp"]["ris_backfill"]["collectors"])

    @property
    def ris_backfill_ranges(self) -> list[Window]:
        """Snapshot ranges covered by the RIS-inclusive secondary series (D-012)."""
        blocks = self._phases["bgp"]["ris_backfill"]["ranges"]
        return [self._window(name, block) for name, block in blocks.items()]

    @property
    def rib_interval_hours(self) -> int:
        return int(self._phases["bgp"]["rib_interval_hours"])

    @property
    def full_feed_min_prefixes(self) -> dict[str, int]:
        return dict(self._phases["bgp"]["full_feed_min_prefixes"])

    @property
    def ioda_signals(self) -> list[str]:
        return list(self._phases["ioda"]["signals"])

    @property
    def ioda_request_interval(self) -> float:
        return float(self._phases["ioda"]["request_interval_seconds"])

    @property
    def ioda_max_query_seconds(self) -> int:
        return int(self._phases["ioda"]["max_query_days"]) * 86400

    @property
    def ripestat_sample_asns(self) -> list[int]:
        return [int(a) for a in self._phases["ripestat_sample_asns"]]

    @property
    def analysis(self) -> dict:
        return dict(self._phases["analysis"])

    @property
    def probing_baseline_window(self) -> Window:
        """Fixed P0 reference window for probing baselines (D-013)."""
        return self._window("probing_baseline", self._phases["analysis"]["probing_baseline_window"])

    # --- sources ---

    def source(self, key: str) -> str:
        return str(self._sources[key])
