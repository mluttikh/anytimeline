# Why overlapping events move

Events have no width in time, but their marks do. Two events a millisecond apart, seen over
an hour, would be drawn on top of each other: you would see one where there are two.

So events that would overlap within a lane are spread over **sub-rows**: the first event in
the middle of the lane, the next one just above, then below, then further out. Each event
goes to the first sub-row that has room, from left to right; when every sub-row is taken, it
is drawn over the one that has been free longest.

The result is a *beeswarm*: a burst of events becomes a column whose height shows how many
there are. It is recomputed when you zoom (zoomed in, events move apart and back to the
middle), not while you pan.

The sub-rows are **as far apart as the lane allows**. When there is room, a mark and a pixel
apart, so marks do not overlap at all; when the rows the events need do not fit that way,
they close up, down to 0.6 of a mark, where neighbouring rows overlap a little. A margin at
the lane's edges keeps the columns of neighbouring lanes apart. All lanes of a layer use the
same spacing, so a column's height compares between lanes: twice as tall, about twice as
many events.

A taller plot, or full screen, gives each lane room for more sub-rows, further apart: the
extra height shows more, not only bigger. In a full-screen plot of the example log, the burst
of requests went from almost every event overlapping a neighbour to none.

Smaller marks need less room (`mark_scale=`, or the Display panel). To keep every event on
its lane's line, switch spreading off: `dodge=False`, the Display panel, or the key **d**
(or `overlap="overlay"` for one layer).
