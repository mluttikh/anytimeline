"""A marimo app with a plot shown as HTML (display="html"), exported by `marimo export html`
for html_display.spec.ts (scripts/make_scenes.py)."""

import marimo

app = marimo.App()


@app.cell
def _():
    from anytimeline import Timeline
    from anytimeline.synthetic import service_log

    plot = Timeline(title="Exported from marimo", display="html", height=300)
    plot.events(service_log(200), lane="service", color="level")
    return (plot,)


if __name__ == "__main__":
    app.run()
