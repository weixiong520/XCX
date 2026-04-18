from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class AccountConfig:
    name: str
    state_path: str
    is_entry_account: bool = True
    feedback_url: str = ""
    home_url: str = "https://mp.weixin.qq.com/"
    enabled: bool = True
    last_login_at: str = ""
    last_fetch_at: str = ""
    last_deadline: str = ""
    last_status: str = ""
    last_note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AppSettings:
    feishu_webhook: str = ""
    login_wait_seconds: int = 120
    headless_fetch: bool = True
    browser_profile_dir: str = ""
    current_main_account_name: str = ""
    auto_fetch_push_enabled: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FetchResult:
    account_name: str
    ok: bool
    actual_account_name: str = ""
    deadline_text: str = ""
    deadline_source: str = ""
    matched_path: str = ""
    page_url: str = ""
    note: str = ""
    fetched_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict:
        return asdict(self)
