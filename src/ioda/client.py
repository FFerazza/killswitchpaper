"""IODA raw-signals client.

Endpoint: {base}/signals/raw/{entityType}/{entityCode}?from=..&until=..&datasource=..
No API key. The host has moved between institutions before — it lives in
config/sources.yaml (ioda_api_base); verify against current IODA docs before
a full run.

Responses are normalized to long-format rows:
    ts, entity_type, entity_code, datasource, value
"""

import time
from pathlib import Path

import pandas as pd

from src.common.cache import get_json
from src.common.log import get_logger

log = get_logger("ioda.client")


def fetch_signals(
    base_url: str,
    entity_type: str,
    entity_code: str,
    start: int,
    end: int,
    signals: list[str],
    request_interval: float,
) -> pd.DataFrame:
    """Fetch all requested signals for one entity and return normalized rows."""
    rows: list[dict] = []
    for signal in signals:
        url = f"{base_url}/signals/raw/{entity_type}/{entity_code}"
        doc = get_json(url, params={"from": start, "until": end, "datasource": signal})
        rows.extend(_normalize(doc, entity_type, entity_code))
        time.sleep(request_interval)  # polite rate limiting
    return pd.DataFrame(rows, columns=["ts", "entity_type", "entity_code", "datasource", "value"])


def _normalize(doc: dict, entity_type: str, entity_code: str) -> list[dict]:
    """Flatten IODA's nested response (data -> [[series...]]) into rows.

    Each series has from/step/values; values may contain nulls where the
    signal has gaps — kept as None so gaps stay distinguishable from zero.
    """
    rows = []
    data = doc.get("data") or []
    for group in data:
        series_list = group if isinstance(group, list) else [group]
        for series in series_list:
            if not isinstance(series, dict):
                continue
            start = series.get("from")
            step = series.get("step")
            values = series.get("values") or []
            datasource = series.get("datasource", "")
            if start is None or step is None:
                continue
            for i, value in enumerate(values):
                rows.append({
                    "ts": int(start + i * step),
                    "entity_type": entity_type,
                    "entity_code": entity_code,
                    "datasource": datasource,
                    "value": value,
                })
    return rows


def fetch_to_parquet(
    out_path: Path,
    base_url: str,
    entity_type: str,
    entity_code: str,
    start: int,
    end: int,
    signals: list[str],
    request_interval: float,
) -> bool:
    """Fetch one entity to parquet; returns False if cached (skipped)."""
    if out_path.exists():
        log.info("skip existing %s", out_path)
        return False
    df = fetch_signals(
        base_url, entity_type, entity_code, start, end, signals, request_interval
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(out_path)
    log.info("%s/%s: %d rows -> %s", entity_type, entity_code, len(df), out_path)
    return True
