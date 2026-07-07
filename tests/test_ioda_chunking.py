import pandas as pd

from src.ioda import client
from src.ioda.client import fetch_signals, query_chunks

DAY = 86400


def test_chunks_cover_range_without_overlap():
    chunks = list(query_chunks(0, 425 * DAY, 90 * DAY))
    assert chunks[0][0] == 0 and chunks[-1][1] == 425 * DAY
    for (_, e1), (s2, _) in zip(chunks, chunks[1:]):
        assert e1 == s2
    assert all(e - s <= 90 * DAY for s, e in chunks)
    assert len(chunks) == 5


def test_short_range_is_single_chunk():
    assert list(query_chunks(100, 200, 90 * DAY)) == [(100, 200)]


def test_fetch_signals_chunks_and_dedupes(monkeypatch):
    calls = []

    def fake_get_json(url, params=None):
        calls.append(params)
        # each chunk returns points at its start and end, so consecutive
        # chunks share one edge point (ts == chunk boundary)
        return {"data": [[{
            "from": params["from"], "step": 100,
            "datasource": params["datasource"], "values": [1, 2],
        }]]}

    monkeypatch.setattr(client, "get_json", fake_get_json)
    monkeypatch.setattr(client.time, "sleep", lambda _s: None)

    df = fetch_signals("http://x", "asn", "1", 0, 200, ["ping-slash24"],
                       request_interval=0, max_query_seconds=100)
    assert [(c["from"], c["until"]) for c in calls] == [(0, 100), (100, 200)]
    # chunk 1 gives ts 0,100; chunk 2 gives ts 100,200 -> shared 100 deduped
    assert df["ts"].tolist() == [0, 100, 200]
