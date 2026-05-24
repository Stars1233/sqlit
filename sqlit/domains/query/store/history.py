"""File-backed query history store.

Each query is a `.sql` file under `CONFIG_DIR/queries/<connection_dir>/`
with a small comment header carrying connection name, database, and
timestamp. Files are sortable lexicographically by their timestamp prefix.

Re-running the same query (exact text after `strip()`) updates the
existing entry by deleting the old file and writing a new one with the
current timestamp, so most-recent always sorts last (and reverse-sorts
first for the UI).
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlit.shared.core.store import CONFIG_DIR

_HEADER_MARKER = "-- sqlit:history"
_HEADER_LINE = re.compile(r"^--\s*([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


@dataclass
class QueryHistoryEntry:
    """A query history entry."""

    query: str
    timestamp: str  # ISO format
    connection_name: str
    database: str = ""
    is_starred: bool = False  # Computed at load time, not persisted
    is_starred_only: bool = False  # True if only in starred store, not in history

    def to_dict(self) -> dict:
        d: dict = {
            "query": self.query,
            "timestamp": self.timestamp,
            "connection_name": self.connection_name,
        }
        if self.database:
            d["database"] = self.database
        return d

    @classmethod
    def from_dict(cls, data: dict) -> QueryHistoryEntry:
        return cls(
            query=data["query"],
            timestamp=data["timestamp"],
            connection_name=data["connection_name"],
            database=data.get("database", ""),
        )


def _query_hash(query: str) -> str:
    return hashlib.sha256(query.strip().encode("utf-8")).hexdigest()[:8]


def _connection_dir_name(connection_name: str) -> str:
    """Sanitize connection name + append short hash for collision-free uniqueness."""
    safe = _SAFE_NAME.sub("_", connection_name)[:40] or "_"
    short = hashlib.sha256(connection_name.encode("utf-8")).hexdigest()[:8]
    return f"{safe}_{short}"


def _timestamp_to_filename(iso_ts: str) -> str:
    """Turn an ISO timestamp into a filesystem-safe sortable prefix."""
    return iso_ts.replace(":", "-")


def _filename_to_timestamp(stem_prefix: str) -> str:
    """Inverse of _timestamp_to_filename. Used only as a fallback when a
    stored file is missing a header."""
    if "T" not in stem_prefix:
        return stem_prefix
    date_part, _, time_part = stem_prefix.partition("T")
    return f"{date_part}T{time_part.replace('-', ':', 2)}"


def _format_entry(entry: QueryHistoryEntry) -> str:
    lines = [
        _HEADER_MARKER,
        f"-- connection: {entry.connection_name}",
    ]
    if entry.database:
        lines.append(f"-- database: {entry.database}")
    lines.append(f"-- ran: {entry.timestamp}")
    lines.append("")
    lines.append(entry.query)
    if not entry.query.endswith("\n"):
        lines.append("")
    return "\n".join(lines)


def _parse_entry(
    text: str, *, fallback_connection: str, fallback_timestamp: str
) -> QueryHistoryEntry | None:
    """Parse a stored .sql file. Header is the leading run of comment
    lines, terminated by the first blank line. Anything below is the
    query body."""
    lines = text.splitlines()
    metadata: dict[str, str] = {}
    body_start = 0
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if stripped == _HEADER_MARKER:
            body_start = i + 1
            continue
        if stripped == "":
            body_start = i + 1
            break
        m = _HEADER_LINE.match(stripped)
        if m:
            key, value = m.group(1).lower(), m.group(2)
            metadata[key] = value
            body_start = i + 1
            continue
        body_start = i
        break

    query = "\n".join(lines[body_start:]).strip("\n")
    if not query:
        return None

    return QueryHistoryEntry(
        query=query,
        timestamp=metadata.get("ran") or fallback_timestamp,
        connection_name=metadata.get("connection") or fallback_connection,
        database=metadata.get("database", ""),
    )


class HistoryStore:
    """File-backed query history.

    Layout::

        CONFIG_DIR/queries/<connection_dir>/<timestamp>_<queryhash>.sql

    Each file holds the query prefixed by an SQL-comment header
    (``-- sqlit:history``, ``-- connection:``, ``-- database:``,
    ``-- ran:``) terminated by a blank line.
    """

    MAX_ENTRIES_PER_CONNECTION = 100

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir if base_dir is not None else CONFIG_DIR / "queries"
        self._migrated = False

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def _ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass

    def _connection_dir(self, connection_name: str) -> Path:
        return self._base_dir / _connection_dir_name(connection_name)

    def _maybe_migrate(self) -> None:
        if self._migrated:
            return
        self._migrated = True
        legacy = self._base_dir.parent / "query_history.json"
        if not legacy.exists():
            return
        try:
            import json
            with legacy.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, list):
            return
        for raw in data:
            if not isinstance(raw, dict):
                continue
            try:
                entry = QueryHistoryEntry.from_dict(raw)
            except (KeyError, TypeError):
                continue
            self._write_entry(entry)
        try:
            legacy.replace(legacy.with_suffix(".json.migrated"))
        except OSError:
            pass

    def _write_entry(self, entry: QueryHistoryEntry) -> Path:
        """Write one entry to disk, replacing any prior file with the
        same query hash for the same connection. Atomic per-file."""
        conn_dir = self._connection_dir(entry.connection_name)
        self._ensure_dir(conn_dir)

        qhash = _query_hash(entry.query)
        for existing in conn_dir.glob(f"*_{qhash}.sql"):
            try:
                existing.unlink()
            except OSError:
                pass

        filename = f"{_timestamp_to_filename(entry.timestamp)}_{qhash}.sql"
        dest = conn_dir / filename
        body = _format_entry(entry)

        fd, tmp_path = tempfile.mkstemp(dir=conn_dir, prefix=".tmp_", suffix=".sql")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(body)
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            os.replace(tmp_path, dest)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return dest

    def _evict(self, connection_name: str) -> None:
        conn_dir = self._connection_dir(connection_name)
        if not conn_dir.is_dir():
            return
        files = sorted(p for p in conn_dir.glob("*.sql") if p.is_file())
        excess = len(files) - self.MAX_ENTRIES_PER_CONNECTION
        if excess <= 0:
            return
        for path in files[:excess]:
            try:
                path.unlink()
            except OSError:
                pass

    def _load_dir(self, conn_dir: Path) -> list[QueryHistoryEntry]:
        if not conn_dir.is_dir():
            return []
        dir_name = conn_dir.name
        # Dir names end with `_<8-hex-chars>`. Strip that for fallback.
        fallback_connection = (
            dir_name[:-9]
            if len(dir_name) > 9 and dir_name[-9] == "_"
            else dir_name
        )
        entries: list[QueryHistoryEntry] = []
        for path in conn_dir.glob("*.sql"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            stem = path.stem
            fallback_ts_raw = stem.rsplit("_", 1)[0] if "_" in stem else stem
            fallback_ts = _filename_to_timestamp(fallback_ts_raw)
            entry = _parse_entry(
                text,
                fallback_connection=fallback_connection,
                fallback_timestamp=fallback_ts,
            )
            if entry is not None:
                entries.append(entry)
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries

    # ----- public API (matches HistoryStoreProtocol) -----

    def load_for_connection(self, connection_name: str) -> list[QueryHistoryEntry]:
        self._maybe_migrate()
        return self._load_dir(self._connection_dir(connection_name))

    def load_all(self) -> list[QueryHistoryEntry]:
        self._maybe_migrate()
        if not self._base_dir.is_dir():
            return []
        entries: list[QueryHistoryEntry] = []
        for child in self._base_dir.iterdir():
            if child.is_dir():
                entries.extend(self._load_dir(child))
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries

    def save_query(self, connection_name: str, query: str, database: str = "") -> None:
        self._maybe_migrate()
        query_stripped = query.strip()
        if not query_stripped:
            return
        entry = QueryHistoryEntry(
            query=query_stripped,
            timestamp=datetime.now().isoformat(),
            connection_name=connection_name,
            database=database,
        )
        self._write_entry(entry)
        self._evict(connection_name)

    def delete_entry(self, connection_name: str, timestamp: str) -> bool:
        self._maybe_migrate()
        conn_dir = self._connection_dir(connection_name)
        if not conn_dir.is_dir():
            return False
        filename_prefix = _timestamp_to_filename(timestamp)
        for path in conn_dir.glob("*.sql"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            entry = _parse_entry(
                text,
                fallback_connection=connection_name,
                fallback_timestamp=_filename_to_timestamp(path.stem.rsplit("_", 1)[0]),
            )
            if entry is None:
                continue
            if entry.timestamp == timestamp or path.name.startswith(filename_prefix):
                try:
                    path.unlink()
                    return True
                except OSError:
                    return False
        return False

    def clear_for_connection(self, connection_name: str) -> int:
        self._maybe_migrate()
        conn_dir = self._connection_dir(connection_name)
        if not conn_dir.is_dir():
            return 0
        count = 0
        for path in conn_dir.glob("*.sql"):
            try:
                path.unlink()
                count += 1
            except OSError:
                pass
        try:
            conn_dir.rmdir()
        except OSError:
            pass
        return count
