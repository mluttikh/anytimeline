import datetime as dt

import numpy as np
import pandas as pd
import polars as pl
import pytest

from anytimeline.timebase import UNITS, time_base, times


def test_unit_is_the_coarsest_that_keeps_values_exact():
    ms = times(np.array(["2026-10-12T08:00:00.250", "2026-10-12T08:00:01"], dtype="datetime64[ms]"))
    base = time_base([ms])
    assert base.unit == "ms"
    assert base.ticks(ms).tolist() == [0.0, 750.0]
    whole = times(np.array(["2026-10-12T08:00:00", "2026-10-12T08:00:05"], dtype="datetime64[ns]"))
    assert time_base([whole]).unit == "s"
    nano = times(np.array([1, 2_000_000_001], dtype="timedelta64[ns]"))
    assert time_base([nano]).unit == "ns"


def test_dates_before_1677_use_a_coarser_storage_unit():
    t = times(np.array(["1066-10-14", "2001-09-11"], dtype="datetime64[D]"))
    assert t.per == UNITS["s"]
    base = time_base([t])
    assert base.unit == "s"
    ticks = base.ticks(t)
    assert ticks[0] == 0
    assert ticks[1] == pytest.approx((dt.date(2001, 9, 11) - dt.date(1066, 10, 14)).days * 86400)
    assert base.to_value(ticks[1]) == np.datetime64("2001-09-11T00:00:00", "s")


def test_ticks_stay_exact_across_mixed_storage_units():
    fine = times(np.array(["2026-10-12T08:00:00.000001"], dtype="datetime64[us]"))
    coarse = times(np.array(["2026-10-12T08:00:01"], dtype="datetime64[s]"))
    base = time_base([fine, coarse])
    assert base.unit == "us"
    assert base.ticks(fine).tolist() == [0.0]
    assert base.ticks(coarse).tolist() == [999_999.0]


def test_numbers_and_durations():
    plain = times(np.array([10.0, 12.5]))
    assert plain.kind == "number"
    base = time_base([plain])
    assert base.ticks(plain).tolist() == [0.0, 2.5]
    secs = times(np.array([0.25, 1.5]), unit="s")
    assert secs.kind == "duration"
    assert time_base([secs]).unit == "ms"
    with pytest.raises(ValueError, match="unknown unit"):
        times(np.array([1.0]), unit="minutes")


def test_missing_values_and_errors():
    t = times(np.array(["2026-01-01", "NaT"], dtype="datetime64[s]"))
    assert t.valid.tolist() == [True, False]
    with pytest.raises(TypeError, match="boolean"):
        times(np.array([True, False]))
    with pytest.raises(TypeError, match="one kind"):
        time_base([times(np.array([1.0])), t])


def test_python_and_pandas_datetimes_with_time_zones():
    aware = times(
        np.array([dt.datetime(2026, 3, 29, 1, 30, tzinfo=dt.UTC)], dtype=object), timezone=None
    )
    assert aware.kind == "datetime"
    assert aware.timezone == "UTC"
    ts = pd.Series(pd.to_datetime(["2026-03-29 03:30"]).tz_localize("Europe/Amsterdam"))
    t = times(np.asarray(ts.to_numpy()), timezone="Europe/Amsterdam")
    base = time_base([t])
    assert base.timezone == "Europe/Amsterdam"
    # 03:30 CEST is 01:30 UTC
    assert base.to_value(0) == np.datetime64("2026-03-29T01:30:00")


def test_polars_time_zone_reaches_the_plot():
    from anytimeline import Timeline

    df = pl.DataFrame(
        {
            "t": [
                dt.datetime(2026, 1, 1, 12, tzinfo=dt.UTC),
                dt.datetime(2026, 1, 1, 13, tzinfo=dt.UTC),
            ]
        }
    ).with_columns(pl.col("t").dt.convert_time_zone("America/New_York"))
    plot = Timeline().events(df, time="t")
    assert plot._spec["time"]["timezone"] == "America/New_York"
    assert plot._spec["time"]["unit"] == "s"
