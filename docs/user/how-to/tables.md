# Plot your own tables

`events()` takes a table with one row per event and the names of its columns:

```python
plot = Timeline()
plot.events(df, time="timestamp", lane="host", color="severity")
```

## Supported tables

Any table [narwhals](https://narwhals-dev.github.io/narwhals/) reads: a Polars DataFrame or
LazyFrame, a pandas DataFrame, a PyArrow Table, a DuckDB relation, an Ibis table, and more;
or a dict of arrays. A lazy table (a Polars LazyFrame, a DuckDB relation, an Ibis table) is
read once, when its layer is added, with only the columns the layer uses.

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

## The selected rows

[`selected`][anytimeline.Timeline.selected] gives the rows selected in the plot as a table of
the type you plotted: a pandas DataFrame keeps its index, a dict gives a dict. A lazy table
gives the rows of the read the plot drew (a Polars DataFrame for a LazyFrame, a PyArrow table
for DuckDB and Ibis), so they are the rows you selected even when the database returns its rows in
another order next time.

```python
plot = Timeline().events(df, time="time", lane="host")
plot  # select with the Select tool, then:
plot.selected()  # the plot's one layer; else plot.selected("events")
```

## Rows that are left out

Rows without a time (null, NaN, NaT) are left out. A row without a lane value goes into a lane named `(missing)`, and a row without
a color value is drawn gray.

## Times that look wrong

The plot is drawn, with a warning, when its times look like a mistake:

- **All in January 1970**: numbers since the epoch read in a too fine unit (seconds read as
  nanoseconds). Convert them with their unit: `pd.to_datetime(x, unit="s")` or
  `pl.from_epoch(x, time_unit="s")`.
- **Numbers that look like seconds (or ms, µs, ns) since the epoch**: drawn as plain numbers.
  The warning names the unit they look like and the first as a date.

An `end` column of durations is an error that says to pass it as `duration="end"`.

## A column that does not exist

An error names the missing column and lists the table's columns:

```text
NotFoundError: columns not found: ['hosts']; available: ['time', 'host', 'severity']
```
