"""Undo and redo of the selection (``undo_selection``, ``redo_selection``; Ctrl/Cmd+Z and
Shift+Ctrl/Cmd+Z in the plot): every change, made in the plot or in Python, up to 50."""

from __future__ import annotations

from anytimeline import Timeline
from anytimeline.plot import UNDO_STEPS
from anytimeline.synthetic import service_log


def plot() -> Timeline:
    return Timeline().events(service_log(40, seed=1), lane="service")


def test_undo_takes_back_each_change_and_redo_makes_it_again() -> None:
    p = plot()
    heard: list[dict] = []
    p.on_select(heard.append)
    p.selection = {"events": [1]}
    p.selection = {"events": [1, 2]}
    p.selection = {}
    assert p.undo_selection()
    assert p.selection == {"events": [1, 2]}
    assert p.undo_selection()
    assert p.selection == {"events": [1]}
    assert p.redo_selection()
    assert p.selection == {"events": [1, 2]}
    assert heard == [{"events": [1, 2]}, {"events": [1]}, {"events": [1, 2]}]  # undo, undo, redo
    assert p.undo_selection()
    assert p.undo_selection()
    assert p.selection == {}
    assert not p.undo_selection()  # nothing before the first
    assert p.redo_selection()
    assert p.redo_selection()
    assert p.redo_selection()
    assert not p.redo_selection()
    assert p.selection == {}


def test_a_new_change_drops_what_could_be_made_again() -> None:
    p = plot()
    p.selection = {"events": [1]}
    p.undo_selection()
    p.selection = {"events": [5]}
    assert not p.redo_selection()


def test_changes_made_in_the_plot_undo_with_its_keys() -> None:
    p = plot()
    w = p.widget
    p._on_pick({"new": {"kind": "click", "layer": "events", "index": 0, "mode": "replace"}})
    first = p.selection
    assert first
    p._on_pick({"new": {"kind": "clear"}})
    assert p.selection == {}
    w._on_msg(w, {"type": "undo"}, [])
    assert p.selection == first
    w._on_msg(w, {"type": "redo"}, [])
    assert p.selection == {}


def test_at_most_fifty_steps() -> None:
    p = plot()
    for i in range(UNDO_STEPS + 10):
        p.selection = {"events": [i % 30, 30 + i % 7]}
    n = 0
    while p.undo_selection():
        n += 1
    assert n == UNDO_STEPS


def test_a_layer_removed_leaves_the_history() -> None:
    p = plot().events(service_log(10, seed=2), lane="service", name="more")
    p.selection = {"more": [1]}
    p.selection = {"events": [2]}
    p.remove("more")
    assert p.selection == {"events": [2]}
    assert p.undo_selection()
    assert p.selection == {}  # {"more": [1]} without the layer: nothing
