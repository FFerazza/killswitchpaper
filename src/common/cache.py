"""Download caching and atomic writes.

Every stage must be idempotent and resumable: raw pulls are cached on disk
and skipped when present; outputs are written atomically (temp file + rename)
so a crash never leaves a truncated file that would be mistaken for done.
"""

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

import requests

from src.common.log import get_logger

log = get_logger("common.cache")

_TIMEOUT = 120
_RETRIES = 3


def atomic_write(dest: Path, write_fn: Callable[[Path], None]) -> None:
    """Call `write_fn(tmp_path)` then atomically rename tmp_path to `dest`."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.")
    tmp = Path(tmp_name)
    try:
        os.close(fd)
        write_fn(tmp)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def download(url: str, dest: Path, force: bool = False) -> Path:
    """Download `url` to `dest`, skipping if the file is already cached."""
    if dest.exists() and not force:
        log.info("cached: %s", dest)
        return dest
    log.info("downloading %s -> %s", url, dest)
    last_err: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            with requests.get(url, stream=True, timeout=_TIMEOUT) as resp:
                resp.raise_for_status()

                def _write(tmp: Path) -> None:
                    with open(tmp, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=1 << 20):
                            f.write(chunk)

                atomic_write(dest, _write)
            return dest
        except requests.RequestException as e:
            last_err = e
            log.warning("attempt %d/%d failed for %s: %s", attempt, _RETRIES, url, e)
    raise RuntimeError(f"Failed to download {url} after {_RETRIES} attempts") from last_err


def get_json(url: str, params: dict | None = None) -> dict:
    """GET a JSON document with retries."""
    last_err: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_err = e
            log.warning("attempt %d/%d failed for %s: %s", attempt, _RETRIES, url, e)
    raise RuntimeError(f"Failed to fetch {url} after {_RETRIES} attempts") from last_err
