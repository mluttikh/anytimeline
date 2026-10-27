# Fix a plot that doesn't show

**"Waiting for data from Python"** in the plot: the notebook's kernel is not running, or the
plot belongs to a kernel that was restarted. Run the cell again.

**"Python no longer answers for this plot"**: the kernel restarted after the plot was drawn,
so it cannot fetch tooltips or selections. Run the cell again.

**Nothing at all below the cell**: the notebook does not show widgets. Use JupyterLab 4,
Jupyter Notebook 7, VS Code with the Jupyter extension, or marimo. In an older Jupyter,
install `anywidget` in the same environment as the kernel.

**The plot is slow, or the info line says `canvas2d`**: the browser has no usable graphics
chip for WebGPU or WebGL2, so the plot draws on the CPU. Check that hardware acceleration is
on in the browser's settings. You can choose the backend with `Timeline(renderer="webgl2")`;
the info line at the top of the plot names the one in use, and `plot.dev.perf` reports it.

**Scrolling scrolls the page, not the plot**: click the plot first; then the wheel zooms.
**Ctrl** (⌘ on a Mac) + wheel zooms at any time.

**`TypeError: a time column must hold datetimes, durations or numbers`**: the column is
text; parse it first, for example `pl.col("t").str.to_datetime()`.

**`TypeError: the layers' times must be of one kind`**: one layer has datetimes and another
durations or numbers; convert one of them.
