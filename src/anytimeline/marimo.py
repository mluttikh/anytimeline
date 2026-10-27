"""anytimeline in marimo notebooks: the selection as marimo state.

marimo is not a dependency of anytimeline: this module imports it when used.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anytimeline.plot import Timeline


def selection(plot: Timeline) -> Callable[[], dict[str, list[int]]]:
    """The plot's selection as marimo state: a getter of
    [`selection`][anytimeline.Timeline.selection].

    A cell that calls the getter runs again when the selection changes, in the plot or from
    Python, and on nothing else. A cell that reads ``mo.ui.anywidget(plot).value`` instead
    runs again on every change in the plot: a pan, a tool, the text size.

    ```python
    get_selection = anytimeline.marimo.selection(plot)
    ```

    ```python
    get_selection()  # this cell runs again when the selection changes
    plot.selected("events")
    ```

    Calling it again (its cell run again) replaces the plot's earlier state.

    Args:
        plot: The plot.

    Returns:
        The getter: layer name → sorted table rows.
    """
    import marimo as mo

    get, set_ = mo.state(dict(plot.selection))
    for old in plot._watchers.get("selection", []):
        if getattr(old, "_marimo", False):
            plot._unwatch("selection", old)

    def changed(change: dict[str, Any]) -> None:
        set_(dict(change["new"]))

    changed._marimo = True  # ty: ignore[unresolved-attribute]
    plot._watch("selection", changed)
    return get
