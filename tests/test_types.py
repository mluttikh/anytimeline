"""The option types in ``anytimeline.types`` are the values the plot accepts: each value of
each type works, and a value outside it is refused with the options named."""

from collections.abc import Callable
from typing import Any, get_args

import numpy as np
import pytest

from anytimeline import Stem, Timeline, story, types
from anytimeline.synthetic import service_health, service_log, service_metrics, traces

LOG = service_log(10)
TRACE = traces(1, seed=1).spans
METRICS = service_metrics(5)
HEALTH = service_health(5)
STORY = {"time": np.array([1.0, 2.0]), "title": ["a", "b"]}

USES: dict[Any, Callable[[Any], Any]] = {
    types.Renderer: lambda v: Timeline(renderer=v),
    types.Tool: lambda v: Timeline(tool=v),
    types.XScale: lambda v: Timeline(xscale=v),
    types.SelectionMode: lambda v: Timeline(selection_mode=v),
    types.Display: lambda v: Timeline(display=v),
    types.Align: lambda v: Timeline(align=v).events(LOG, lane="service", group="level"),
    types.LaneSort: lambda v: Timeline(sort=v).events(LOG, lane="service"),
    types.EventOverlap: lambda v: Timeline().events(LOG, lane="service", overlap=v),
    types.BarOverlap: lambda v: Timeline().intervals(TRACE, lane="service", overlap=v),
    types.ValuesKind: lambda v: Timeline().values(METRICS, value="cpu", kind=v),
    types.ValuesScale: lambda v: Timeline().values(METRICS, value="cpu", scale=v),
    types.StemShape: lambda v: story(STORY, "title", stems=v),
    types.Symbol: lambda v: Timeline().events(LOG, lane="service", symbol=v),
}


def literals(kind: Any) -> list[Any]:
    """The values of a Literal type (of the Literal in a union with other types)."""
    args = get_args(kind)
    if all(isinstance(a, str) for a in args):
        return list(args)
    return [v for a in args for v in get_args(a) if isinstance(v, str)]


@pytest.mark.parametrize("kind", list(USES), ids=lambda k: str(k).split(".")[-1])
def test_every_option_is_accepted_and_no_other(kind):
    use = USES[kind]
    for value in literals(kind):
        use(value)
    with pytest.raises(ValueError, match="nope") as refused:
        use("nope")
    message = str(refused.value)
    assert all(repr(value) in message for value in literals(kind))


def test_the_types_named_in_all_are_the_module_s():
    assert sorted(types.__all__) == sorted(
        name for name in vars(types) if name[0].isupper() and name != "Literal"
    )


def test_the_other_options():
    for expand in [1, 3, "auto", "all"]:
        Timeline().spans(TRACE, expand=expand)
    for clim in [(0.0, 1.0), "robust"]:
        Timeline().events(LOG, lane="service", color="bytes", clim=clim)
    assert literals(types.Expand) == ["auto", "all"]
    assert literals(types.Clim) == ["robust"]
    assert Stem.of(True) == Stem()
    assert Timeline().states(HEALTH, lane="service", text=None).layers == ["states"]
