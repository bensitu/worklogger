"""Upgrade a database into a new destination while retaining the original file."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from worklogger.infrastructure.database.upgrade import upgrade_database


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--template-file", type=Path)
    parser.add_argument("--template-user")
    parser.add_argument("--template-language", default="en_US")
    args = parser.parse_args(argv)
    try:
        report = upgrade_database(args.source, args.destination, template_file=args.template_file,
                                  template_user=args.template_user, template_language=args.template_language)
    except Exception as exc:
        print(f"Database upgrade failed ({type(exc).__name__}); the source and existing destination have been retained.", file=sys.stderr)
        return 1
    print(json.dumps(asdict(report)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
