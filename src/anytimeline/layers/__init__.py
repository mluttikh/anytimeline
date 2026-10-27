"""The kinds of layer, a module each: ``build`` reads a layer's table into a record when the
layer is added, ``layout`` lays it out on the plot's time base and lanes (its spec and the
buffers that spec names), and ``common`` picks its rows for a click or a box.

* ``events``: a mark per event (``Timeline.events``).
* ``intervals``: a bar per row, packed, in a tree, with links (``intervals``, ``spans``).
* ``states``: changes as chained bars (``states``), laid out as intervals.
* ``values``: samples per lane (``values``).
"""
