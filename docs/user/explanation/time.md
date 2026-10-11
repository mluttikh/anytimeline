# Time from nanoseconds to centuries

A plot may span a microsecond of a CPU trace or a thousand years of history. anytimeline
handles both with one rule.

## One unit per plot

Times become whole numbers of one unit, chosen per plot: the coarsest of seconds,
milliseconds, microseconds and nanoseconds that keeps every value exact. Millisecond log
timestamps give milliseconds; a trace with nanoseconds gives nanoseconds. Each plot counts
from its earliest event.

A 64-bit count of nanoseconds reaches only from 1677 to 2262, so dates outside that range are
kept in microseconds, milliseconds or seconds: a count of seconds reaches hundreds of billions
of years.

## Precision in the browser

The graphics chip computes with 32-bit floats, which hold about 7 significant digits: over a
day in nanoseconds, that is only about 5 ms. The browser therefore sends positions relative
to a point near the view, and moves that point when you move far from it, so a mark lands on
the right pixel at any zoom, down to a nanosecond. Tick labels are computed with exact
integers, so they are exact anywhere.

## Calendars and time zones

The time axis follows the calendar of the plot's time zone: hour ticks stay on the local
clock, and a day with a daylight-saving change has 23 or 25 hours. Ticks run from
nanoseconds (`.000 000 110`) through seconds, minutes, days, months and years to centuries;
a second row above the ticks gives the context (the date of hour ticks, the second of
sub-second ticks).
