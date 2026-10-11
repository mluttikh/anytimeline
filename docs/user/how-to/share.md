# Share a plot

A plot in a notebook needs the notebook's Python to draw. To show it to someone who does not
run the notebook, save it as a page or as a picture.

## As a page

[`save_html`][anytimeline.Timeline.save_html] writes one HTML file with everything in it: the
data, the code that draws it and the styles. It opens in any browser, also without a network,
and stays interactive: pan, zoom, hover (with the `tooltip=` columns), Time / Order, folding
traces and full screen. The plot fills the browser window.

```python
plot.save_html("checkout-trace.html")
```

Several plots go in one page with [`anytimeline.save_html`][anytimeline.save_html]
(`save_html("page.html", plot_a, plot_b)`); linked plots stay linked there.

Attach the file to a ticket, mail it, or put it on a web server. Selecting is the one thing
it cannot do: that needs Python, which turns a selection into rows of your table.

The file holds all the data of the plot, so it grows with it: about 30 bytes per event plus
the tooltip columns (tooltips are left out for layers of more than a million values).

## As a picture

The toolbar's **Save as PNG** button (the arrow into a tray) downloads the plot as it is on
screen: the title, the lanes and marks in view, and the legend, at twice the screen's
resolution, named after the title. Zoom and fold first to show what matters.

From Python, [`save_png`][anytimeline.Timeline.save_png] does the same into a file of your
choice, also where a notebook blocks downloads (VS Code):

```python
plot.save_png("checkout-trace.png")
```

The picture is drawn in the browser, so the plot must be on screen, and the file is written
when the browser sends it: in Jupyter right after the cell has run.
