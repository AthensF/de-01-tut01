"""Chapter 9: Make runs and quality observable.

A finished process is not proof of a correct refresh. Record acquisition, transformation, validation, and publication outcomes separately, with timestamps and evidence.

Run from the repository root with:
    uv run python course/chapter_09_quality.py --data-dir data

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
    result = run_lesson(9, data_dir=args.data_dir, live=args.live)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

