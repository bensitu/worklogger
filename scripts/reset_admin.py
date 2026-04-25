from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "worklogger"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from config.constants import DEFAULT_ADMIN_USER, FORCE_PASSWORD_CHANGE_SETTING_KEY
from data.db import DB


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset a WorkLogger administrator password locally.",
    )
    parser.add_argument("--db", default="", help="Path to worklog.db")
    parser.add_argument("--username", default=DEFAULT_ADMIN_USER)
    parser.add_argument("--password", default=DEFAULT_ADMIN_USER)
    args = parser.parse_args()

    db = DB(args.db or None)
    try:
        user = db.get_user_by_username(args.username)
        if user is None:
            user_id = db.create_user(
                args.username,
                args.password,
                is_admin=True,
            )
        else:
            user_id = int(user["id"])
            if not db.reset_password(user_id, args.password):
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
