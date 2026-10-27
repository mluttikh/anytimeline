import json
import re

import pytest
from kinds import every_kind

from anytimeline import Timeline
from anytimeline.page import HTML_WARN_BYTES
from anytimeline.synthetic import service_log

LOG = service_log(30)
N = f"{len(LOG['request']):,}"


def plot_of_log(**kwargs):
    return Timeline(**kwargs).events(LOG, lane="service", order="seq")


def payload(html: str) -> dict:
    data = re.search(r'<script type="application/json">(.*?)</script>', html, re.DOTALL)
    assert data is not None
    return json.loads(data.group(1))


def test_a_widget_by_default_with_text_that_says_how_to_show_it_as_html():
    plot = plot_of_log()
    assert plot.display == "widget"
    bundle = plot._repr_mimebundle_()
    data = bundle[0] if isinstance(bundle, tuple) else bundle
    assert "application/vnd.jupyter.widget-view+json" in data
    assert "text/html" not in data
    assert data["text/plain"].startswith(f"Timeline(events: {N} events)")
    assert 'display="html"' in data["text/plain"]


def test_display_html_shows_the_plot_as_an_output_that_runs_without_a_kernel():
    plot = plot_of_log(display="html", title="Log")
    data = plot._repr_mimebundle_()
    assert set(data) == {"text/plain", "text/html"}
    out = data["text/html"]
    assert out.startswith("<style>")
    assert '<div class="anytimeline-embed">' in out
    # where scripts do not run: what the plot is, and how to let it run
    note = re.search(r'<p class="anytimeline-note">(.*?)</p>', out)
    assert note is not None
    assert f"Timeline(events: {N} events)" in note.group(1)
    assert "Trust Notebook" in note.group(1)
    # the drawing code, run once per page per version of it
    version = re.search(r'r\["([0-9a-f]{16})"\]', out)
    assert version is not None
    assert payload(out)["title"] == "Log"
    with pytest.raises(ValueError, match="display must be one of"):
        plot.display = "png"


def test_the_data_in_a_fragment_cannot_end_its_script():
    log = service_log(5)
    log["request"][0] = "</script><script>alert(1)</script>"
    plot = Timeline(title="</script>").events(log, lane="service", tooltip=["request"])
    out = plot.to_html(full_html=False)
    data = out.split('<script type="application/json">', 1)[1].split("</script>", 1)[0]
    assert "<" not in data
    assert payload(out)["tooltips"]["events"]["values"][0].count(log["request"][0]) == 1


def test_to_html_is_the_page_save_html_writes(tmp_path):
    plot = plot_of_log(title="Log")
    page = plot.to_html()
    assert page.startswith("<!doctype html>")
    assert page == plot.save_html(tmp_path / "plot.html").read_text(encoding="utf-8")
    assert "<title>Other</title>" in plot.to_html(title="Other")
    with pytest.raises(ValueError, match="full_html"):
        plot.to_html(title="Other", full_html=False)
    fragment = plot.to_html(full_html=False)
    assert "<!doctype" not in fragment
    assert "<html" not in fragment
    assert "Trust Notebook" not in fragment


def test_fragments_share_one_version_of_the_script():
    a, b = plot_of_log(), plot_of_log(title="B")
    version = re.compile(r'r\["([0-9a-f]{16})"\]')
    assert version.findall(a.to_html(full_html=False)) == version.findall(
        b.to_html(full_html=False)
    )


def test_a_large_plot_shown_as_html_warns():
    plot = plot_of_log(display="html")
    plot._buffers["big"] = b"x" * (HTML_WARN_BYTES + 1)
    with pytest.warns(UserWarning, match="MB"):
        plot._repr_mimebundle_()


def test_marimo_shows_the_widget_or_a_frame():
    pytest.importorskip("marimo")
    plot = plot_of_log()
    assert type(plot._display_()).__name__ == "anywidget"
    plot.display = "html"
    plot.height = 300
    shown = plot._display_()
    assert "<iframe" in shown.text
    assert "300px" in shown.text


def test_repr_names_layers_and_sizes():
    assert repr(Timeline()) == "Timeline(no layers)"
    from anytimeline.synthetic import traces

    tr = traces(2, seed=1)
    plot = Timeline().spans(tr.spans).events(LOG, lane="service", name="log")
    assert repr(plot) == f"Timeline(spans: {len(tr.spans['span_id']):,} bars; log: {N} events)"


@pytest.mark.parametrize("kind", list(every_kind()))
def test_every_kind_makes_a_fragment(kind):
    plot = every_kind()[kind]
    if not plot._layers:
        pytest.skip("no layers")
    data = payload(plot.to_html(full_html=False))
    assert set(data["buffers"]) == set(plot._buffers)
