
"""
Store SQL query results in server-side memory.

The LLM receives a small preview.
Other tools can retrieve the full DataFrame using its reference.
"""

import threading
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class StoredResult:
    """Information about one stored SQL query result."""

    ref: str
    sql: str
    df: pd.DataFrame
    columns: list[str]
    total_rows: int


class ResultStore:
    """Thread-safe in-memory storage for query results."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: dict[str, StoredResult] = {}

    def put(self, ref: str, sql: str, df: pd.DataFrame) -> StoredResult:
        """Save a DataFrame and return its metadata."""

        stored = StoredResult(
            ref=ref,
            sql=sql,
            df=df,
            columns=list(df.columns),
            total_rows=len(df),
        )

        with self._lock:
            self._slots[ref] = stored

        return stored

    def get(self, ref: str) -> Optional[StoredResult]:
        """Retrieve a stored result by reference."""

        with self._lock:
            return self._slots.get(ref)

    def clear(self) -> None:
        """Remove all stored results."""

        with self._lock:
            self._slots.clear()


# Shared store used by the agent tools.
STORE = ResultStore()