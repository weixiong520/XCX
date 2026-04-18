import unittest

from desktop_py.core.models import AccountConfig
from desktop_py.core.store import default_state_path


class DefaultStatePathTestCase(unittest.TestCase):
    def test_use_existing_state_path(self):
        accounts = [
            AccountConfig(name="A", state_path="storage/a.json"),
            AccountConfig(name="B", state_path=""),
        ]
        self.assertEqual(default_state_path(accounts), "storage/a.json")

    def test_fallback_to_shared_path(self):
        path = default_state_path([])
        self.assertTrue(path.endswith("storage\\shared_accounts.json") or path.endswith("storage/shared_accounts.json"))


if __name__ == "__main__":
    unittest.main()
