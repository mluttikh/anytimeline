"""A marimo app for the notebook-connection test (notebook.spec.ts): an event chart, and a
cell that shows what Python knows of it."""

import marimo

app = marimo.App()


@app.cell
def _():
    import json

    import marimo as mo

    from anytimeline import Timeline
    from anytimeline.synthetic import service_log

    log = service_log(300)
    plot = Timeline(title="Connection test", renderer="webgl2", height=360)
    plot.events(
        log,
        time="time",
        lane="service",
        color="level",
        symbol="event",
        order="seq",
        route="request",
        tooltip=["request", "user"],
    )
    widget = mo.ui.anywidget(plot)
    widget
    return json, mo, plot, widget


@app.cell
def _(json, mo, plot, widget):
    # re-runs whenever the plot changes a synced setting: what Python knows of the plot
    widget.value
    state = {
        "selected": {name: len(rows) for name, rows in plot.selection.items()},
        "xscale": plot.xscale,
        "tool": plot.tool,
        "renderer": plot.perf.get("renderer"),
    }
    mo.Html(f"<pre id='python-state'>{json.dumps(state, sort_keys=True)}</pre>")
    return


@app.cell
def _(plot):
    import anytimeline.marimo

    get_selection = anytimeline.marimo.selection(plot)
    runs = []
    return get_selection, runs


@app.cell
def _(get_selection, json, mo, plot, runs):
    # re-runs only when the selection changes (anytimeline.marimo.selection): its runs, and
    # the requests of the rows selected
    runs.append(sum(len(rows) for rows in get_selection().values()))
    picked = plot.selected("events")["request"].tolist()
    mo.Html(f"<pre id='selection-runs'>{json.dumps({'runs': runs, 'requests': picked})}</pre>")
    return


if __name__ == "__main__":
    app.run()
