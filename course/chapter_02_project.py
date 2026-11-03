"""Chapter 2: Create a runnable Python project.

A production project needs one dependency definition, stable commands, configuration, and tests. The numbered lessons delegate to the same package used by scheduled jobs and the API.

Run from the repository root with:
    uv run python course/chapter_02_project.py --data-dir data

The shared lesson dispatcher provides the reusable application behavior.
"""

import argparse
import json
from pathlib import Path

from roadsafety.lessons import run_lesson


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--live",
        action="store_true",
        help="Opt into this lesson's live-source path; default is offline fixture work.",
    )
    args = parser.parse_args()
    result = run_lesson(2, data_dir=args.data_dir, live=args.live)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
