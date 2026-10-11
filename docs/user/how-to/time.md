# Use your time column

`time=` names the column with the moment of each event. It can hold datetimes, durations or
plain numbers. The plot picks the unit itself: the coarsest of seconds, milliseconds,
microseconds and nanoseconds that keeps every value exact.

## Datetimes and time zones

A datetime column with a time zone (Polars `Datetime(time_zone=...)`, pandas
`datetime64[ns, Europe/Amsterdam]`) is shown in that zone: the axis follows its calendar,
so a day with a daylight-saving change has 23 or 25 hours. To show another zone:

```python
plot = Timeline(timezone="America/New_York")
```

Datetimes without a time zone are shown as they are (as wall-clock time, labelled UTC).

Text is not a time: parse it first, for example `pl.col("t").str.to_datetime()` or
`pd.to_datetime(df["t"])`.

## Durations

Durations (timedelta) are shown as time since zero: `250 µs`, `1.5 s`, `3 min`.

```python exec="on" source="above" session="time" html="true"
import numpy as np
from anytimeline import Timeline

rng = np.random.default_rng(0)
ns = np.sort(rng.integers(0, 50_000, 300)).astype("timedelta64[ns]")
plot = Timeline(title="Interrupts per CPU, in nanoseconds", height=220)
plot.events({"time": ns, "cpu": rng.integers(0, 4, 300)}, lane="cpu", symbol="tick", size=12)
print(plot._embed_html())
```

## Plain numbers

Numbers are shown as numbers. If they are times, say in which unit with `time_unit=`, and the
axis shows them as durations:

```python
plot = Timeline(time_unit="s")  # 0.25 means a quarter of a second
plot.events(df, time="seconds_since_start")
```

## Centuries

Dates before 1677 and after 2262 work too (they are kept in a coarser unit than
nanoseconds):

```python exec="on" source="above" session="time" html="true"
history = {
    "time": np.array(
        [
            "1066-10-14",
            "1215-06-15",
            "1492-10-12",
            "1789-07-14",
            "1914-06-28",
            "1969-07-20",
            "1989-11-09",
        ],
        dtype="datetime64[D]",
    ),
    "region": ["Europe", "Europe", "Americas", "Europe", "Europe", "Space", "Europe"],
    "event": [
        "Hastings",
        "Magna Carta",
        "Columbus lands",
        "Bastille",
        "Sarajevo",
        "Moon landing",
        "Berlin Wall",
    ],
}
plot = Timeline(title="Centuries", height=220)
plot.events(history, lane="region", text="event", symbol="diamond", size=10)
print(plot._embed_html())
```

## Only an order, no time

Steps of a protocol, or events with a logical clock, have an order but no time. Leave out
`time=` and give `order=`; the plot then has only the Order scale:

```python exec="on" source="above" session="time" html="true"
from anytimeline import Route

steps = {
    "step": [1, 2, 3, 4, 5, 6],
    "actor": ["client", "server", "db", "server", "client", "server"],
    "what": ["request", "parse", "query", "render", "receive", "log"],
}
plot = Timeline(title="A request, step by step", height=200)
plot.events(
    steps, time=None, order="step", lane="actor", text="what", route=Route("actor", color="theme")
)
print(plot._embed_html())
```

## Equal times

Events with the same time keep the order of `order=` if you give it (a sequence number, the
line in a log file), else the order of the table.

See also: [time from nanoseconds to centuries](../explanation/time.md).
