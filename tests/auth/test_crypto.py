import os
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from utils import crypto


class CryptoTests(unittest.TestCase):
    def tearDown(self):
        crypto.machine_key.cache_clear()

    def test_machine_key_uses_ephemeral_key_when_fallback_storage_fails(self):
        crypto.machine_key.cache_clear()
        with patch("utils.crypto._load_keyring_key", return_value=None), \
             patch("utils.crypto._load_file_key", return_value=None), \
             patch("utils.crypto._store_keyring_key", return_value=False), \
             patch("utils.crypto._store_file_key", side_effect=OSError("denied")):
            key = crypto.machine_key()
            cached_key = crypto.machine_key()

        self.assertEqual(len(key), 32)
        self.assertEqual(cached_key, key)


if __name__ == "__main__":
    unittest.main()
