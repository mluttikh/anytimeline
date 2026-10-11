# What an event chart is for

An event chart draws **instants**: one mark per event at the moment it happened, without a
duration. It answers three questions at a glance: *what* happened (color, symbol), *when*
(position along time), and *in what order* (which mark comes first).

The idea is old and has many names. In survival analysis an *event chart* draws a line per
patient with a symbol for each event (Lee, Hess and Dubin, *The American Statistician*,
2000). Process mining calls it a *dotted chart*: a row per case, a dot per activity.
Neuroscience calls it a *raster plot*: a row per neuron, a tick per spike. Log viewers and
trace viewers draw the same picture with a lane per host, thread or service.

## Lanes

Lanes are rows of a category: a service, a host, a patient, a request. They turn a cloud of
events into rows you can compare: when did this lane get busy, which lane failed first? Their
order matters: put lanes in the order work flows through them (`lane_order=`), or by when they
started (`sort="first"`).

## Time or order

On the **Time** scale, distance is elapsed time: gaps and bursts are visible, but events a
microsecond apart sit on top of each other. On the **Order** scale every event gets the same
width, one after another: the order of a burst is readable, at the cost of the real gaps,
which the axis marks with a break and the time skipped. The two answer different questions,
so the plot has a switch rather than a choice made for you.

Timelines researchers call these the *chronological* and *sequential* scales; the break
marks make the Order scale *sequential with interim durations* (Brehmer et al., *Timelines
Revisited*, 2017).

## Routes

When events belong to a group that moves between lanes, such as a request passing through
services, a line through the group's events in order shows its path. On the Order scale,
crossing lines show where one request overtook another.
