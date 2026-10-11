# Plot your own tables

`events()` takes a table with one row per event and the names of its columns:

```python
plot = Timeline()
plot.events(df, time="timestamp", lane="host", color="severity")
```

## Supported tables

Any table [narwhals](https://narwhals-dev.github.io/narwhals/) reads: a Polars DataFrame or
LazyFrame, a pandas DataFrame, a PyArrow Table, a DuckDB relation, and more; or a dict of
arrays. A lazy table is read once, with all its columns.

```python exec="on" source="above" html="true"
import numpy as np
from anytimeline import Timeline

events = {
    "time": np.array(
        [
            "2026-10-12T09:00",
            "2026-10-12T09:05",
            "2026-10-12T09:07",
            "2026-10-12T09:30",
            "2026-10-12T10:10",
        ],
        dtype="datetime64[s]",
    ),
    "host": ["web-1", "web-2", "web-1", "db-1", "web-2"],
    "severity": ["info", "warning", "info", "error", "info"],
}
plot = Timeline(height=200)
plot.events(events, time="time", lane="host", color="severity", symbol="severity", size=10)
print(plot._embed_html())
```

## Rows that are left out

Rows without a time (null, NaN, NaT) are left out. A row without a lane value goes into a lane named `(missing)`, and a row without
a color value is drawn gray.

## A column that does not exist

An error names the missing column and lists the table's columns:

```text
NotFoundError: columns not found: ['hosts']; available: ['time', 'host', 'severity']
```
