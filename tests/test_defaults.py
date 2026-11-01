"""Defaults per method (set_defaults, defaults, get_defaults, reset_defaults), and changing a
layer with plot.update and plot.arguments."""

import inspect

import pytest

import anytimeline
from anytimeline import Timeline
from anytimeline.data import NotFoundError
from anytimeline.synthetic import service_log, traces


@pytest.fixture(autouse=True)
def no_defaults():
    anytimeline.reset_defaults()
    yield
    anytimeline.reset_defaults()


def log():
    return service_log(40)


def test_defaults_fill_what_a_call_leaves_out():
    anytimeline.set_defaults(plot={"font_size": 16, "title": "Ops"}, events={"lane": "service"})
    plot = Timeline(title="Checkout").events(log())
    assert plot.font_size == 16
    assert plot.title == "Checkout"  # the call wins
    assert len(plot._spec["lanes"]["names"]) > 1  # by service: a lane each
    assert len(Timeline().events(log(), lane=None)._spec["lanes"]["names"]) == 1


def test_defaults_add_up_and_are_listed():
    anytimeline.set_defaults(events={"lane": "service"})
    anytimeline.set_defaults(events={"opacity": 0.5}, plot={"height": 300})
    assert anytimeline.get_defaults() == {
        "events": {"lane": "service", "opacity": 0.5},
        "plot": {"height": 300},
    }
    anytimeline.reset_defaults("events")
    assert anytimeline.get_defaults() == {"plot": {"height": 300}}
    with pytest.raises(ValueError, match="no method 'event'"):
        anytimeline.reset_defaults("event")


def test_defaults_are_checked_when_set():
    with pytest.raises(TypeError, match=r"Timeline.events\(\) takes no argument 'colour'"):
        anytimeline.set_defaults(plot={"height": 300}, events={"colour": "level"})
    assert anytimeline.get_defaults() == {}  # nothing of that call is kept
    with pytest.raises(ValueError, match="overlap must be one of"):
        anytimeline.set_defaults(events={"overlap": "spread"})
    with pytest.raises(ValueError, match="xscale must be one of"):
        anytimeline.set_defaults(plot={"xscale": "log"})
    for key in ("data", "name"):
        with pytest.raises(TypeError, match="cannot have a default"):
            anytimeline.set_defaults(spans={key: "x"})
    with pytest.raises(TypeError, match="dict of arguments"):
        anytimeline.set_defaults(values=["lane"])  # ty: ignore[invalid-argument-type]


def test_defaults_in_a_with_block_only():
    anytimeline.set_defaults(plot={"height": 300})

    def make():
        with anytimeline.defaults(plot={"font_size": 18}):
            made.append(Timeline())
            raise RuntimeError

    made = []
    with pytest.raises(RuntimeError):
        make()
    assert (made[0].font_size, made[0].height) == (18, 300)
    assert anytimeline.get_defaults() == {"plot": {"height": 300}}
    assert Timeline().font_size == 12


def test_signatures_keep_their_own_defaults():
    params = inspect.signature(Timeline.events).parameters
    assert params["overlap"].default == "dodge"
    assert inspect.signature(Timeline).parameters["font_size"].default == 12


def test_update_calls_the_layer_again_with_the_changes():
    plot = Timeline().events(log(), lane="service", color="level", name="calls")
    plot.events(service_log(5), name="jobs")
    assert plot.arguments("calls") == {"lane": "service", "color": "level"}
    plot.update("calls", opacity=0.4, color=None)  # None: the method's own default
    assert plot.arguments("calls") == {"lane": "service", "opacity": 0.4}
    assert plot.layers == ["calls", "jobs"]  # its place kept
    fewer = service_log(10)
    plot.update("calls", data=fewer)
    assert len(plot._tables["calls"]["time"]) == len(fewer["time"])
    assert plot.arguments("calls")["opacity"] == 0.4


def test_update_keeps_the_layer_when_the_change_fails():
    plot = Timeline().events(log(), lane="service")
    before = plot._spec
    with pytest.raises(TypeError):
        plot.update("events", colour="level")
    with pytest.raises(ValueError, match="overlap"):
        plot.update("events", overlap="spread")
    assert plot._spec == before
    assert plot.arguments("events") == {"lane": "service"}
    with pytest.raises(TypeError, match="keeps its name"):
        plot.update("events", name="other")
    with pytest.raises(NotFoundError, match="no layer 'evnts'"):
        plot.update("evnts", opacity=0.5)
    plot.remove("events")
    with pytest.raises(NotFoundError):
        plot.arguments("events")


def test_a_layer_remembers_its_defaults_and_its_own_method():
    anytimeline.set_defaults(spans={"color": "service"})
    plot = Timeline().spans(traces(2, seed=1).spans, name="trace")
    # spans calls intervals: the layer is remembered as a spans call
    assert plot._calls["trace"][0] == "spans"
    assert plot.arguments("trace") == {"color": "service"}
    anytimeline.reset_defaults()
    plot.update("trace", layout="flame")  # still coloured by service
    assert plot.arguments("trace") == {"color": "service", "layout": "flame"}


def test_a_lazy_table_is_not_read_again(tmp_path):
    pl = pytest.importorskip("polars")
    path = tmp_path / "log.parquet"
    pl.DataFrame(log()).write_parquet(path)
    plot = Timeline().events(pl.scan_parquet(path), lane="service")
    path.unlink()  # a query that ran again would fail now
    plot.update("events", opacity=0.5)
    assert plot.arguments("events") == {"lane": "service", "opacity": 0.5}


def test_copies_keep_the_calls():
    plot = Timeline().events(log(), lane="service")
    import copy
    import pickle

    for other in (copy.copy(plot), pickle.loads(pickle.dumps(plot))):
        other.update("events", opacity=0.3)
        assert other.arguments("events") == {"lane": "service", "opacity": 0.3}
    assert plot.arguments("events") == {"lane": "service"}
