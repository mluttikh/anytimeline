"""Run CI's Linux jobs here, before pushing: the same steps, in the same order, from this
checkout (.github/workflows/ci.yml).

    uv run python scripts/check.py            # python, browser and wheel
    uv run python scripts/check.py python     # some of them
    uv run python scripts/check.py --keep-going

``python`` runs on this checkout's Python (CI: 3.12 to 3.15, and Windows); ``browser`` needs
Chromium, Firefox and WebKit for Playwright (``cd js && npx playwright install chromium
firefox webkit``) and, here as on CI, compares screenshots on macOS only (in Chromium).
Each step's output shows as it runs; a summary of the steps and their times ends the run,
which fails when a step failed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "js"

Step = tuple[str, list[str], Path]
"""A step: its name, its command, and where it runs."""


def python_job() -> list[Step]:
    return [
        ("npm ci", ["npm", "ci"], JS),
        ("build", ["npm", "run", "build"], JS),
        ("uv sync", ["uv", "sync"], ROOT),
        ("ruff check", ["uv", "run", "ruff", "check", "."], ROOT),
        ("ruff format", ["uv", "run", "ruff", "format", "--check", "."], ROOT),
        ("ty", ["uv", "run", "ty", "check"], ROOT),
        ("pytest", ["uv", "run", "pytest"], ROOT),
    ]


def browser_job() -> list[Step]:
    return [
        ("npm ci", ["npm", "ci"], JS),
        ("typecheck", ["npm", "run", "typecheck"], JS),
        ("npm test", ["npm", "test"], JS),
        ("build", ["npm", "run", "build"], JS),
        ("uv sync", ["uv", "sync"], ROOT),
        ("scenes", ["uv", "run", "python", "scripts/make_scenes.py"], ROOT),
        ("docs (strict)", ["uv", "run", "python", "scripts/build_docs.py"], ROOT),
        ("browser tests", ["npx", "playwright", "test"], JS),
    ]


def wheel_job(clean: Path) -> list[Step]:
    venv = clean / "venv"
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return [
        ("uv build", ["uv", "build", "--out-dir", str(clean / "dist")], ROOT),
        ("clean environment", ["uv", "venv", "--python", "3.12", str(venv)], ROOT),
        # WHEEL, DIST: the files built (their names are known once built)
        ("install the wheel", ["uv", "pip", "install", "--python", str(venv), "WHEEL"], ROOT),
        ("smoke test", [str(python), "-I", "scripts/smoke.py"], ROOT),
        ("twine check", ["uvx", "twine", "check", "--strict", "DIST"], ROOT),
    ]


JOBS = ("python", "browser", "wheel")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("jobs", nargs="*", help=f"some of {', '.join(JOBS)} (default: all)")
    parser.add_argument("--keep-going", action="store_true", help="run the steps after a failure")
    args = parser.parse_args()
    jobs = args.jobs or list(JOBS)
    if unknown := [j for j in jobs if j not in JOBS]:
        parser.error(f"no job {unknown[0]!r}; the jobs: {', '.join(JOBS)}")
    results: list[tuple[str, bool, float]] = []
    with tempfile.TemporaryDirectory(prefix="anytimeline-check-") as tmp:
        clean = Path(tmp)
        steps = {"python": python_job, "browser": browser_job, "wheel": lambda: wheel_job(clean)}
        for job in jobs:
            for name, given, cwd in steps[job]():
                command = expand(given, clean)
                label = f"{job}: {name}"
                print(f"\n\033[1m── {label}\033[0m", flush=True)
                start = time.monotonic()
                env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"} if job == "wheel" else None
                ok = subprocess.run(resolve(command), check=False, cwd=cwd, env=env).returncode == 0
                results.append((label, ok, time.monotonic() - start))
                if not ok and not args.keep_going:
                    break
            if results and not results[-1][1] and not args.keep_going:
                break
    print("\n\033[1m── summary\033[0m")
    for label, ok, seconds in results:
        print(f"  {'ok  ' if ok else 'FAIL'}  {seconds:6.1f} s  {label}")
    failed = [label for label, ok, _ in results if not ok]
    print(f"\n{len(failed)} failed" if failed else "\nall passed")
    return 1 if failed else 0


def expand(command: list[str], clean: Path) -> list[str]:
    """The wheel job's placeholders: the built wheel, and every built distribution."""
    dist = sorted((clean / "dist").glob("*")) if (clean / "dist").exists() else []
    out: list[str] = []
    for part in command:
        if part == "WHEEL":
            out.extend(str(p) for p in dist if p.suffix == ".whl")
        elif part == "DIST":
            out.extend(str(p) for p in dist if p.suffix in (".whl", ".gz"))
        else:
            out.append(part)
    return out


def resolve(command: list[str]) -> list[str]:
    """The command with its program's path (on Windows npm and npx are .cmd files, which
    subprocess finds only by their full name)."""
    found = shutil.which(command[0])
    if found is None:
        sys.exit(f"{command[0]} is not installed (or not on PATH)")
    return [found, *command[1:]]


if __name__ == "__main__":
    sys.exit(main())
