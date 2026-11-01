"""anytimeline without anywidget: pictures, pages, the selection, callbacks, links and copies
work and load no widget package; showing the widget says what to install."""

import subprocess
import sys
import textwrap

BLOCKED = ("anywidget", "ipywidgets", "traitlets", "comm")

SCRIPT = textwrap.dedent(
    """
    import importlib.abc
    import sys

    BLOCKED = {blocked!r}

    class Missing(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in BLOCKED:
                raise ModuleNotFoundError(f"No module named {{name!r}}", name=name)
            return None

    sys.meta_path.insert(0, Missing())

    import copy
    import pickle
    import tempfile
    from pathlib import Path

    from anytimeline import Timeline, save_html
    from anytimeline.synthetic import service_log

    plot = Timeline(title="Checkout").events(service_log(30), lane="service")
    other = Timeline().events(service_log(10), lane="service")
    folder = Path(tempfile.mkdtemp())
    assert plot.to_svg().startswith("<svg")
    plot.save_image(folder / "plot.svg")
    assert "<html" in plot.to_html()
    save_html(folder / "page.html", plot, other)
    plot.display = "html"
    bundle = plot._repr_mimebundle_()
    assert "text/html" in (bundle[0] if isinstance(bundle, tuple) else bundle)
    seen = []
    plot.on_select(seen.append)
    plot.on_select(seen.append)  # registered once
    plot.selection = {{"events": [1, 2]}}
    assert plot.selected("events") is not None
    plot.link(other)
    assert plot.linked == [other]
    assert copy.copy(plot).selection == {{"events": [1, 2]}}
    assert pickle.loads(pickle.dumps(plot)).layers == ["events"]
    try:
        plot.widget
    except ImportError as err:
        assert "pip install anywidget" in str(err), err
        assert 'plot.display = "html"' in str(err), err
    else:
        raise AssertionError("the widget was made without anywidget")
    loaded = [m for m in BLOCKED if m in sys.modules]
    assert not loaded, loaded
    print("ok")
    """
)


def test_pictures_pages_and_the_selection_work_without_anywidget():
    code = SCRIPT.format(blocked=set(BLOCKED))
    done = subprocess.run(
        [sys.executable, "-c", code], check=False, capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"


def test_a_callback_that_raises_does_not_stop_the_others(caplog):
    from anytimeline import Timeline
    from anytimeline.plot import _call_each

    seen = []

    def broken(selection):
        raise RuntimeError("broken callback")

    with caplog.at_level("ERROR", logger="anytimeline"):
        _call_each([broken, seen.append], {"events": [1]})
    assert seen == [{"events": [1]}]
    assert "broken callback" in caplog.text
    # and on_select removes what it registered
    plot = Timeline()
    plot.on_select(seen.append)
    plot.on_select(seen.append, remove=True)
    assert plot._select_handlers == []
