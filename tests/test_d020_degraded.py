import pandas as pd

from src.analysis.joins import drop_degraded
from src.bgp.ribs import _stamp_fullfeed, consolidate


def _snapshot(ts, ff_v4, ff_v6):
    """One snapshot frame: a v4 and a v6 row with own-family peers_total."""
    return pd.DataFrame({
        "ts": [ts, ts],
        "prefix": ["5.22.200.0/24", "2c0f:1::/32"],
        "family": [4, 6],
        "peers_total": [ff_v4, ff_v6],
        "visibility": [1.0, 1.0],
        "cc": ["IR", "IR"],
    })


def test_stamp_fullfeed_sets_both_family_counts():
    df = _stamp_fullfeed(_snapshot(100, 51, 29))
    assert df["ff_v4"].tolist() == [51, 51]
    assert df["ff_v6"].tolist() == [29, 29]


def test_stamp_fullfeed_missing_family_is_zero():
    df = _stamp_fullfeed(_snapshot(100, 51, 29)[lambda d: d["family"] == 4])
    assert df["ff_v6"].tolist() == [0]


def test_consolidate_carries_fullfeed_columns(tmp_path):
    _snapshot(100, 51, 29).to_parquet(tmp_path / "rib_100.parquet", index=False)
    _snapshot(200, 26, 3).to_parquet(tmp_path / "rib_200.parquet", index=False)
    out = tmp_path / "series.parquet"
    consolidate(tmp_path, out)
    df = pd.read_parquet(out)
    by_ts = df.drop_duplicates("ts").set_index("ts")
    assert by_ts.loc[100, ["ff_v4", "ff_v6"]].tolist() == [51, 29]
    assert by_ts.loc[200, ["ff_v4", "ff_v6"]].tolist() == [26, 3]


def test_drop_degraded_excludes_only_the_thin_family():
    df = pd.concat([_snapshot(100, 51, 29), _snapshot(200, 26, 3)],
                   ignore_index=True)
    kept = drop_degraded(df, min_fullfeed_peers=15)
    # ts=200 IPv6 (3 peers) is the only degraded cell; its IPv4 row stays
    assert [(int(r.ts), int(r.family)) for r in kept.itertuples()] == [
        (100, 4), (100, 6), (200, 4),
    ]


def test_drop_degraded_noop_when_all_healthy():
    df = _snapshot(100, 51, 29)
    assert drop_degraded(df, 15).equals(df)
