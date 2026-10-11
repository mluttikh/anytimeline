import numpy as np
import pytest

from anytimeline import Timeline, story
from anytimeline.events import EventsRecord
from anytimeline.synthetic import incident


def test_story_preset():
    plot = story(incident(), "{time:%H:%M}\n{title}", color="kind", importance="importance")
    layer = plot._spec["layers"][0]
    assert layer["labels"] == "stems"
    assert layer["importance"] is not None
    assert plot._spec["lanes"]["show_names"] is False  # one story line: no column of names
    rec = plot._layers["events"]
    assert isinstance(rec, EventsRecord)
    assert rec.text is not None
    assert rec.text[0] == "14:00\nDeploy checkout 4.12"  # datetimes format in templates
    by_team = story(incident(), "title", lane="team")
    assert by_team._spec["lanes"]["show_names"] is True
    assert by_team._spec["lanes"]["names"] == ["payments", "monitoring", "support", "databases"]


def test_stems_need_text_and_a_known_layout():
    data = {"time": np.array([1.0, 2.0]), "title": ["a", "b"]}
    with pytest.raises(ValueError, match="text="):
        Timeline().events(data, labels="stems")
    with pytest.raises(ValueError, match="labels"):
        Timeline().events(data, text="title", labels="above")  # ty: ignore[invalid-argument-type]
    plot = Timeline().events(data, text="title", labels="stems")
    assert plot._spec["layers"][0]["labels"] == "stems"
    assert plot._spec["lanes"]["show_names"] is True


def test_incident_data():
    inc = incident()
    assert len(inc["time"]) == 20
    assert set(inc["kind"]) == {"deploy", "alert", "page", "action", "status"}
    assert (np.diff(inc["time"].astype(np.int64)) > 0).all()
