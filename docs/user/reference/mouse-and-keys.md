# Mouse and keys

Press **?** in a plot to see this list there. Keys work while the plot has focus (after a
click into it).

## Tools

The toolbar's first three buttons choose what a drag does; `plot.tool` sets it from Python.

| | Pan (default) | Zoom | Select |
| --- | --- | --- | --- |
| Drag | move through time and lanes | zoom to the time range | select the events in a box |
| Shift + drag | zoom to a time range | the same | add what is in the box |
| Click | nothing | zoom in 2× | select the event |
| Shift / Ctrl / ⌘ + click | add or remove the event | — | add or remove the event |
| Alt + click | remove the event | zoom out 2× | remove the event |
| Alt + drag | — | — | remove what is in the box |
| Double-click | the whole timeline | — | — |

Select is offered while something can be selected (`selection_mode` is not `"none"`) and a
notebook is running.

## Every tool

| Gesture | Effect |
| --- | --- |
| Wheel | zoom time (after a click into the plot, in full screen, or with Ctrl/⌘) |
| Shift + wheel | scroll the lanes |
| Hold Space + drag | pan |
| Drag on the time axis | zoom to that range (with Select: select that range in all lanes) |
| Hover | the event's details |

## Lanes in a tree

For spans ([`spans`](../how-to/traces.md)) and tasks with sub-tasks (`parent=`):

| Gesture | Effect |
| --- | --- |
| Click a name with a triangle | fold or unfold the lanes under it |
| Alt + click a name | the same, with every level under it |
| Double-click a name | zoom to it and everything under it |
| <kbd>[</kbd> <kbd>]</kbd> | fold all, unfold all |

## Keys

| Key | Effect |
| --- | --- |
| <kbd>p</kbd> <kbd>z</kbd> <kbd>s</kbd> | Pan, Zoom, Select |
| <kbd>t</kbd> | Time / Order |
| <kbd>0</kbd> or <kbd>Home</kbd> | the whole timeline |
| <kbd>Backspace</kbd> | the previous view |
| <kbd>+</kbd> <kbd>−</kbd> | zoom in, out |
| <kbd>←</kbd> <kbd>→</kbd> | move through time |
| <kbd>↑</kbd> <kbd>↓</kbd> | scroll the lanes |
| <kbd>d</kbd> | spread overlapping events, or draw them on the lane's line |
| <kbd>l</kbd> | show or hide the legend |
| <kbd>f</kbd> | full screen |
| <kbd>/</kbd> or <kbd>Ctrl</kbd>/<kbd>⌘</kbd> <kbd>F</kbd> | find text and lanes; <kbd>Enter</kbd>, <kbd>Shift</kbd> <kbd>Enter</kbd>: the next, the previous match |
| <kbd>.</kbd> <kbd>,</kbd> | the next, the previous mark of the lane |
| <kbd>F</kbd> | fit the view to that mark |
| <kbd>a</kbd> | annotate: then drag over a time range, or click a time, and type its text |
| <kbd>c</kbd> | on a mark, then on another: an arrow between them |
| <kbd>Ctrl</kbd>/<kbd>⌘</kbd> <kbd>Z</kbd> | undo a change of the selection (with <kbd>Shift</kbd>: redo) |
| <kbd>?</kbd> | this list |
| <kbd>Esc</kbd> | cancel a box being drawn, close the search box, drop the mark found, else clear the selection; in full screen, leave it |

See [Summarise, find and annotate](../how-to/explore.md).

## Touch

A plot waits for a tap: before it, a finger scrolls the page. After it, one finger pans and
two pinch to zoom, until you tap outside the plot.

## The toolbar

From left to right: Pan, Zoom, Select · Time, Order · Back, Home · Clear the selection (while
there is one) · Legend · Display (text size, mark size, spreading) · Save as PNG · Full screen ·
Mouse and keys (?).
