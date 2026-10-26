"""The scene spec Python sends is the one the browser declares (js/src/core/types.ts).

``tests/fixtures/scene-schema.json`` is the JSON Schema of ``SceneSpec``, generated from
types.ts (``npm run schema`` in js/; a JS test keeps it up to date). Every kind of plot is
built here and its spec checked against it: a field Python sends that the browser does not
declare, a missing one, or a wrong type fails.
"""

import json
from pathlib import Path

import jsonschema
import pytest
from jsonschema.exceptions import best_match, relevance
from kinds import every_kind

SCHEMA = json.loads(
    (Path(__file__).parent / "fixtures" / "scene-schema.json").read_text(encoding="utf-8")
)
VALIDATOR = jsonschema.Draft7Validator(SCHEMA)
PLOTS = every_kind()


def specific(errors: list[jsonschema.ValidationError]) -> jsonschema.ValidationError | None:
    """The most relevant error; for a layer that matches none of the layer types, the error
    of its own type's schema (the one whose ``type`` it has), not "matches none of them"."""
    if not errors:
        return None
    error = max(errors, key=relevance)
    if error.validator not in ("anyOf", "oneOf") or not error.context:
        return error
    by_branch: dict[int, list[jsonschema.ValidationError]] = {}
    for e in error.context:
        by_branch.setdefault(int(e.relative_schema_path[0]), []).append(e)
    own = [es for es in by_branch.values() if not any(list(e.path) == ["type"] for e in es)]
    return specific(own[0]) if len(own) == 1 else best_match([error])


def check(spec: dict) -> None:
    """The spec is valid; else the most specific error, with where it is."""
    error = specific(list(VALIDATOR.iter_errors(spec)))
    if error is not None:
        where = "/".join(str(p) for p in error.absolute_path)
        pytest.fail(f"spec does not match types.ts at {where or '(top)'}: {error.message[:300]}")


@pytest.mark.parametrize("name", list(PLOTS))
def test_every_kind_of_plot_sends_the_declared_spec(name):
    check(PLOTS[name]._spec)


def test_an_empty_plot_sends_the_declared_spec():
    from anytimeline import Timeline

    check(Timeline()._spec)


def test_the_check_finds_a_field_the_browser_does_not_declare():
    spec = json.loads(json.dumps(PLOTS["events"]._spec))
    spec["layers"][0]["colour"] = "red"
    with pytest.raises(pytest.fail.Exception, match="colour"):
        check(spec)
