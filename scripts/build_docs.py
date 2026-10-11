"""Build the user documentation (docs/user/ -> site/), or serve it while writing.

    uv run python scripts/build_docs.py          # build into site/, strict: warnings fail
    uv run python scripts/build_docs.py serve    # preview at http://localhost:8000

The example plots in the pages are live: ``Timeline._embed_html`` puts each plot's data in the
page, and the JavaScript bundle (``standalone.js``) draws it. Build the bundle first
(cd js && npm run build); this script copies it into the documentation.

A build fails on warnings, also on those Zensical's strict mode does not count: an example
that raises (markdown-exec) and a docstring the API reference cannot read (griffe).

The build runs in Python's UTF-8 mode (as ``python -X utf8``), it and every process it
starts: the pages and the code are UTF-8 (µ, ×, →), and on Windows Python otherwise reads
and writes text in the locale's encoding (cp1252), also in tools we don't control (the
API reference formats signatures through a subprocess).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "anytimeline" / "static"
ASSETS = ROOT / "docs" / "user" / "assets" / "anytimeline"


def copy_bundle() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    for name in ("standalone.js", "widget.css"):
        source = STATIC / name
        if not source.is_file():
            sys.exit(f"{source} is missing; build the JavaScript first: cd js && npm run build")
        shutil.copyfile(source, ASSETS / name)


class Warnings(logging.Handler):
    """Collects the warnings of the plugins that run examples and read docstrings."""

    SOURCES = ("markdown_exec", "griffe", "mkdocstrings", "mkdocs")

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.seen: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.split(".")[0] in self.SOURCES:
            self.seen.append(f"{record.name}: {record.getMessage()}")


def build() -> int:
    import zensical

    warnings = Warnings()
    logging.getLogger().addHandler(warnings)
    os.chdir(ROOT)
    try:
        zensical.build(str(ROOT / "zensical.toml"), {"clean": True, "strict": True})
    except RuntimeError as err:  # strict mode: a warning of Zensical itself
        print(err, file=sys.stderr)
        return 1
    for line in warnings.seen:
        print(f"warning: {line}", file=sys.stderr)
    return 1 if warnings.seen else 0


def main() -> None:
    if not sys.flags.utf8_mode:
        # again in UTF-8 mode; PYTHONUTF8 reaches the processes it starts too
        env = {**os.environ, "PYTHONUTF8": "1"}
        sys.exit(subprocess.run([sys.executable, *sys.argv], env=env, check=False).returncode)
    copy_bundle()
    if sys.argv[1:] == ["serve"]:
        sys.exit(subprocess.run(["zensical", "serve"], cwd=ROOT, check=False).returncode)
    sys.exit(build())


if __name__ == "__main__":
    main()
