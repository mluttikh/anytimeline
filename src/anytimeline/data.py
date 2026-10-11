"""Reading columns from tables: Polars, PyArrow, pandas, DuckDB (via narwhals) or a dict of
arrays."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np


class NotFoundError(KeyError):
    """A missing column or layer: a ``KeyError`` whose message reads as written."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


def frame(data: Any) -> Any:
    """``data`` as an eager narwhals DataFrame, or the mapping itself."""
    if isinstance(data, Mapping):
        return data
    import narwhals as nw

    try:
        out = nw.from_native(data)
    except TypeError:
        raise TypeError(
            f"unsupported data of type {type(data).__name__}; pass a Polars, PyArrow, pandas "
            "or DuckDB table, or a dict of arrays"
        ) from None
    if isinstance(out, nw.LazyFrame):
        out = out.collect()
    return out


def column_names(table: Any) -> list[str]:
    """The names of a table's columns (``table`` from ``frame``)."""
    if isinstance(table, Mapping):
        return [str(k) for k in table]
    return list(table.columns)


def column(table: Any, name: str) -> np.ndarray:
    """A column as a 1-D NumPy array; a missing text value as None."""
    check(table, [name])
    if isinstance(table, Mapping):
        values = table[name]
        if isinstance(values, list | tuple) and any(
            isinstance(v, list | tuple | set | np.ndarray) for v in values
        ):
            # cells that are lists (several ids per row): one object per cell
            out = np.empty(len(values), dtype=object)
            for i, v in enumerate(values):
                out[i] = v
            return out
        return np.asarray(values).ravel()
    series = table[name]
    out = series.to_numpy()
    if out.dtype == object:
        missing = np.asarray(series.is_null().to_numpy(), dtype=bool)
        if missing.any():
            out = out.copy()
            out[missing] = None
    return out


def time_zone(table: Any, name: str) -> str | None:
    """The time zone of a datetime column (None: naive, or not a datetime)."""
    if isinstance(table, Mapping):
        values = table[name]
        tz = getattr(getattr(values, "dt", None), "tz", None) or getattr(values, "tz", None)
        return str(tz) if tz is not None else None
    import narwhals as nw

    dtype = table.schema[name]
    if isinstance(dtype, nw.Datetime):
        return dtype.time_zone
    return None


def categories(table: Any, name: str) -> list[Any] | None:
    """The declared order of a column's values: a Polars ``Enum`` or a pandas
    ``Categorical``; None for other columns."""
    if isinstance(table, Mapping):
        values = table[name]
        cat = getattr(values, "cat", None)
        if cat is not None and hasattr(cat, "categories"):
            return list(cat.categories)
        return list(values.categories) if hasattr(values, "categories") else None
    import narwhals as nw

    dtype = table.schema[name]
    if isinstance(dtype, nw.Enum):
        return list(dtype.categories)
    native = nw.to_native(table)
    if dtype == nw.Categorical and hasattr(native, "iloc"):  # pandas: its own categories
        return list(native[name].cat.categories)
    return None


def check(table: Any, names: list[str]) -> None:
    """Raise ``NotFoundError`` naming the columns that ``table`` lacks."""
    available = column_names(table)
    missing = [n for n in names if n not in available]
    if missing:
        raise NotFoundError(f"columns not found: {missing}; available: {available}")


def is_missing(values: np.ndarray) -> np.ndarray:
    """True where a value is missing: None, NaN or NaT."""
    if values.dtype.kind in "fc":
        return np.isnan(values)
    if values.dtype.kind in "mM":
        return np.isnat(values)
    if values.dtype.kind == "O":
        return np.array(
            [v is None or (isinstance(v, float) and v != v) for v in values], dtype=bool
        )
    return np.zeros(values.shape, dtype=bool)
