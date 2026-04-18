import unittest

from desktop_py.core.parser import convert_timestamp, extract_labeled_datetime


class ParserTestCase(unittest.TestCase):
    def test_extract_labeled_datetime(self):
        text = "处理截止时间：2026-04-20 19:07:26 申诉截止时间：2026-04-21 10:19:34"
        self.assertEqual(extract_labeled_datetime(text, "处理截止时间"), "2026-04-20 19:07:26")

    def test_convert_timestamp(self):
        self.assertEqual(convert_timestamp("1776737974"), "2026-04-21 10:19:34")


if __name__ == "__main__":
    unittest.main()
