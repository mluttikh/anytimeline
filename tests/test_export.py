"""The Export menu's requests to Python: an SVG of the view as shown, and pictures saved next
to the notebook (``{"type": "figure"}``, ``{"type": "save-image"}``)."""

import pytest

from anytimeline import Timeline, View
from anytimeline.synthetic import service_log, traces


def answers(plot, monkeypatch):
    """The answers the plot's widget sends."""
    sent = []
    monkeypatch.setattr(plot.widget, "send", lambda content, buffers=None: sent.append(content))
    return sent


def ask(plot, content, buffers=None):
    plot.widget._on_msg(plot.widget, {"request": 7, **content}, buffers or [])


def log_plot():
    return Timeline(title="Checkout").events(service_log(30), lane="service", order="seq")


def view_of(plot, start, end):
    """A figure request for a range given as the data's times (the browser sends ticks)."""
    t0, t1 = plot._ticks(start), plot._ticks(end)
    names = [str(n) for n in plot._spec["lanes"]["names"]]
    return {"width": 700, "height": 300, "range": [t0, t1], "lanes": names, "open": []}


def test_the_svg_is_the_view_as_shown(monkeypatch):
    plot = log_plot()
    sent = answers(plot, monkeypatch)
    log = service_log(30)
    start, end = log["time"][3], log["time"][20]
    ask(plot, {"type": "figure", "theme": "dark", **view_of(plot, start, end)})
    [answer] = sent
    assert answer["type"] == "answer"
    assert answer["request"] == 7
    assert "error" not in answer
    names = [str(n) for n in plot._spec["lanes"]["names"]]
    expected = plot.to_svg(width=700, height=300, view=View(start, end, names), theme="dark")
    assert answer["svg"] == expected
    assert 'width="700" height="300"' in answer["svg"]


def test_folded_lanes_are_drawn_folded():
    tr = traces(2, seed=1)
    plot = Timeline().spans(tr.spans, expand="all")
    names = [str(n) for n in plot._spec["lanes"]["names"]]
    tree = plot._spec["lanes"]["tree"]
    folded = [s < 2 for s in tree["size"]]  # every lane with lanes under it folded
    open_svg = plot.to_svg(width=800, height=0)
    shut = plot._figure({"width": 800, "height": 0, "open": folded})
    assert sum(n in open_svg for n in names) > sum(f">{n}<" in shut for n in names)
    # the browser reports its folds with the view: save_image then folds as shown
    plot._shown({"range": [0, 1], "lanes": names[:1], "open": folded})
    assert plot.to_svg(width=800, height=0) == plot._figure(
        {"width": 800, "height": 0, "open": folded}
    )
    assert plot.to_svg(width=800, height=0) != plot._figure(
        {"width": 800, "height": 0, "open": [True] * len(folded)}
    )
    # folds of another tree (the plot changed since) are left out
    plot._shown({"range": [0, 1], "lanes": names[:1], "open": [True]})
    assert plot.to_svg(width=800, height=0) == plot._figure(
        {"width": 800, "height": 0, "open": [True] * len(folded)}
    )


def test_save_next_to_the_notebook_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plot = log_plot()
    sent = answers(plot, monkeypatch)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    for _ in range(2):
        ask(plot, {"type": "save-image", "name": "checkout.png"}, [memoryview(png)])
    assert [a["path"] for a in sent] == [
        str((tmp_path / "checkout.png").resolve()),
        str((tmp_path / "checkout-2.png").resolve()),
    ]
    assert (tmp_path / "checkout-2.png").read_bytes() == png


def test_save_an_svg_drawn_in_python(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plot = log_plot()
    sent = answers(plot, monkeypatch)
    ask(plot, {"type": "save-image", "name": "../up/checkout.svg", "width": 640, "height": 0})
    [answer] = sent
    path = tmp_path / "checkout.svg"  # a plain name: no folders
    assert answer["path"] == str(path.resolve())
    assert path.read_text(encoding="utf-8").startswith("<svg")
    assert 'width="640"' in path.read_text(encoding="utf-8")


def test_a_failure_comes_back_as_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plot = log_plot()
    sent = answers(plot, monkeypatch)
    ask(plot, {"type": "save-image", "name": "checkout.png"})  # no PNG sent
    ask(plot, {"type": "figure", "width": 50})  # too narrow: drawn at the least width
    assert sent[0] == {"type": "answer", "request": 7, "error": "no image data"}
    assert sent[1]["svg"].startswith("<svg")


def test_an_unknown_suffix_saves_a_png(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plot = log_plot()
    sent = answers(plot, monkeypatch)
    ask(plot, {"type": "save-image", "name": "notes.txt"}, [b"\x89PNG"])
    assert sent[0]["path"].endswith("notes.png")


@pytest.mark.parametrize("theme", ["light", "dark", "other"])
def test_the_theme_is_light_or_dark(monkeypatch, theme):
    plot = log_plot()
    svg = plot._figure({"width": 400, "height": 200, "theme": theme})
    assert svg == plot.to_svg(width=400, height=200, theme="dark" if theme == "dark" else "light")
