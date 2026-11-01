# How to make images for slides

There are two ways to get a plot into PowerPoint, Keynote, a report or an e-mail: export
what you see in the plot, or save images from Python, for example one for every hour of a
day.

## Export what you see

Click the **Export** button in the plot's toolbar (the arrow into a tray), or press ++e++,
and choose:

| Entry | What you get |
| --- | --- |
| **Copy image** | a PNG on the clipboard: paste it into your slide |
| **Copy as vector** | an SVG on the clipboard, sharp at any size, with the PNG beside it for apps that don't take SVG; the app you paste into picks one |
| **Download PNG** | an image file, named after the plot's title |
| **Download SVG** | a vector image file (PowerPoint for Microsoft 365, Keynote and Word take it as a picture) |
| **Save PNG next to the notebook** | Python writes the file in the notebook's working folder, and the plot says where |
| **Save SVG next to the notebook** | the same, as SVG |

The menu lists only what works where the plot is. Copying needs a secure page (`https://`,
or a notebook on your own computer at `localhost`); Copy as vector also needs Chrome, Edge
or VS Code. Saving next to the notebook works also where copying and downloading are
blocked (VS Code).

The PNG is the plot as it is on screen: the title, the lanes and marks in view, folded as
you folded them, and the legend, at twice the screen's resolution and in the plot's light
or dark theme. Zoom and fold first to show what matters.

The SVG is drawn by Python for the same view: the same size, time range, lanes in sight,
folded lanes and theme. So it needs a running kernel; while a cell runs, it waits for it.
It differs from the screen in small ways: a story's text goes beside its marks rather than
in boxes on stems, and the fonts are those of the app you paste into.

!!! tip "PNG or SVG?"
    A PNG looks the same everywhere and is quick to show in a slide. An SVG stays sharp
    when you enlarge it, and in PowerPoint you can recolor it or ungroup it into shapes. It
    holds every mark as a shape, though: with many thousands of marks in view it can be
    several MB and slow to show. **Copy as vector** then says so; use **Copy image**
    instead, or zoom in.

A page saved with [`save_html`](share.md), or a plot shown with `display="html"`, has no
Python behind it: its Export menu offers Copy image and Download PNG.

## Save an image from Python

[`save_image`][anytimeline.Timeline.save_image] draws the plot in Python and writes the
file, without a browser, so it works in scripts, tests and CI too:

```python
from anytimeline import View

plot.save_image("checkout-trace.svg")                       # shapes and text, for slides
plot.save_image("checkout-trace.png", width=1200, scale=2)  # needs anytimeline[png]
plot.save_image("db.svg", view=View(start, end, lanes=["db"]), theme="dark")
```

- `.svg` writes shapes, lines and text (no clip paths, filters or images), which slides
  import as shapes you can edit. `.png` needs the optional `resvg-py`:
  `pip install 'anytimeline[png]'`. [`to_svg`][anytimeline.Timeline.to_svg] gives the SVG
  as text.
- `width` and `height` set the size in pixels (default 960 wide, and the plot's height);
  `scale` the pixels per pixel of a PNG (default 2).
- `view` sets what it shows; by default the plot's
  [`view`][anytimeline.Timeline.view], as shown or set last. Once the plot was shown, lanes
  are folded as you left them; before, as the plot starts.
- `Timeline(font_size=16)` makes the text larger, on screen and in images.

[`save_png`][anytimeline.Timeline.save_png] saves the PNG the Export menu makes (the plot as
it is on screen) into a file of your choice. The plot must be on screen, and the file is
written when the browser sends it: in Jupyter right after the cell has run.

## An image for every hour

A loop over views saves one image each:

```python
import numpy as np
from pathlib import Path

Path("images").mkdir(exist_ok=True)
day = np.datetime64("2026-10-12T00:00")
for hour in range(24):
    start = day + np.timedelta64(hour, "h")
    end = start + np.timedelta64(1, "h")
    plot.save_image(f"images/hour-{hour:02}.svg", view=View(start, end))
```

## Straight into a PowerPoint file

With the [python-pptx](https://python-pptx.readthedocs.io/) package, a script puts the
images on slides, one per slide (PNG: python-pptx does not take SVG):

```python
from pptx import Presentation
from pptx.util import Inches

deck = Presentation()
deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)  # 16:9
for hour in range(24):
    start = day + np.timedelta64(hour, "h")
    image = plot.save_image(
        f"images/hour-{hour:02}.png", view=View(start, start + np.timedelta64(1, "h")),
        width=1200, height=680,
    )
    slide = deck.slides.add_slide(deck.slide_layouts[6])  # a blank slide
    slide.shapes.add_picture(str(image), Inches(0.4), Inches(0.3), height=Inches(6.9))
deck.save("day.pptx")
```

Give the plot a `title` so that every image says what it shows.
