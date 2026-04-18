import unittest

from desktop_dev import find_existing_app_pids


class DesktopDevTestCase(unittest.TestCase):
    def test_find_existing_app_pids_only_matches_desktop_main(self):
        processes = [
            {"ProcessId": 100, "CommandLine": r'python.exe desktop_main.py'},
            {"ProcessId": 101, "CommandLine": r'python.exe desktop_dev.py'},
            {"ProcessId": 102, "CommandLine": r'python.exe -m unittest py_tests.test_app -v'},
            {"ProcessId": 103, "CommandLine": r'python.exe C:\Users\Administrator\Desktop\M\desktop_main.py'},
        ]

        result = find_existing_app_pids(processes, current_pid=101)

        self.assertEqual(result, [100, 103])

    def test_find_existing_app_pids_skips_current_process(self):
        processes = [
            {"ProcessId": 200, "CommandLine": r'python.exe desktop_main.py'},
        ]

        result = find_existing_app_pids(processes, current_pid=200)

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
