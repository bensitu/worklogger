from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "worklogger"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from config.constants import DEFAULT_ADMIN_USER, FORCE_PASSWORD_CHANGE_SETTING_KEY
from data.db import DB


RESET_PASSWORD_ENV = "WORKLOGGER_RESET_PASSWORD"


def _prompt_password(username: str) -> str:
    password = getpass.getpass(f"New password for '{username}': ")
    confirm = getpass.getpass("Confirm new password: ")
    if password != confirm:
        raise ValueError("Passwords do not match.")
    return password


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset a WorkLogger administrator password locally.",
    )
    parser.add_argument("--db", default="", help="Path to worklog.db")
    parser.add_argument("--username", default=DEFAULT_ADMIN_USER)
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help=f"Do not prompt; require {RESET_PASSWORD_ENV} to be set.",
    )
    args = parser.parse_args()
    password = os.environ.get(RESET_PASSWORD_ENV, "")
    if not password and not args.no_prompt:
        try:
            password = _prompt_password(args.username)
        except (EOFError, KeyboardInterrupt):
            print("Password reset cancelled.", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if not password:
        print(
            f"Set {RESET_PASSWORD_ENV} or run without --no-prompt.",
            file=sys.stderr,
        )
        return 2

    db = DB(args.db or None)
    try:
        user = db.get_user_by_username(args.username)
        if user is None:
            user_id = db.create_user(
                args.username,
                password,
                is_admin=True,
            )
        else:
            user_id = int(user["id"])
            if not db.reset_password(user_id, password):
                raise RuntimeError("Failed to reset password")
            db.set_admin(user_id, True)
        db.set_setting(FORCE_PASSWORD_CHANGE_SETTING_KEY, "1", user_id=user_id)
        print(
            f"Reset administrator '{args.username}'. "
            "Password change will be required at next login."
        )
        return 0
    finally:
        db.conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
