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

To read tables, install the library you use: Polars, pandas, PyArrow or DuckDB. A dict of
NumPy arrays works without any of them.

## From the source

```bash
git clone <the repository> && cd anytimeline
(cd js && npm ci && npm run build)   # the JavaScript bundle (needs Node.js 20+)
uv sync
```
