import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "worklogger"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from data.db import DB


class ResetAdminScriptTests(unittest.TestCase):
    def _temp_db_path(self) -> str:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_requires_env_password_when_prompt_is_disabled(self):
        path = self._temp_db_path()
        env = dict(os.environ)
        env.pop("WORKLOGGER_RESET_PASSWORD", None)

        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "admin" / "reset_admin.py"),
                "--db",
                path,
                "--no-prompt",
            ],
            cwd=str(PROJECT_ROOT),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("WORKLOGGER_RESET_PASSWORD", result.stderr)
        self.assertFalse(os.path.exists(path))

    def test_resets_admin_password_from_environment(self):
        path = self._temp_db_path()
        env = dict(os.environ)
        env["WORKLOGGER_RESET_PASSWORD"] = "secret123"

        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "admin" / "reset_admin.py"),
                "--db",
                path,
                "--username",
                "admin",
                "--no-prompt",
            ],
            cwd=str(PROJECT_ROOT),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        db = DB(path)
        self.addCleanup(db.conn.close)
        self.assertIsNotNone(db.verify_user("admin", "secret123"))
        self.assertIsNone(db.verify_user("admin", "admin"))


if __name__ == "__main__":
    unittest.main()

