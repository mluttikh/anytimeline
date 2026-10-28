"""Pictures drawn in Python (``Timeline.save_image``, ``to_svg``): every kind of plot draws,
as SVG that slides import as shapes, with what the browser shows in that view."""

from __future__ import annotations

import importlib.util
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
from kinds import every_kind

from anytimeline import Timeline, View, levels
from anytimeline.synthetic import instants, service_log

SVG = "{http://www.w3.org/2000/svg}"

# what PowerPoint, Keynote and Google Slides import as shapes and text: no clip paths, masks,
# filters, patterns, CSS, images or foreign objects
ELEMENTS = {"svg", "title", "defs", "linearGradient", "stop", "g", "rect", "line", "path", "text"}
ATTRIBUTES = {
    "xmlns", "width", "height", "viewBox", "font-family", "transform", "x", "y", "x1", "y1",
    "x2", "y2", "d", "rx", "fill", "fill-opacity", "stroke", "stroke-width", "stroke-opacity",
    "stroke-dasharray", "stroke-linejoin", "stroke-linecap", "font-size", "font-weight",
    "text-anchor", "id", "gradientUnits", "offset", "stop-color", "stop-opacity",
}  # fmt: skip

KINDS = every_kind()


def parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def texts(root: ET.Element) -> list[str]:
    return [t.text or "" for t in root.iter(f"{SVG}text")]


@pytest.mark.parametrize("name", list(KINDS))
def test_every_kind_draws_as_svg_slides_import(name: str) -> None:
    svg = KINDS[name].to_svg(width=800)
    root = parse(svg)
    assert root.tag == f"{SVG}svg"
    assert root.get("width") == "800"
    for el in root.iter():
        tag = el.tag.removeprefix(SVG)
        assert tag in ELEMENTS, tag
        assert set(el.attrib) <= ATTRIBUTES, (tag, set(el.attrib) - ATTRIBUTES)
    for el in root.iter(f"{SVG}rect"):
        assert float(el.get("width", "0")) >= 0
        assert float(el.get("height", "0")) >= 0
    for el in root.iter():
        for value in el.attrib.values():
            assert not re.search(r"nan|inf", value, re.IGNORECASE), value


def test_the_picture_has_the_plots_lanes_axis_title_and_legend() -> None:
    plot = KINDS["events"]
    words = texts(parse(plot.to_svg()))
    for lane in ("gateway", "auth", "api", "cache", "db"):
        assert lane in words
    assert "Events" in words  # the title
    assert "level" in words  # the legend
    assert "info" in words
    assert any(re.fullmatch(r"\d\d:\d\d", w) for w in words)  # the time axis


def test_a_view_zooms_and_scrolls_the_picture() -> None:
    log = service_log(400, seed=1)
    plot = Timeline().events(log, lane="service", text="{event}")
    whole = texts(parse(plot.to_svg()))
    t0 = log["time"].min() + np.timedelta64(60, "s")
    zoomed = parse(plot.to_svg(view=View(t0, t0 + np.timedelta64(2, "s"), lanes=("db",))))
    labels = texts(zoomed)
    # fractions of seconds on the axis, the seconds above them, and the events' labels
    assert any(re.fullmatch(r"\.\d00", w) for w in labels)
    assert any(re.fullmatch(r"Oct 12, 2026 08:01:1\d", w) for w in labels)
    assert not any(re.fullmatch(r"\.\d00", w) for w in whole)
    assert "handled" in labels
    # the view set on the plot is the picture's
    plot.view = View(t0, t0 + np.timedelta64(2, "s"))
    assert plot.to_svg() == plot.to_svg(view=plot.view)


def test_the_selection_fades_the_rest_and_rings_what_is_selected() -> None:
    plot = Timeline().events(service_log(50, seed=2), lane="service")
    plain = plot.to_svg()
    plot.selection = {"events": [3, 4]}
    selected = plot.to_svg()
    assert 'fill-opacity="0.2"' in selected
    assert 'fill-opacity="0.2"' not in plain
    assert "#e8590c" in selected  # the rings, in the selection's colour


def test_bars_progress_milestones_and_dependencies() -> None:
    svg = KINDS["gantt"].to_svg()
    root = parse(svg)
    words = texts(root)
    assert "Design" in words
    # milestones are diamonds, dependencies arrows (paths), the marker for today is dashed
    assert 'stroke-dasharray="5 3"' in svg
    assert len(list(root.iter(f"{SVG}rect"))) > 10


def test_layers_sent_as_levels_draw_their_bins_or_their_marks() -> None:
    plot = KINDS["events_levels"]
    root = parse(plot.to_svg())
    paths = len(list(root.iter(f"{SVG}path")))
    rects = len(list(root.iter(f"{SVG}rect")))
    assert rects > 20 or paths > 0  # bins zoomed out
    lo, hi = plot._spec["time"]["extent"]
    base = plot._base
    assert base is not None
    a = base.to_value(lo + (hi - lo) * 0.5)
    b = base.to_value(lo + (hi - lo) * 0.5005)
    zoomed = plot.to_svg(view=View(a, b))
    assert zoomed != plot.to_svg()


def test_a_selection_fades_the_bins_that_hold_none_of_it(monkeypatch) -> None:
    monkeypatch.setattr(levels, "LEVELS_FROM", 200)
    monkeypatch.setattr(levels, "RAW_MARKS", 50)
    plot = Timeline().events(instants(4000, lanes=6), lane="lane")
    assert 'fill-opacity="0.22"' not in plot.to_svg()
    plot.selection = {"events": [0]}
    svg = plot.to_svg()
    bins = [r for r in parse(svg).iter(f"{SVG}rect") if r.get("fill") == "#1f77b4"]
    faded = [r for r in bins if r.get("fill-opacity") == "0.22"]
    assert len(bins) - len(faded) == 1  # the bin of the selected event
    assert len(faded) > 100


def test_dark_theme() -> None:
    svg = KINDS["events"].to_svg(theme="dark")
    assert 'fill="#12171d"' in svg  # the background


def test_story_text_goes_in_boxes_on_stems() -> None:
    svg = KINDS["story"].to_svg(height=420)
    assert 'rx="6"' in svg  # rounded boxes
    assert "C" in "".join(re.findall(r' d="([^"]*)"', svg)) or "stroke-linecap" in svg


def test_save_image_writes_svg(tmp_path: Path) -> None:
    out = KINDS["events"].save_image(tmp_path / "plot.svg")
    assert out == tmp_path / "plot.svg"
    assert out.read_text(encoding="utf-8").startswith("<svg")


@pytest.mark.skipif(importlib.util.find_spec("resvg_py") is None, reason="needs resvg-py")
def test_save_image_writes_png(tmp_path: Path) -> None:
    out = KINDS["gantt"].save_image(tmp_path / "plot.png", width=600, scale=2)
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width = int.from_bytes(data[16:20], "big")
    assert width == 1200


def test_wrong_arguments_say_what_is_wrong(tmp_path: Path) -> None:
    plot = KINDS["events"]
    with pytest.raises(ValueError, match=r"\.svg or \.png"):
        plot.save_image(tmp_path / "plot.jpg")
    with pytest.raises(ValueError, match="theme"):
        plot.to_svg(theme="blue")  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValueError, match="width"):
        plot.to_svg(width=50)
    with pytest.raises(ValueError, match="no layers"):
        Timeline().to_svg()


def test_the_same_plot_gives_the_same_picture() -> None:
    plot = KINDS["intervals_packed"]
    assert plot.to_svg() == plot.to_svg()
