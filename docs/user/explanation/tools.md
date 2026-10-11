# Why the tools work the way they do

The plot follows three rules:

1. **Navigating never selects, and selecting never navigates.** Moving through time is
   something you do all the time; a selection is something you build up and keep.
2. **The default tool cannot change the selection by accident.** With Pan, a plain click
   does nothing, because a click often only gives the plot focus, or is a short drag that
   didn't move. Selecting a single event with Pan takes a deliberate Shift-click.
3. **The active tool shows**: a pressed button, the cursor, and a hint beside the counts
   ("Drag: pan · Shift-drag: zoom to a range").

## Zoom is in time only

A timeline's two axes are not alike: time is continuous and zoomable, lanes are rows. So a
zoom box is a band over all lanes, with the length of the range it shows, and the wheel zooms
time. Lanes scroll instead.

## No lasso

Lanes are rows, so a box of time × lanes covers what a lasso would on a scatter plot. One
tool fewer to learn.

## The time axis is a handle

Dragging on the time axis zooms to that range in any tool, and with Select selects that range
over all lanes. Trace viewers use the axis the same way; it is the quickest way to zoom
exactly.

## The wheel waits for a click

In a notebook the wheel scrolls the page. A plot that zoomed on every scroll would catch the
page's scrolling, so the wheel zooms only after a click into the plot, in full screen, or
with Ctrl or ⌘ held.
