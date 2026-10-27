"""Twins: Python's ports of the browser's time axis, level choice, dodging and stem layout
(``axis``, ``image``, ``stems``) give the browser's answers on the cases of
``tests/fixtures/twins.json``, which ``js/test/twins.test.ts`` writes and checks against the
browser's code (``UPDATE_TWINS=1 npm test``)."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

from anytimeline import axis, image, stems
from anytimeline.styling import SYMBOLS

ROOT = Path(__file__).resolve().parent.parent
TWINS = json.loads((ROOT / "tests" / "fixtures" / "twins.json").read_text(encoding="utf-8"))


def _num(v: object) -> float:
    return {"Infinity": math.inf, "-Infinity": -math.inf}.get(v, v)  # ty: ignore[invalid-return-type]


def test_the_constants_are_the_browsers() -> None:
    c = TWINS["constants"]
    for name in (
        "PAD_RIGHT", "PAD_BOTTOM", "MIN_LANE", "AUTO_LANE", "LABEL_BUDGET", "ROUTE_BUDGET",
        "GAP_PX", "BIN_PX", "BIN_FILL", "MERGE_PX", "MAX_ROWS", "MIN_STEP", "LEGEND_ITEMS",
    ):  # fmt: skip
        assert getattr(image, name) == c[name], name
    assert list(SYMBOLS) == c["SYMBOLS"]


def test_the_themes_are_the_stylesheets() -> None:
    css = (ROOT / "js" / "src" / "widget.css").read_text(encoding="utf-8")
    blocks = re.findall(r"\{([^{}]*--atl-bg[^{}]*)\}", css)
    found = [dict(re.findall(r"--atl-([a-z]+):\s*([^;]+);", b)) for b in blocks]
    for name, theme in image.THEMES.items():
        want = next(f for f in found if f["bg"] == theme.bg)
        for key in ("bg", "text", "muted", "grid", "band", "select", "accent", "border"):
            assert want[key] == getattr(theme, key), (name, key)
        r, g, b = image._rgb(theme.panel[0])
        assert want["panel"] == f"rgba({r}, {g}, {b}, {theme.panel[1]})", name


@pytest.mark.parametrize(
    "case",
    TWINS["axis"],
    ids=lambda c: f"{c['spec']['kind']}-{c['spec']['timezone']}-{c['right'] - c['left']:.3g}",
)
def test_axis(case: dict) -> None:
    ax = axis.TimeAxis(case["spec"])
    t = ax.ticks(case["left"], case["right"], case["width"])
    assert t.pinned == case["pinned"]
    assert [m.label for m in t.minor] == [m[1] for m in case["minor"]]
    assert [c.label for c in t.context] == [c[1] for c in case["context"]]
    # (JSON writes large whole numbers as integers)
    want = [float(m[0]) for m in case["minor"]]
    np.testing.assert_allclose([m.x for m in t.minor], want, rtol=1e-12, atol=1e-9)
    want = [float(c[0]) for c in case["context"]]
    np.testing.assert_allclose([c.x for c in t.context], want, rtol=1e-12, atol=1e-9)
    mid = (case["left"] + case["right"]) / 2
    assert [ax.format_full(case["left"]), ax.format_full(mid)] == case["full"]
    span = case["right"] - case["left"]
    assert [ax.format_span(span), ax.format_span(span / 7)] == case["span"]


def test_numbers() -> None:
    got = [[v, p, axis.fmt_number(v, p)] for v, p, _ in TWINS["numbers"]]
    assert got == TWINS["numbers"]


def test_durations() -> None:
    got = [[v, s, e, g, axis.format_duration(v, s, e, g)] for v, s, e, g, _ in TWINS["durations"]]
    assert got == TWINS["durations"]


def test_nice_steps() -> None:
    assert [[r, i, axis.nice_step(r, i)] for r, i, _ in TWINS["nice"]] == TWINS["nice"]


def test_level_choice() -> None:
    got = [
        [top, s, image.events_level(top, s), image.values_level(top, s), image.bars_level(top, s)]
        for top, s, *_ in TWINS["levels"]
    ]
    assert got == TWINS["levels"]


@pytest.mark.parametrize("case", TWINS["dodge"], ids=lambda c: f"{len(c['xs'])}-{c['laneH']}")
def test_dodge(case: dict) -> None:
    lane_h, size = case["laneH"], case["size"]
    rows = image.rows_for(lane_h, size, image.spacing(lane_h, size, math.inf))
    assert rows == case["rows"]
    dy = image.dodge(np.asarray(case["xs"]), size * 0.85, rows)
    assert dy.tolist() == case["dy"]
    assert image.spacing(lane_h, size, float(np.abs(dy).max())) == pytest.approx(
        case["step"], rel=1e-12
    )


@pytest.mark.parametrize(
    "case", TWINS["stems"], ids=lambda c: f"{len(c['items'])}-{c['space']['shape']}"
)
def test_stems(case: dict) -> None:
    items = [
        stems.StemItem(it["index"], it["x"], it["w"], it["importance"]) for it in case["items"]
    ]
    space = case["space"]
    placed = stems.place_stems(items, **space)
    want = case["placed"]
    assert [(p.index, p.level) for p in placed] == [(p["index"], p["level"]) for p in want]
    np.testing.assert_allclose(
        [(p.x0, p.cx) for p in placed], [(p["x0"], p["cx"]) for p in want], atol=1e-9
    )
    boxed = {p.index for p in placed}
    hidden = [(it.index, it.x) for it in items if it.index not in boxed]
    clusters = stems.cluster_hidden(hidden, 48, [it.x for it in items if it.index in boxed])
    assert [(c.indices, c.x0, c.x1) for c in clusters] == [
        (c["indices"], c["x0"], c["x1"]) for c in case["clusters"]
    ]


def test_wrapping() -> None:
    def measure(s: str) -> float:
        return len(s) * 6.5 + len(re.findall("[mwMW]", s)) * 3

    for text, width, lines, want in TWINS["wrap"]:
        w = math.inf if width is None else width
        assert stems.wrap_text(text, w, lines, measure) == want, (text, width, lines)
    for lane_h, box_h, start, levels, up, down in TWINS["stem_levels"]:
        assert stems.levels_for(lane_h, box_h, 7, start) == levels
        assert stems.level_offset(2, box_h, 7, start) == up
        assert stems.level_offset(-1, box_h, 7, start) == down
