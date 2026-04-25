from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse

from desktop_py.core.models import AccountConfig

GAME_FEEDBACK_BASE_URL = "https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback"
WECHAT_BACKEND_HOST = "mp.weixin.qq.com"


def extract_token_from_url(url: str) -> str:
    value = url.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    return (parse_qs(parsed.query).get("token") or [""])[0].strip()


def build_feedback_url_from_token(token: str) -> str:
    value = token.strip()
    if not value:
        return ""
    return (
        GAME_FEEDBACK_BASE_URL
        + "?"
        + urlencode(
            {
                "action": "plugin_redirect",
                "plugin_uin": "1010",
                "selected": "2",
                "token": value,
                "lang": "zh_CN",
            }
        )
    )


def canonical_feedback_url(url: str) -> str:
    value = url.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    host = (parsed.netloc or "").strip().lower()
    path = (parsed.path or "").strip().lower()
    token = extract_token_from_url(value)
    if not token:
        return ""
    if host and host != WECHAT_BACKEND_HOST:
        return ""
    if "/wxamp/" not in path and "pluginredirect/gamefeedback" not in value.lower():
        return ""
    return build_feedback_url_from_token(token)


def refresh_account_feedback_url(account: AccountConfig, page_url: str) -> bool:
    feedback_url = canonical_feedback_url(page_url)
    if not feedback_url or account.feedback_url == feedback_url:
        return False
    account.feedback_url = feedback_url
    return True


def _group_accounts(accounts: list[AccountConfig], state_path: str) -> list[AccountConfig]:
    value = state_path.strip()
    if not value:
        return []
    return [account for account in accounts if account.state_path == value]


def _preferred_group_feedback_url(
    accounts: list[AccountConfig],
    state_path: str,
    *,
    preferred_account: AccountConfig | None = None,
) -> str:
    group_accounts = _group_accounts(accounts, state_path)
    candidates: list[AccountConfig] = []
    if preferred_account is not None and preferred_account.state_path == state_path:
        candidates.append(preferred_account)
    candidates.extend(account for account in group_accounts if account.is_entry_account and account not in candidates)
    candidates.extend(account for account in group_accounts if account not in candidates)
    for account in candidates:
        feedback_url = canonical_feedback_url(account.feedback_url)
        if feedback_url:
            return feedback_url
    return ""


def sync_account_feedback_url(accounts: list[AccountConfig], account: AccountConfig) -> bool:
    state_path = account.state_path.strip()
    if not state_path:
        return False
    current_feedback_url = canonical_feedback_url(account.feedback_url)
    if current_feedback_url:
        if account.feedback_url == current_feedback_url:
            return False
        account.feedback_url = current_feedback_url
        return True
    shared_feedback_url = _preferred_group_feedback_url(accounts, state_path, preferred_account=account)
    if not shared_feedback_url:
        return False
    account.feedback_url = shared_feedback_url
    return True


def propagate_account_feedback_url(accounts: list[AccountConfig], account: AccountConfig) -> bool:
    state_path = account.state_path.strip()
    feedback_url = canonical_feedback_url(account.feedback_url)
    if not state_path or not feedback_url:
        return False
    changed = False
    for item in _group_accounts(accounts, state_path):
        if item.feedback_url == feedback_url:
            continue
        item.feedback_url = feedback_url
        changed = True
    return changed


def normalize_group_feedback_urls(accounts: list[AccountConfig]) -> bool:
    changed = False
    for account in accounts:
        if sync_account_feedback_url(accounts, account):
            changed = True
    return changed
