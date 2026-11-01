# Install anytimeline

```bash
pip install anytimeline
```

or, in a [uv](https://docs.astral.sh/uv/) project:

```bash
uv add anytimeline
```

The package includes the JavaScript that draws the plots, so it works offline and needs no
Node.js. It needs Python 3.12 or newer, and a notebook that shows
[anywidget](https://anywidget.dev) widgets: JupyterLab, Jupyter Notebook 7, VS Code or
marimo.

To read tables, install the library you use: Polars, pandas, PyArrow, DuckDB or Ibis. A dict of
NumPy arrays works without any of them.

## Without the widget, on a server

A web app, a report job or a container that only makes pictures and pages
([`save_image`][anytimeline.Timeline.save_image], [`to_html`][anytimeline.Timeline.to_html],
[`save_html`][anytimeline.save_html]) does not need the notebook widget. anywidget is installed
with anytimeline, and with it ipywidgets, IPython and about 20 more packages; leave them out
with:

```bash
pip install --no-deps anytimeline numpy narwhals   # on Windows also tzdata
```

`import anytimeline` loads no widget package. Pictures, pages, the selection and
[`on_select`][anytimeline.Timeline.on_select] work; showing a plot as a widget says what to
install.

## From the source

```bash
git clone https://github.com/mluttikh/anytimeline && cd anytimeline
(cd js && npm ci && npm run build)   # the JavaScript bundle (needs Node.js 20+)
uv sync
```
