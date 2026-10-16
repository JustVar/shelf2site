"""Build the database schema on an empty Postgres database.

The app also does this on startup (app/schema.py); this script is for doing
it on its own, and for checking a database without changing it.

Run:
    python -m scripts.init_db            # build, then report anything missing
    python -m scripts.init_db --check    # report only; exit 1 if anything is missing
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schema import build_schema, missing_objects  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build or check the database schema.")
    parser.add_argument("--check", action="store_true", help="only report missing objects")
    args = parser.parse_args(argv)
    if not args.check:
        build_schema(log=print)
    missing = missing_objects()
    if missing:
        print("MISSING: " + ", ".join(missing))
        return 1
    print("schema complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
