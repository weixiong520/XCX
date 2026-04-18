from __future__ import annotations

import re
from datetime import datetime


DATE_TIME_RE = re.compile(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:[日\sT]*\d{1,2}:\d{2}(?::\d{2})?)?")


def extract_labeled_datetime(text: str, label: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    pattern = re.compile(
        rf"{re.escape(label)}[：:\s]*({DATE_TIME_RE.pattern})"
    )
    matched = pattern.search(normalized)
    return matched.group(1) if matched else ""


def convert_timestamp(value: str) -> str:
    if re.fullmatch(r"\d{10}", value):
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    return value
