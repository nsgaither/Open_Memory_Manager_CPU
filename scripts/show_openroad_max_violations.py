#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def newest_run(runs_dir: Path) -> Path:
    runs = sorted(runs_dir.glob("RUN_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not runs:
        raise SystemExit(f"No RUN_* directories found under {runs_dir}")
    return runs[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show max slew and max cap violation metrics grouped by OpenROAD step."
    )
    parser.add_argument(
        "run",
        nargs="?",
        type=Path,
        help="LibreLane run directory. Defaults to the newest librelane/runs/RUN_* directory.",
    )
    args = parser.parse_args()

    run = args.run or newest_run(Path("librelane/runs"))
    print(f"# {run}")

    found = False
    for state_file in sorted(run.glob("*openroad*/state_out.json")):
        with state_file.open() as f:
            metrics = json.load(f).get("metrics", {})

        rows = [
            (key, value)
            for key, value in sorted(metrics.items())
            if "max_slew_violation" in key or "max_cap_violation" in key
        ]
        if not rows:
            continue

        found = True
        print(f"\n{state_file.parent.name}")
        for key, value in rows:
            print(f"  {key}: {value}")

    if not found:
        print("No max slew or max cap violation metrics found in OpenROAD state_out.json files.")


if __name__ == "__main__":
    main()
