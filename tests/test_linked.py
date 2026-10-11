import json
import re

import pytest

from anytimeline import Timeline, save_html


def plot(t0: float = 0.0) -> Timeline:
    return Timeline().events({"time": [t0 + 1.0, t0 + 2.0], "lane": ["a", "b"]}, lane="lane")


def test_link_merges_groups_and_unlink_leaves():
    a, b, c, d = plot(), plot(), plot(), plot()
    a.link(b)
    c.link(d, align="start")
    b.link(c)  # joins the two groups
    group = a._link["group"]
    assert all(p._link["group"] == group for p in (a, b, c, d))
    assert {id(p) for p in a.linked} == {id(b), id(c), id(d)}
    assert all(p._link["align"] == "time" for p in (a, b, c, d))
    c.unlink()
    assert c._link == {}
    assert c.linked == []
    assert {id(p) for p in a.linked} == {id(b), id(d)}
    with pytest.raises(ValueError, match="align"):
        a.link(b, align="end")  # ty: ignore[invalid-argument-type]


def payloads(page: str) -> list[dict]:
    found = re.findall(r'<script type="application/json">(.*?)</script>', page, re.DOTALL)
    return [json.loads(f) for f in found]


def test_save_html_of_several_plots(tmp_path):
    a, b = plot(), plot(10.0)
    a.link(b, align="start")
    page = save_html(tmp_path / "two.html", a, [b], title="Two").read_text(encoding="utf-8")
    data = payloads(page)
    assert len(data) == 2
    assert data[0]["link"] == data[1]["link"] == {"group": a._link["group"], "align": "start"}
    assert 'data-fill="window"' not in page  # several plots: one above the other
    assert "<title>Two</title>" in page
    with pytest.raises(ValueError, match="no plots"):
        save_html(tmp_path / "none.html")
