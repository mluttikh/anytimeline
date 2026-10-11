# Why overlapping events move

Events have no width in time, but their marks do. Two events a millisecond apart, seen over
an hour, would be drawn on top of each other: you would see one where there are two.

So events that would overlap within a lane are spread over **sub-rows**: the first event in
the middle of the lane, the next one just above, then below, then further out. Each event
goes to the first sub-row that has room, from left to right; when every sub-row is taken, it
is drawn over the one that has been free longest.

The result is a narrow *beeswarm*: a burst of events becomes a column whose height shows how
many there are. It is recomputed when you zoom (zoomed in, events move apart and back to the
middle), not while you pan.

How many sub-rows there are depends on the lane's height, up to 31. A taller plot, or full
screen, gives each lane more sub-rows, so bursts spread out further: the extra height shows
more, not only bigger.

To keep every event in the middle of its lane, use `overlap="overlay"`.
