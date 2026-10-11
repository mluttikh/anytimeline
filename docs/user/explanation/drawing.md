# How the plot is drawn

## Python and the browser

Python reads your table, sorts the events by lane and time, and turns colors, symbols and
sizes into compact binary arrays. It sends the browser a small description of the plot and
the arrays on request, in chunks, each identified by its content, so the same data is never
sent twice. Bulk data is not stored in the notebook file.

The browser does everything interactive: the camera, the axis, hover, the toolbar. Python
hears back only what changes your data's meaning: the selection (as rows of your table), the
tool, the scale, the text size, and the visible range.

## Three backends

The browser draws with the best of three backends it can use:

- **WebGPU**: modern graphics in the browser (Chrome, Edge, Safari, Firefox).
- **WebGL2**: the older standard, in every current browser.
- **Canvas 2D**: no graphics chip needed, for laptops without one; slower, and limited to
  40,000 events per frame.

`Timeline(renderer=...)` chooses one; the info line at the top names the one in use. All three
draw the same picture: the shapes are defined once and drawn by each.

## Three layers of canvas

The plot stacks three canvases: at the back the lane bands and grid lines, in the middle the
events and routes (drawn by the backend), at the front the axis, the lane names, labels and
the hover ring. Only the middle one needs the graphics chip.
