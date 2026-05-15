import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.agent.tools import list_medications


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    medications = list_medications(
        user_id=args.user_id,
        active_only=not args.all,
    )
    if not medications:
        print("No medications found.")
        return

    for medication in medications:
        print(medication)


if __name__ == "__main__":
    main()
