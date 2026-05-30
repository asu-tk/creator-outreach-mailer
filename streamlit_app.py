from __future__ import annotations

import os
import re
import secrets
import socket
import smtplib
import sqlite3
import time
import json
import base64
import hashlib
import html
import math
from io import BytesIO
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from string import Template
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

try:
    from streamlit_sortables import sort_items
except Exception:
    sort_items = None

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "mailer.sqlite3"
APP_TIMEZONE = ZoneInfo("Asia/Tokyo")
CONTACT_STATUS_OPTIONS = ["未確認", "メール確認済み", "送信対象", "返信あり", "見込みあり", "除外"]
SENDABLE_CONTACT_STATUSES = {"未確認", "メール確認済み", "送信対象"}
GOOGLE_APP_SCOPES = [
    "openid",
    "email",
    "profile",
]
OUTSOURCE_SHEET_NAME = "外注用候補"
OUTSOURCE_DISCARD_COLUMN = "候補から削除"
OUTSOURCE_SHEET_COLUMNS = [
    "チャンネル名",
    "YouTube URL",
    "メールアドレス",
    OUTSOURCE_DISCARD_COLUMN,
    "メモ",
    "状態",
    "候補ID（編集しない）",
    "チャンネルID（編集しない）",
    "検索キーワード",
    "作成日時",
]
GOOGLE_SHEET_WRITE_DISABLED_MESSAGE = (
    "外注用GoogleシートはURL登録方式で運用しています。"
)
OUTSOURCE_MIN_UNIT_PRICE_YEN = 10
OUTSOURCE_MAX_UNIT_PRICE_YEN = 300
OUTSOURCE_DEFAULT_UNIT_PRICE_YEN = 50
AI_SCENARIO_EXPECTED_SECONDS = 75
AI_SCENARIO_STALE_SECONDS = 90
AI_OPENAI_TIMEOUT_SECONDS = 75
AI_IMAGE_MAX_BYTES = 8 * 1024 * 1024
STREAMLIT_SEND_QUEUE_BATCH_SIZE = 1
STREAMLIT_SEND_QUEUE_MIN_INTERVAL_SECONDS = 25
STREAMLIT_SEND_QUEUE_STALE_SENDING_SECONDS = 10 * 60
UNSUBSCRIBE_SCOPE_GLOBAL = "global"
UNSUBSCRIBE_SCOPE_SCENARIO = "scenario"
UNSUBSCRIBE_SCOPE_CAMPAIGN = "campaign"
UNSUBSCRIBE_REASON_GLOBAL = "配信停止:global"
UNSUBSCRIBE_REASON_PREFIX = "配信停止:"

YOUTUBE_VIDEO_CATEGORIES = {
    "エンターテイメント": "24",
    "ゲーム": "20",
    "コメディ": "23",
    "スポーツ": "17",
    "ニュースと政治": "25",
    "ハウツーとスタイル": "26",
    "ブログ": "22",
    "ペットと動物": "15",
    "映画とアニメ": "1",
    "音楽": "10",
    "科学と技術": "28",
    "教育": "27",
    "自動車と乗り物": "2",
    "非営利団体と社会活動": "29",
    "旅行とイベント": "19",
}

DEFAULT_CAMPAIGN_NAME = "初回案内"
DEFAULT_CAMPAIGN_SUBJECT = "${channel}へのご連絡"
DEFAULT_CAMPAIGN_BODY = """突然のご連絡失礼いたします。

${channel}を拝見し、ご連絡いたしました。

もしご興味がありましたら、一度お話しできれば幸いです。

不要な場合は、お手数ですが「配信停止希望」とご返信ください。"""

DEFAULT_CAMPAIGN_TEMPLATES = [
    (
        "初回案内",
        "${channel}へのご連絡",
        """突然のご連絡失礼いたします。

${channel}を拝見し、ご連絡いたしました。

貴チャンネルの運営に関して、こちらでお役に立てそうな点があると感じています。
もしご興味がありましたら、一度だけ概要をお送りできれば幸いです。

不要な場合は、お手数ですが「配信停止希望」とご返信ください。""",
    ),
    (
        "2通目 課題提起",
        "${channel}の運営で気になった点について",
        """先日ご連絡しました件で、補足のご連絡です。

${channel}を拝見して、今後さらに伸ばせそうな余地がある一方で、日々の運営の中では後回しになりやすい作業も多いのではないかと感じました。

弊社では、そのような作業負担を減らしながら、運営の成果につながる部分を支援しています。
もし少しでもご関心がありましたら、簡単な資料をお送りします。

不要な場合は、お手数ですが「配信停止希望」とご返信ください。""",
    ),
    (
        "3通目 価値説明",
        "${channel}に合いそうな活用イメージ",
        """何度も失礼いたします。

${channel}のように継続して発信されている場合、すでにあるコンテンツや取り組みを少し整えるだけで、新しい反応につながることがあります。

弊社サービスでは、そうした改善や運用の手間を減らすことを目的にしています。
大きな作業を増やすのではなく、今ある運営の延長で使える形を重視しています。

必要でしたら、貴チャンネルに合わせた簡単な活用案を無料で作成します。

不要な場合は、お手数ですが「配信停止希望」とご返信ください。""",
    ),
    (
        "4通目 軽い提案",
        "一度だけ無料で確認できます",
        """ご確認ありがとうございます。

もし判断材料が必要でしたら、一度だけ無料で簡単な確認・提案を作成できます。
その内容を見て、必要なければそのまま見送っていただいて問題ありません。

無理な営業ではなく、まず相性があるかだけ確認できればと思っています。

ご希望でしたら「確認希望」とだけご返信ください。

不要な場合は、お手数ですが「配信停止希望」とご返信ください。""",
    ),
    (
        "5通目 最終確認",
        "最後のご連絡です",
        """何度もご連絡失礼いたしました。

本件については、今回で最後のご連絡にいたします。
もし今後、運営改善や作業効率化について検討されるタイミングがありましたら、その際に思い出していただけますと幸いです。

ご興味がありましたら、このメールにそのままご返信ください。

不要な場合は、お手数ですが「配信停止希望」とご返信ください。""",
    ),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_utc_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def format_jst_datetime(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        jst_time = parsed.astimezone(APP_TIMEZONE)
        return jst_time.strftime("%Y年%m月%d日 %H:%M:%S（日本時間）")
    except ValueError:
        return value


def format_jst_datetime_compact(value: str) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(APP_TIMEZONE).strftime("%Y-%m-%d %H:%M（日本時間）")
    except ValueError:
        return value


def today_key() -> str:
    return datetime.now(APP_TIMEZONE).strftime("%Y-%m-%d")


def campaign_key(campaign_name: str) -> str:
    normalized = campaign_name.strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def auth_is_configured() -> bool:
    try:
        auth_config = st.secrets.get("auth", {})
        google_config = auth_config.get("google", {})
        return bool(
            get_google_redirect_uri()
            and auth_config.get("cookie_secret")
            and google_config.get("client_id")
            and google_config.get("client_secret")
        )
    except Exception:
        return False


def get_google_config() -> dict:
    try:
        auth_config = st.secrets.get("auth", {})
        google_config = auth_config.get("google", {})
        return {
            "client_id": google_config.get("client_id") or auth_config.get("client_id", ""),
            "client_secret": google_config.get("client_secret") or auth_config.get("client_secret", ""),
            "redirect_uri": get_google_redirect_uri(),
        }
    except Exception:
        return {"client_id": "", "client_secret": "", "redirect_uri": ""}


def get_google_redirect_uri() -> str:
    try:
        redirect_uri = str(st.secrets.get("auth", {}).get("redirect_uri", ""))
    except Exception:
        redirect_uri = ""
    if redirect_uri.endswith("/oauth2callback"):
        return redirect_uri.removesuffix("oauth2callback")
    return redirect_uri


def build_google_login_url() -> str:
    config = get_google_config()
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": " ".join(GOOGLE_APP_SCOPES),
        "prompt": "select_account consent",
        "include_granted_scopes": "true",
        "access_type": "online",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


def post_form(url: str, payload: dict[str, str]) -> dict:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def google_access_token() -> str:
    manual_user = st.session_state.get("google_user") or {}
    token = str(manual_user.get("access_token") or "")
    expires_at = float(manual_user.get("expires_at") or 0)
    if token and expires_at and time.time() < expires_at - 60:
        return token
    return ""


def google_service_account_info() -> dict:
    info: dict = {}
    try:
        section = st.secrets.get("google_service_account", {})
        if section:
            info = dict(section)
    except Exception:
        info = {}
    if not info:
        raw_json = ""
        try:
            raw_json = str(st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", ""))
        except Exception:
            raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if raw_json.strip():
            try:
                info = json.loads(raw_json)
            except json.JSONDecodeError:
                info = {}
    private_key = str(info.get("private_key") or "")
    if "\\n" in private_key:
        info["private_key"] = private_key.replace("\\n", "\n")
    return info


def google_service_account_email() -> str:
    return str(google_service_account_info().get("client_email") or "")


def google_service_account_configured() -> bool:
    info = google_service_account_info()
    return bool(info.get("client_email") and info.get("private_key") and info.get("token_uri"))


def google_service_account_token(scopes: list[str]) -> str:
    info = google_service_account_info()
    if not google_service_account_configured():
        raise ValueError("Googleシートへ書き込むには、Streamlit Secretsにgoogle_service_accountを設定してください。")
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
    except Exception as exc:
        raise ValueError("Googleシート連携に必要なgoogle-authがインストールされていません。") from exc
    credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    credentials.refresh(Request())
    return str(credentials.token or "")


def google_sheet_write_ready() -> tuple[bool, str]:
    if not google_service_account_configured():
        return False, "Googleシートへ自動反映するには、サービスアカウント設定が必要です。"
    try:
        from google.oauth2 import service_account  # noqa: F401
        from google.auth.transport.requests import Request  # noqa: F401
    except Exception:
        return False, "Googleシート連携に必要なgoogle-authがインストールされていません。"
    return True, ""


def google_api_request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            message = parsed.get("error", {}).get("message") or detail
        except Exception:
            message = detail or str(exc)
        raise ValueError(f"Google APIで処理できませんでした: {message}") from exc


def parse_bool(value: str | bool, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def read_secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return os.getenv(name, default)


def get_nested_secret(section: str, name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(section, {}).get(name, default))
    except Exception:
        return os.getenv(f"{section.upper()}_{name.upper()}", default)


def supabase_config() -> dict[str, str]:
    return {
        "url": get_nested_secret("supabase", "url") or read_secret("SUPABASE_URL"),
        "service_role_key": get_nested_secret("supabase", "service_role_key") or read_secret("SUPABASE_SERVICE_ROLE_KEY"),
    }


def supabase_configured() -> bool:
    config = supabase_config()
    return bool(config["url"] and config["service_role_key"])


def supabase_request(method: str, path: str, payload: dict | None = None, prefer: str = "") -> list[dict] | dict:
    config = supabase_config()
    base_url = config["url"].rstrip("/")
    url = f"{base_url}/rest/v1/{path.lstrip('/')}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "apikey": config["service_role_key"],
        "Authorization": f"Bearer {config['service_role_key']}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else []


def stripe_secret_key() -> str:
    return read_secret("STRIPE_SECRET_KEY") or get_nested_secret("billing", "stripe_secret_key")


def stripe_configured() -> bool:
    return bool(stripe_secret_key())


def stripe_request(path: str, params: dict[str, str] | None = None) -> dict:
    query = urllib.parse.urlencode(params or {})
    url = f"https://api.stripe.com/v1/{path.lstrip('/')}"
    if query:
        url += f"?{query}"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {stripe_secret_key()}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def handle_google_callback() -> None:
    code = st.query_params.get("code")
    if not code:
        return
    config = get_google_config()
    try:
        token_data = post_form(
            "https://oauth2.googleapis.com/token",
            {
                "code": code,
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "redirect_uri": config["redirect_uri"],
                "grant_type": "authorization_code",
            },
        )
        id_token = token_data.get("id_token", "")
        user_info = get_json("https://oauth2.googleapis.com/tokeninfo?id_token=" + urllib.parse.quote(id_token))
        st.session_state["google_user"] = {
            "email": user_info.get("email", ""),
            "sub": user_info.get("sub", ""),
            "name": user_info.get("name", ""),
            "access_token": token_data.get("access_token", ""),
            "scope": token_data.get("scope", ""),
            "expires_at": time.time() + int(token_data.get("expires_in", 0) or 0),
        }
        st.query_params.clear()
        st.rerun()
    except Exception as exc:
        st.error(f"Googleログインの処理に失敗しました: {exc}")


def auth_config_status() -> list[str]:
    checks = []
    try:
        auth_config = st.secrets.get("auth", {})
        for key in ["redirect_uri", "cookie_secret", "client_id", "client_secret", "server_metadata_url"]:
            value = auth_config.get(key) if key in ["redirect_uri", "cookie_secret"] else auth_config.get("google", {}).get(key)
            checks.append(f"{key}: {'設定あり' if value else '未設定'}")
        redirect_uri = str(auth_config.get("redirect_uri", ""))
        active_redirect_uri = get_google_redirect_uri()
        if redirect_uri.endswith("/oauth2callback"):
            checks.append("redirect_uri: 古い形式ですが、アプリ側では末尾を外して使います")
        checks.append(f"Google Cloudに登録するリダイレクトURL: {active_redirect_uri or '未設定'}")
    except Exception as exc:
        checks.append(f"Secrets読取エラー: {exc}")
    return checks


def current_user_id() -> str:
    manual_user = st.session_state.get("google_user")
    if manual_user:
        return str(manual_user.get("email") or manual_user.get("sub") or "unknown-user")
    try:
        if auth_is_configured() and st.user.is_logged_in:
            return str(st.user.get("email") or st.user.get("sub") or "unknown-user")
    except Exception:
        pass
    return "local-user"


def current_user_profile() -> dict[str, str]:
    manual_user = st.session_state.get("google_user")
    if manual_user:
        return {
            "email": str(manual_user.get("email") or ""),
            "sub": str(manual_user.get("sub") or ""),
            "name": str(manual_user.get("name") or ""),
        }
    try:
        if auth_is_configured() and st.user.is_logged_in:
            return {
                "email": str(st.user.get("email") or ""),
                "sub": str(st.user.get("sub") or ""),
                "name": str(st.user.get("name") or ""),
            }
    except Exception:
        pass
    return {"email": current_user_id(), "sub": "", "name": ""}


def ensure_supabase_user() -> None:
    if not supabase_configured() or current_user_id() == "local-user":
        return
    profile = current_user_profile()
    email = profile["email"].strip().lower()
    if not email:
        return
    try:
        supabase_request(
            "POST",
            "app_users?on_conflict=email",
            {
                "email": email,
                "google_sub": profile["sub"],
                "name": profile["name"],
                "updated_at": now_iso(),
            },
            prefer="resolution=merge-duplicates",
        )
    except Exception as exc:
        st.warning(f"Supabaseのユーザー登録に失敗しました: {exc}")


def admin_emails() -> set[str]:
    raw = read_secret("ADMIN_EMAILS")
    if not raw:
        raw = get_nested_secret("billing", "admin_emails") or get_nested_secret("supabase", "ADMIN_EMAILS")
    return {email.strip().lower() for email in raw.split(",") if email.strip()}


def subscription_required() -> bool:
    raw = read_secret("SUBSCRIPTION_REQUIRED")
    if not raw:
        raw = get_nested_secret("billing", "subscription_required") or get_nested_secret("supabase", "SUBSCRIPTION_REQUIRED")
    return parse_bool(raw, False)


def get_subscription_status(email: str) -> dict:
    query_email = urllib.parse.quote(email.lower(), safe="")
    result = supabase_request(
        "GET",
        f"subscriptions?user_email=eq.{query_email}&select=status,plan_name,current_period_end",
    )
    return result[0] if isinstance(result, list) and result else {}


def subscription_active(subscription: dict) -> bool:
    status = str(subscription.get("status", "")).lower()
    if status in {"active", "trialing"}:
        period_end = str(subscription.get("current_period_end") or "")
        if not period_end:
            return True
        try:
            normalized = period_end.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized) > datetime.now(timezone.utc)
        except ValueError:
            return True
    return False


def find_stripe_subscription_by_email(email: str) -> dict:
    if not stripe_configured() or not email:
        return {}
    customers = stripe_request("customers/search", {"query": f"email:'{email}'", "limit": "5"})
    for customer in customers.get("data", []):
        customer_id = customer.get("id", "")
        if not customer_id:
            continue
        subscriptions = stripe_request(
            "subscriptions",
            {"customer": customer_id, "status": "all", "limit": "10"},
        )
        for subscription in subscriptions.get("data", []):
            status = str(subscription.get("status", "")).lower()
            if status not in {"active", "trialing"}:
                continue
            period_end = subscription.get("current_period_end")
            period_end_iso = ""
            if period_end:
                period_end_iso = datetime.fromtimestamp(int(period_end), timezone.utc).isoformat()
            return {
                "stripe_customer_id": customer_id,
                "stripe_subscription_id": subscription.get("id", ""),
                "plan_name": "Creator Outreach Mailer 月額プラン",
                "status": status,
                "current_period_end": period_end_iso,
            }
    return {}


def sync_subscription_from_stripe(email: str) -> bool:
    stripe_subscription = find_stripe_subscription_by_email(email)
    if not stripe_subscription:
        return False
    supabase_request(
        "POST",
        "subscriptions?on_conflict=user_email",
        {
            "user_email": email,
            "stripe_customer_id": stripe_subscription["stripe_customer_id"],
            "stripe_subscription_id": stripe_subscription["stripe_subscription_id"],
            "plan_name": stripe_subscription["plan_name"],
            "status": stripe_subscription["status"],
            "current_period_end": stripe_subscription["current_period_end"] or None,
            "updated_at": now_iso(),
        },
        prefer="resolution=merge-duplicates",
    )
    return True


def require_active_subscription() -> None:
    ensure_supabase_user()
    if not subscription_required():
        return
    if not supabase_configured():
        st.error("課金チェック用のSupabase設定が未設定です。")
        st.stop()
    email = current_user_profile()["email"].strip().lower()
    if email in admin_emails():
        st.caption("管理者アカウントとして利用中です。")
        return
    subscription = get_subscription_status(email)
    if not subscription_active(subscription) and stripe_configured():
        try:
            if sync_subscription_from_stripe(email):
                subscription = get_subscription_status(email)
        except Exception as exc:
            if email in admin_emails():
                st.warning(f"Stripeの課金状態確認に失敗しました: {exc}")
    if subscription_active(subscription):
        return
    st.title("Creator Outreach Mailer")
    st.warning("このアプリを使うには有料プランへの登録が必要です。")
    checkout_url = read_secret("STRIPE_CHECKOUT_URL") or get_nested_secret("billing", "stripe_checkout_url")
    if checkout_url:
        st.link_button("有料プランに登録する", checkout_url)
        st.caption("決済時のメールアドレスは、Googleログインと同じメールアドレスを使ってください。決済後、この画面に戻ると課金状態を自動確認します。")
        if stripe_configured() and st.button("決済状態を確認する"):
            try:
                if sync_subscription_from_stripe(email):
                    st.success("決済状態を確認しました。アプリを開き直します。")
                    st.rerun()
                else:
                    st.info("まだ有料プランの登録を確認できませんでした。決済が完了している場合は、少し時間を置いてからもう一度お試しください。")
            except Exception as exc:
                if email in admin_emails():
                    st.error(f"決済状態の確認に失敗しました: {exc}")
                else:
                    st.info("現在、決済状態を確認できませんでした。少し時間を置いてからもう一度お試しください。")
    else:
        st.info("現在、決済ページを準備中です。管理者にお問い合わせください。")
    st.stop()


def require_login() -> bool:
    handle_google_callback()
    if not auth_is_configured():
        st.warning("ログイン設定が未設定です。開発モードとして local-user のデータを表示しています。")
        return True
    manual_user = st.session_state.get("google_user")
    if manual_user:
        return True
    if st.user.is_logged_in:
        return True
    st.title("Creator Outreach Mailer")
    st.write("このアプリを使うにはGoogleログインが必要です。")
    st.link_button("Googleでログイン", build_google_login_url())
    st.stop()


def render_login_status_bar() -> None:
    if not auth_is_configured() or current_user_id() == "local-user":
        return
    profile = current_user_profile()
    email = profile.get("email", "").strip() or current_user_id()
    email_col, logout_col, spacer_col = st.columns([2.1, 0.8, 5.0])
    email_col.caption(f"ログイン中: {email}")
    if "google_user" in st.session_state:
        if logout_col.button("ログアウト", key="logout_manual_user", width="stretch"):
            st.session_state.pop("google_user", None)
            st.rerun()
        return
    try:
        if st.user.is_logged_in and logout_col.button("ログアウト", key="logout_streamlit_user", width="stretch"):
            st.logout()
    except Exception:
        spacer_col.empty()


def inject_mail_preview_styles() -> None:
    st.markdown(
        """
        <style>
        .mail-readonly-block {
            margin-top: 0.5rem;
        }
        .mail-readonly-label {
            color: #334155;
            font-size: 0.9rem;
            font-weight: 600;
            margin: 0 0 0.35rem;
        }
        .mail-readonly-body {
            width: 100%;
            box-sizing: border-box;
            border: 1px solid #CBD5E1;
            border-radius: 8px;
            background: #FFFFFF;
            color: #0F172A;
            line-height: 1.75;
            font-size: 0.96rem;
            padding: 16px 18px;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_readonly_mail_body(label: str, text: str, min_height: int = 380) -> None:
    safe_label = html.escape(str(label or "本文"))
    safe_text = html.escape(str(text or "").strip()).replace("\n", "<br>") or "-"
    st.markdown(
        f"""
        <div class="mail-readonly-block">
            <div class="mail-readonly-label">{safe_label}</div>
            <div class="mail-readonly-body" style="min-height: {int(min_height)}px;">{safe_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def inject_loading_indicator() -> None:
    st.iframe(
        """
        <script>
        (() => {
            const win = window.parent;
            const doc = win.document;
            if (win.__creatorOutreachLoadingIndicatorInstalled) {
                return;
            }
            win.__creatorOutreachLoadingIndicatorInstalled = true;

            const style = doc.createElement("style");
            style.id = "creator-outreach-loading-style";
            style.textContent = `
                @keyframes creatorOutreachLoadingSpin {
                    to { transform: rotate(360deg); }
                }
                #creator-outreach-loading-indicator {
                    display: none;
                    position: fixed;
                    inset: 0;
                    z-index: 2147483000;
                    pointer-events: none;
                    align-items: center;
                    justify-content: center;
                    background: rgba(248, 250, 252, 0.30);
                }
                body.creator-outreach-is-loading #creator-outreach-loading-indicator {
                    display: flex;
                }
                .creator-outreach-loading-card {
                    display: inline-flex;
                    align-items: center;
                    gap: 12px;
                    min-width: 168px;
                    justify-content: center;
                    padding: 14px 18px;
                    border-radius: 8px;
                    border: 1px solid rgba(148, 163, 184, 0.45);
                    background: rgba(255, 255, 255, 0.96);
                    box-shadow: 0 18px 45px rgba(15, 23, 42, 0.18);
                    color: #0f172a;
                    font-family: "Source Sans Pro", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                    font-size: 0.95rem;
                    font-weight: 700;
                    letter-spacing: 0;
                }
                .creator-outreach-loading-spinner {
                    width: 20px;
                    height: 20px;
                    border-radius: 999px;
                    border: 3px solid #dbeafe;
                    border-top-color: #2563eb;
                    animation: creatorOutreachLoadingSpin 0.8s linear infinite;
                    flex: 0 0 auto;
                }
                @media (prefers-reduced-motion: reduce) {
                    .creator-outreach-loading-spinner {
                        animation: none;
                    }
                }
            `;
            doc.head.appendChild(style);

            const indicator = doc.createElement("div");
            indicator.id = "creator-outreach-loading-indicator";
            indicator.innerHTML = `
                <div class="creator-outreach-loading-card" role="status" aria-live="polite">
                    <div class="creator-outreach-loading-spinner" aria-hidden="true"></div>
                    <div>読み込み中...</div>
                </div>
            `;
            doc.body.appendChild(indicator);

            function elementIsVisible(element) {
                const rect = element.getBoundingClientRect();
                const computed = win.getComputedStyle(element);
                return (
                    rect.width > 0 &&
                    rect.height > 0 &&
                    computed.display !== "none" &&
                    computed.visibility !== "hidden" &&
                    computed.opacity !== "0"
                );
            }

            function updateIndicator() {
                const widgets = Array.from(doc.querySelectorAll('[data-testid="stStatusWidget"]'));
                const running = widgets.some((widget) => {
                    if (!elementIsVisible(widget)) {
                        return false;
                    }
                    const text = (widget.innerText || widget.textContent || "").trim().toLowerCase();
                    return text.includes("running") || text.includes("実行") || text.includes("処理") || text.includes("読み込み");
                });
                doc.body.classList.toggle("creator-outreach-is-loading", running);
            }

            win.setInterval(updateIndicator, 180);
            updateIndicator();
        })();
        </script>
        """,
        height=1,
        width=1,
    )


def get_secret(name: str, default: str = "") -> str:
    saved = get_setting(name)
    if saved:
        return saved
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return os.getenv(name, default)


def init_db() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.executescript(
            """
            create table if not exists contacts (
                id integer primary key autoincrement,
                user_id text not null default 'local-user',
                email text not null default '',
                name text not null default '',
                memo text not null default '',
                channel text not null default '',
                youtube_channel_id text not null default '',
                youtube_channel_url text not null default '',
                youtube_subscriber_count integer not null default 0,
                youtube_video_count integer not null default 0,
                youtube_view_count integer not null default 0,
                youtube_keyword text not null default '',
                youtube_description text not null default '',
                source text not null default '',
                consent integer not null default 0,
                unsubscribed integer not null default 0,
                contact_status text not null default '送信対象',
                replied_at text not null default '',
                token text not null unique,
                created_at text not null
            );

            create table if not exists sends (
                id integer primary key autoincrement,
                user_id text not null default 'local-user',
                contact_id integer not null,
                campaign_key text not null default '',
                send_job_id text not null default '',
                subject text not null,
                status text not null,
                error text not null default '',
                sent_at text not null,
                foreign key(contact_id) references contacts(id)
            );

            create table if not exists settings (
                user_id text not null default 'local-user',
                key text not null,
                value text not null,
                primary key (user_id, key)
            );

            create table if not exists smtp_accounts (
                id integer primary key autoincrement,
                user_id text not null default 'local-user',
                label text not null default '',
                sender_name text not null default '',
                sender_email text not null default '',
                smtp_host text not null default '',
                smtp_port text not null default '587',
                smtp_ssl integer not null default 0,
                smtp_pass text not null default '',
                created_at text not null,
                updated_at text not null
            );

            create table if not exists youtube_candidates (
                id integer primary key autoincrement,
                user_id text not null default 'local-user',
                channel_id text not null,
                email text not null default '',
                title text not null default '',
                channel_url text not null default '',
                subscriber_count integer not null default 0,
                video_count integer not null default 0,
                view_count integer not null default 0,
                description text not null default '',
                keyword text not null default '',
                created_at text not null
            );

            create table if not exists outsource_imports (
                id integer primary key autoincrement,
                user_id text not null default 'local-user',
                source_url text not null default '',
                source_type text not null default '',
                imported_count integer not null default 0,
                skipped_count integer not null default 0,
                candidate_removed_count integer not null default 0,
                candidate_discarded_count integer not null default 0,
                worker_name text not null default '',
                unit_price_yen integer not null default 50,
                receipt_note text not null default '',
                payment_status text not null default '未払い',
                receipt_issued_at text not null default '',
                created_at text not null
            );

            create table if not exists youtube_api_usage (
                user_id text not null default 'local-user',
                usage_date text not null,
                units integer not null default 0,
                primary key (user_id, usage_date)
            );

            create table if not exists blocked_targets (
                id integer primary key autoincrement,
                user_id text not null default 'local-user',
                email text not null default '',
                youtube_channel_id text not null default '',
                channel text not null default '',
                reason text not null default '',
                created_at text not null
            );

            create table if not exists campaign_templates (
                id integer primary key autoincrement,
                user_id text not null default 'local-user',
                name text not null,
                sort_order integer not null default 0,
                subject text not null default '',
                body text not null default '',
                updated_at text not null
            );

            create table if not exists unsubscribe_events (
                id integer primary key autoincrement,
                user_id text not null default 'local-user',
                contact_email text not null default '',
                youtube_channel_id text not null default '',
                channel text not null default '',
                campaign_key text not null default '',
                scope text not null default 'campaign',
                scope_key text not null default '',
                scope_label text not null default '',
                unsubscribed_at text not null
            );

            create table if not exists scenarios (
                id integer primary key autoincrement,
                user_id text not null default 'local-user',
                name text not null,
                created_at text not null,
                updated_at text not null
            );

            create table if not exists scenario_steps (
                id integer primary key autoincrement,
                user_id text not null default 'local-user',
                scenario_id integer not null,
                step_number integer not null,
                template_name text not null,
                foreign key(scenario_id) references scenarios(id)
            );
            """
        )
        columns = [row[1] for row in db.execute("pragma table_info(contacts)").fetchall()]
        migrations = {
            "user_id": "alter table contacts add column user_id text not null default 'local-user'",
            "youtube_channel_id": "alter table contacts add column youtube_channel_id text not null default ''",
            "youtube_channel_url": "alter table contacts add column youtube_channel_url text not null default ''",
            "youtube_subscriber_count": "alter table contacts add column youtube_subscriber_count integer not null default 0",
            "youtube_video_count": "alter table contacts add column youtube_video_count integer not null default 0",
            "youtube_view_count": "alter table contacts add column youtube_view_count integer not null default 0",
            "youtube_keyword": "alter table contacts add column youtube_keyword text not null default ''",
            "youtube_description": "alter table contacts add column youtube_description text not null default ''",
            "memo": "alter table contacts add column memo text not null default ''",
            "contact_status": "alter table contacts add column contact_status text not null default '送信対象'",
            "replied_at": "alter table contacts add column replied_at text not null default ''",
        }
        added_memo_column = False
        for column, statement in migrations.items():
            if column not in columns:
                db.execute(statement)
                if column == "memo":
                    added_memo_column = True
        if added_memo_column:
            db.execute("update contacts set memo = name where memo = '' and name != ''")
        for table in ["sends", "settings", "youtube_candidates", "outsource_imports", "youtube_api_usage", "blocked_targets", "campaign_templates", "smtp_accounts", "unsubscribe_events", "scenarios", "scenario_steps"]:
            table_columns = [row[1] for row in db.execute(f"pragma table_info({table})").fetchall()]
            if "user_id" not in table_columns:
                db.execute(f"alter table {table} add column user_id text not null default 'local-user'")
        candidate_columns = [row[1] for row in db.execute("pragma table_info(youtube_candidates)").fetchall()]
        if "email" not in candidate_columns:
            db.execute("alter table youtube_candidates add column email text not null default ''")
        outsource_import_columns = [row[1] for row in db.execute("pragma table_info(outsource_imports)").fetchall()]
        outsource_import_migrations = {
            "source_url": "alter table outsource_imports add column source_url text not null default ''",
            "source_type": "alter table outsource_imports add column source_type text not null default ''",
            "imported_count": "alter table outsource_imports add column imported_count integer not null default 0",
            "skipped_count": "alter table outsource_imports add column skipped_count integer not null default 0",
            "candidate_removed_count": "alter table outsource_imports add column candidate_removed_count integer not null default 0",
            "candidate_discarded_count": "alter table outsource_imports add column candidate_discarded_count integer not null default 0",
            "worker_name": "alter table outsource_imports add column worker_name text not null default ''",
            "unit_price_yen": "alter table outsource_imports add column unit_price_yen integer not null default 50",
            "receipt_note": "alter table outsource_imports add column receipt_note text not null default ''",
            "payment_status": "alter table outsource_imports add column payment_status text not null default '未払い'",
            "receipt_issued_at": "alter table outsource_imports add column receipt_issued_at text not null default ''",
            "created_at": "alter table outsource_imports add column created_at text not null default ''",
        }
        for column, statement in outsource_import_migrations.items():
            if column not in outsource_import_columns:
                db.execute(statement)
        sends_columns = [row[1] for row in db.execute("pragma table_info(sends)").fetchall()]
        if "campaign_key" not in sends_columns:
            db.execute("alter table sends add column campaign_key text not null default ''")
        if "send_job_id" not in sends_columns:
            db.execute("alter table sends add column send_job_id text not null default ''")
        campaign_columns = [row[1] for row in db.execute("pragma table_info(campaign_templates)").fetchall()]
        if "sort_order" not in campaign_columns:
            db.execute("alter table campaign_templates add column sort_order integer not null default 0")
            db.execute("update campaign_templates set sort_order = id where sort_order = 0")
        unsubscribe_columns = [row[1] for row in db.execute("pragma table_info(unsubscribe_events)").fetchall()]
        unsubscribe_migrations = {
            "scope": "alter table unsubscribe_events add column scope text not null default 'campaign'",
            "scope_key": "alter table unsubscribe_events add column scope_key text not null default ''",
            "scope_label": "alter table unsubscribe_events add column scope_label text not null default ''",
        }
        for column, statement in unsubscribe_migrations.items():
            if column not in unsubscribe_columns:
                db.execute(statement)
        db.execute(
            """
            update unsubscribe_events
            set scope = 'campaign',
                scope_key = campaign_key,
                scope_label = 'この配信'
            where coalesce(scope_key, '') = '' and coalesce(campaign_key, '') != ''
            """
        )
        db.execute(
            """
            insert into unsubscribe_events
            (user_id, contact_email, youtube_channel_id, channel, campaign_key, scope, scope_key, scope_label, unsubscribed_at)
            select user_id, email, youtube_channel_id, channel, '', 'global', 'global', 'すべての案内', created_at
            from blocked_targets
            where reason = '配信停止URL'
              and not exists (
                  select 1
                  from unsubscribe_events ue
                  where ue.user_id = blocked_targets.user_id
                    and ue.scope = 'global'
                    and (
                        (blocked_targets.email != '' and ue.contact_email = blocked_targets.email)
                        or
                        (blocked_targets.youtube_channel_id != '' and ue.youtube_channel_id = blocked_targets.youtube_channel_id)
                    )
              )
            """
        )
        db.execute("delete from blocked_targets where reason = '配信停止URL'")
        db.commit()


def fetch_contacts() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as db:
        return pd.read_sql_query(
            """
            select
                c.id,
                c.email,
                c.name,
                c.memo,
                c.channel,
                c.consent,
                c.unsubscribed,
                c.contact_status,
                c.replied_at,
                c.created_at,
                exists (
                    select 1
                    from unsubscribe_events ue_global
                    where ue_global.user_id = c.user_id
                      and ue_global.scope = 'global'
                      and (
                          (ue_global.contact_email != '' and ue_global.contact_email = lower(c.email))
                          or
                          (ue_global.youtube_channel_id != '' and ue_global.youtube_channel_id = c.youtube_channel_id)
                      )
                ) as global_unsubscribed,
                exists (
                    select 1
                    from unsubscribe_events ue_scoped
                    where ue_scoped.user_id = c.user_id
                      and ue_scoped.scope != 'global'
                      and (
                          (ue_scoped.contact_email != '' and ue_scoped.contact_email = lower(c.email))
                          or
                          (ue_scoped.youtube_channel_id != '' and ue_scoped.youtube_channel_id = c.youtube_channel_id)
                      )
                ) as scoped_unsubscribed,
                coalesce(max(s.sent_at), '') as last_sent
            from contacts c
            left join sends s on s.contact_id = c.id
            where c.user_id = ?
            group by c.id
            order by c.id asc
            """,
            db,
            params=(current_user_id(),),
        )


def fetch_candidates() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as db:
        return pd.read_sql_query(
            """
            select
                id,
                channel_id,
                email,
                title,
                channel_url,
                subscriber_count,
                video_count,
                view_count,
                keyword,
                created_at
            from youtube_candidates
            where user_id = ?
            order by id desc
            """,
            db,
            params=(current_user_id(),),
        )


def contacts_export_frame(contacts: pd.DataFrame) -> pd.DataFrame:
    export_columns = {
        "channel": "チャンネル名",
        "email": "Eメール",
        "memo": "メモ",
        "状態": "状態",
        "contact_status": "分類",
        "replied_at": "返信日時",
        "last_sent": "最終送信",
        "youtube_channel_url": "YouTube URL",
        "youtube_subscriber_count": "登録者数",
        "youtube_video_count": "動画数",
        "youtube_view_count": "総再生数",
        "youtube_keyword": "検索キーワード",
        "created_at": "登録日時",
    }
    available_columns = [column for column in export_columns if column in contacts.columns]
    return contacts[available_columns].rename(columns=export_columns)


def candidates_outsource_frame(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame(columns=OUTSOURCE_SHEET_COLUMNS)
    export = pd.DataFrame(
        {
            "チャンネル名": candidates["title"].fillna("").astype(str),
            "YouTube URL": candidates["channel_url"].fillna("").astype(str),
            "メールアドレス": candidates["email"].fillna("").astype(str) if "email" in candidates.columns else "",
            OUTSOURCE_DISCARD_COLUMN: False,
            "メモ": "",
            "状態": "",
            "候補ID（編集しない）": candidates["id"].fillna("").astype(str),
            "チャンネルID（編集しない）": candidates["channel_id"].fillna("").astype(str),
            "検索キーワード": candidates["keyword"].fillna("").astype(str),
            "作成日時": candidates["created_at"].fillna("").astype(str),
        }
    )
    return export


def outsource_sheet_cell_value(column: str, value: object) -> object:
    if column == OUTSOURCE_DISCARD_COLUMN:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "on", "checked", "x", "✓", "○", "はい"}
    return str(value or "")


def outsource_sheet_values(candidates: pd.DataFrame) -> list[list[object]]:
    frame = candidates_outsource_frame(candidates).fillna("")
    values = [list(frame.columns)]
    values.extend(
        [
            [outsource_sheet_cell_value(str(column), row[column]) for column in frame.columns]
            for _, row in frame.iterrows()
        ]
    )
    return values


def create_outsource_spreadsheet(token: str) -> tuple[str, str]:
    title = f"Creator Outreach Mailer 外注用候補 {datetime.now(APP_TIMEZONE).strftime('%Y-%m-%d %H:%M')}"
    result = google_api_request(
        "POST",
        "https://sheets.googleapis.com/v4/spreadsheets",
        token,
        {
            "properties": {"title": title},
            "sheets": [
                {
                    "properties": {
                        "title": OUTSOURCE_SHEET_NAME,
                        "gridProperties": {"frozenRowCount": 1},
                    }
                }
            ],
        },
    )
    spreadsheet_id = str(result.get("spreadsheetId") or "")
    spreadsheet_url = str(result.get("spreadsheetUrl") or "")
    if not spreadsheet_id:
        raise ValueError("Googleスプレッドシートを作成できませんでした。")
    save_setting("OUTSOURCE_SPREADSHEET_ID", spreadsheet_id)
    save_setting("OUTSOURCE_SPREADSHEET_URL", spreadsheet_url)
    return spreadsheet_id, spreadsheet_url


def get_or_create_outsource_spreadsheet(token: str) -> tuple[str, str]:
    spreadsheet_id = get_setting("OUTSOURCE_SPREADSHEET_ID").strip()
    spreadsheet_url = get_setting("OUTSOURCE_SPREADSHEET_URL").strip()
    if spreadsheet_url:
        try:
            extracted_id = extract_google_file_id(spreadsheet_url, "spreadsheets")
            if extracted_id and extracted_id != spreadsheet_id:
                spreadsheet_id = extracted_id
                save_setting("OUTSOURCE_SPREADSHEET_ID", spreadsheet_id)
        except Exception:
            pass
    if spreadsheet_id and spreadsheet_url:
        return spreadsheet_id, spreadsheet_url
    raise ValueError("先に空のGoogleスプレッドシートを作り、そのURLを登録してください。")


def rename_sheet(token: str, spreadsheet_id: str, sheet_id: int, title: str) -> None:
    google_api_request(
        "POST",
        f"https://sheets.googleapis.com/v4/spreadsheets/{urllib.parse.quote(spreadsheet_id, safe='')}:batchUpdate",
        token,
        {
            "requests": [
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": sheet_id, "title": title},
                        "fields": "title",
                    }
                }
            ]
        },
    )


def get_outsource_sheet_id(token: str, spreadsheet_id: str, preferred_gid: str = "") -> int:
    metadata = google_api_request(
        "GET",
        f"https://sheets.googleapis.com/v4/spreadsheets/{urllib.parse.quote(spreadsheet_id, safe='')}",
        token,
    )
    sheets = metadata.get("sheets", [])
    for sheet in metadata.get("sheets", []):
        properties = sheet.get("properties", {})
        if properties.get("title") == OUTSOURCE_SHEET_NAME:
            return int(properties.get("sheetId") or 0)
    for sheet in sheets:
        properties = sheet.get("properties", {})
        sheet_id = int(properties.get("sheetId") or 0)
        if preferred_gid and str(sheet_id) == str(preferred_gid):
            rename_sheet(token, spreadsheet_id, sheet_id, OUTSOURCE_SHEET_NAME)
            return sheet_id
    if len(sheets) == 1:
        properties = sheets[0].get("properties", {})
        sheet_id = int(properties.get("sheetId") or 0)
        rename_sheet(token, spreadsheet_id, sheet_id, OUTSOURCE_SHEET_NAME)
        return sheet_id
    result = google_api_request(
        "POST",
        f"https://sheets.googleapis.com/v4/spreadsheets/{urllib.parse.quote(spreadsheet_id, safe='')}:batchUpdate",
        token,
        {"requests": [{"addSheet": {"properties": {"title": OUTSOURCE_SHEET_NAME}}}]},
    )
    return int(
        result.get("replies", [{}])[0]
        .get("addSheet", {})
        .get("properties", {})
        .get("sheetId", 0)
    )


def google_sheet_range(sheet_name: str, cell_range: str = "A:Z") -> str:
    escaped_name = sheet_name.replace("'", "''")
    return f"'{escaped_name}'!{cell_range}"


def google_values_to_frame(values: list[list]) -> pd.DataFrame:
    if not values:
        return pd.DataFrame()
    header = [str(value).strip() for value in values[0]]
    if not any(header):
        return pd.DataFrame()
    width = len(header)
    rows = []
    for row in values[1:]:
        normalized = [str(value) for value in row[:width]]
        if len(normalized) < width:
            normalized.extend([""] * (width - len(normalized)))
        rows.append(normalized)
    return pd.DataFrame(rows, columns=header).fillna("")


def normalize_sheet_id_value(value: object) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d+(?:\.0+)?", text):
        return str(int(float(text)))
    return text


def outsource_sheet_existing_keys(frame: pd.DataFrame) -> tuple[set[str], set[str]]:
    if frame.empty:
        return set(), set()
    candidate_id_column = find_column(
        frame,
        {
            "候補id",
            "候補ID",
            "候補ID（編集しない）",
            "候補id編集しない",
            "候補ID編集しない",
        },
    )
    channel_id_column = find_column(
        frame,
        {
            "channel_id",
            "channelid",
            "youtube_channel_id",
            "youtubechannelid",
            "チャンネルid",
            "チャンネルID",
            "チャンネルID（編集しない）",
            "チャンネルID編集しない",
        },
    )
    candidate_ids = set()
    channel_ids = set()
    if candidate_id_column:
        candidate_ids = {
            normalized
            for normalized in frame[candidate_id_column].map(normalize_sheet_id_value)
            if normalized
        }
    if channel_id_column:
        channel_ids = {
            str(value or "").strip()
            for value in frame[channel_id_column].fillna("")
            if str(value or "").strip()
        }
    return candidate_ids, channel_ids


def pending_outsource_candidates(candidates: pd.DataFrame, existing_frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if candidates.empty or existing_frame.empty:
        return candidates.copy(), 0
    candidate_ids, channel_ids = outsource_sheet_existing_keys(existing_frame)
    if not candidate_ids and not channel_ids:
        return candidates.copy(), 0
    pending_mask = []
    already_count = 0
    for row in candidates.itertuples():
        candidate_id = normalize_sheet_id_value(getattr(row, "id", ""))
        channel_id = str(getattr(row, "channel_id", "") or "").strip()
        already_exists = bool((candidate_id and candidate_id in candidate_ids) or (channel_id and channel_id in channel_ids))
        pending_mask.append(not already_exists)
        if already_exists:
            already_count += 1
    return candidates[pending_mask].copy(), already_count


def outsource_candidate_row_key(row: object) -> str:
    candidate_id = normalize_sheet_id_value(getattr(row, "id", ""))
    channel_id = str(getattr(row, "channel_id", "") or "").strip()
    return f"{candidate_id}\t{channel_id}"


def outsource_candidate_keys(candidates: pd.DataFrame) -> list[str]:
    if candidates.empty:
        return []
    return [outsource_candidate_row_key(row) for row in candidates.itertuples()]


def outsource_candidates_signature(candidates: pd.DataFrame) -> str:
    return hashlib.sha1("\n".join(outsource_candidate_keys(candidates)).encode("utf-8")).hexdigest()


def filter_outsource_candidates_by_keys(candidates: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if candidates.empty:
        return candidates.copy()
    key_set = set(keys)
    mask = [outsource_candidate_row_key(row) in key_set for row in candidates.itertuples()]
    return candidates[mask].copy()


def read_google_sheet_url_with_service_account(url: str) -> pd.DataFrame:
    token = google_service_account_token(["https://www.googleapis.com/auth/spreadsheets.readonly"])
    spreadsheet_id = extract_google_file_id(url, "spreadsheets")
    target_gid = extract_google_sheet_gid(url)
    metadata = google_api_request(
        "GET",
        f"https://sheets.googleapis.com/v4/spreadsheets/{urllib.parse.quote(spreadsheet_id, safe='')}",
        token,
    )
    sheets = metadata.get("sheets", [])
    target_title = ""
    for sheet in sheets:
        properties = sheet.get("properties", {})
        if properties.get("title") == OUTSOURCE_SHEET_NAME:
            target_title = str(properties.get("title") or "")
            break
    if not target_title:
        for sheet in sheets:
            properties = sheet.get("properties", {})
            if str(properties.get("sheetId") or "") == str(target_gid):
                target_title = str(properties.get("title") or "")
                break
    if not target_title and sheets:
        target_title = str(sheets[0].get("properties", {}).get("title") or "")
    if not target_title:
        raise ValueError("Googleシート内のタブを読み取れませんでした。")
    range_name = urllib.parse.quote(google_sheet_range(target_title), safe="")
    result = google_api_request(
        "GET",
        f"https://sheets.googleapis.com/v4/spreadsheets/{urllib.parse.quote(spreadsheet_id, safe='')}/values/{range_name}",
        token,
    )
    return google_values_to_frame(result.get("values", []))


def read_outsource_sheet_values(token: str, spreadsheet_id: str) -> list[list]:
    range_name = urllib.parse.quote(google_sheet_range(OUTSOURCE_SHEET_NAME), safe="")
    result = google_api_request(
        "GET",
        f"https://sheets.googleapis.com/v4/spreadsheets/{urllib.parse.quote(spreadsheet_id, safe='')}/values/{range_name}",
        token,
    )
    return result.get("values", [])


def has_outsource_discard_column(values: list[list]) -> bool:
    if not values:
        return False
    header = [str(value or "").strip() for value in values[0]]
    return any(
        normalize_column_name(column)
        in {"候補から削除", "候補削除", "削除", "取り込まない", "取込まない", "除外", "メールなし", "noemail", "skip", "discard"}
        for column in header
    )


def discard_column_index(values: list[list]) -> int:
    if not values:
        return -1
    header = [str(value or "").strip() for value in values[0]]
    for index, column in enumerate(header):
        if normalize_column_name(column) in {
            "候補から削除",
            "候補削除",
            "削除",
            "取り込まない",
            "取込まない",
            "除外",
            "メールなし",
            "noemail",
            "skip",
            "discard",
        }:
            return index
    return -1


def add_outsource_discard_column(values: list[list]) -> list[list]:
    if not values:
        return [OUTSOURCE_SHEET_COLUMNS]
    existing_discard_index = discard_column_index(values)
    if existing_discard_index >= 0:
        normalized = [list(row) for row in values]
        normalized[0][existing_discard_index] = OUTSOURCE_DISCARD_COLUMN
        return normalized
    header = [str(value or "").strip() for value in values[0]]
    email_index = next(
        (
            index
            for index, column in enumerate(header)
            if normalize_column_name(column) in {"メールアドレス", "email", "emailaddress", "mail"}
        ),
        -1,
    )
    if email_index < 0:
        return values
    insert_index = email_index + 1
    migrated = []
    for row_index, row in enumerate(values):
        normalized = list(row)
        while len(normalized) < insert_index:
            normalized.append("")
        inserted_value = OUTSOURCE_DISCARD_COLUMN if row_index == 0 else False
        normalized.insert(insert_index, inserted_value)
        migrated.append(normalized)
    return migrated


def ensure_outsource_sheet_columns(token: str, spreadsheet_id: str, values: list[list]) -> list[list]:
    migrated_values = add_outsource_discard_column(values)
    if migrated_values is values or migrated_values == values:
        return values
    encoded_id = urllib.parse.quote(spreadsheet_id, safe="")
    encoded_range = urllib.parse.quote(google_sheet_range(OUTSOURCE_SHEET_NAME), safe="")
    google_api_request(
        "POST",
        f"https://sheets.googleapis.com/v4/spreadsheets/{encoded_id}/values/{encoded_range}:clear",
        token,
        {},
    )
    update_range = urllib.parse.quote(google_sheet_range(OUTSOURCE_SHEET_NAME, "A1"), safe="")
    google_api_request(
        "PUT",
        f"https://sheets.googleapis.com/v4/spreadsheets/{encoded_id}/values/{update_range}?valueInputOption=RAW",
        token,
        {"values": migrated_values},
    )
    return migrated_values


def format_outsource_sheet(token: str, spreadsheet_id: str, sheet_id: int) -> None:
    encoded_id = urllib.parse.quote(spreadsheet_id, safe="")
    google_api_request(
        "POST",
        f"https://sheets.googleapis.com/v4/spreadsheets/{encoded_id}:batchUpdate",
        token,
        {
            "requests": [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 0.94, "green": 0.96, "blue": 1.0},
                                "textFormat": {"bold": True},
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat)",
                    }
                },
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": sheet_id,
                            "gridProperties": {"frozenRowCount": 1},
                        },
                        "fields": "gridProperties.frozenRowCount",
                    }
                },
                {
                    "autoResizeDimensions": {
                        "dimensions": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": len(OUTSOURCE_SHEET_COLUMNS),
                        }
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "startColumnIndex": OUTSOURCE_SHEET_COLUMNS.index(OUTSOURCE_DISCARD_COLUMN),
                            "endColumnIndex": OUTSOURCE_SHEET_COLUMNS.index(OUTSOURCE_DISCARD_COLUMN) + 1,
                        },
                        "cell": {
                            "dataValidation": {
                                "condition": {"type": "BOOLEAN"},
                                "strict": True,
                                "showCustomUi": True,
                            }
                        },
                        "fields": "dataValidation",
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": OUTSOURCE_SHEET_COLUMNS.index(OUTSOURCE_DISCARD_COLUMN),
                            "endIndex": OUTSOURCE_SHEET_COLUMNS.index(OUTSOURCE_DISCARD_COLUMN) + 1,
                        },
                        "properties": {"pixelSize": 130},
                        "fields": "pixelSize",
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": OUTSOURCE_SHEET_COLUMNS.index("メモ"),
                            "endIndex": OUTSOURCE_SHEET_COLUMNS.index("メモ") + 1,
                        },
                        "properties": {"pixelSize": 190},
                        "fields": "pixelSize",
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": OUTSOURCE_SHEET_COLUMNS.index("状態"),
                            "endIndex": OUTSOURCE_SHEET_COLUMNS.index("状態") + 1,
                        },
                        "properties": {"pixelSize": 110},
                        "fields": "pixelSize",
                    }
                },
            ]
        },
    )


def update_outsource_spreadsheet(candidates: pd.DataFrame, share_with_link: bool = False) -> tuple[str, int]:
    ready, message = google_sheet_write_ready()
    if not ready:
        raise ValueError(message)
    token = google_service_account_token(
        [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
        ]
    )
    spreadsheet_id, spreadsheet_url = get_or_create_outsource_spreadsheet(token)
    preferred_gid = extract_google_sheet_gid(spreadsheet_url)
    sheet_id = get_outsource_sheet_id(token, spreadsheet_id, preferred_gid)
    encoded_id = urllib.parse.quote(spreadsheet_id, safe="")
    encoded_range = urllib.parse.quote(google_sheet_range(OUTSOURCE_SHEET_NAME), safe="")
    google_api_request(
        "POST",
        f"https://sheets.googleapis.com/v4/spreadsheets/{encoded_id}/values/{encoded_range}:clear",
        token,
        {},
    )
    values = outsource_sheet_values(candidates)
    update_range = urllib.parse.quote(google_sheet_range(OUTSOURCE_SHEET_NAME, "A1"), safe="")
    google_api_request(
        "PUT",
        f"https://sheets.googleapis.com/v4/spreadsheets/{encoded_id}/values/{update_range}?valueInputOption=RAW",
        token,
        {"values": values},
    )
    format_outsource_sheet(token, spreadsheet_id, sheet_id)
    if share_with_link:
        google_api_request(
            "POST",
            f"https://www.googleapis.com/drive/v3/files/{encoded_id}/permissions",
            token,
            {"type": "anyone", "role": "writer"},
        )
    return spreadsheet_url, max(0, len(values) - 1)


def append_new_outsource_candidates(candidates: pd.DataFrame) -> tuple[str, int, int]:
    ready, message = google_sheet_write_ready()
    if not ready:
        raise ValueError(message)
    token = google_service_account_token(
        [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
        ]
    )
    spreadsheet_id, spreadsheet_url = get_or_create_outsource_spreadsheet(token)
    preferred_gid = extract_google_sheet_gid(spreadsheet_url)
    sheet_id = get_outsource_sheet_id(token, spreadsheet_id, preferred_gid)
    existing_values = read_outsource_sheet_values(token, spreadsheet_id)
    existing_values = ensure_outsource_sheet_columns(token, spreadsheet_id, existing_values)
    existing_frame = google_values_to_frame(existing_values)
    new_candidates, already_count = pending_outsource_candidates(candidates, existing_frame)
    if new_candidates.empty:
        format_outsource_sheet(token, spreadsheet_id, sheet_id)
        return spreadsheet_url, 0, already_count

    values = outsource_sheet_values(new_candidates)
    encoded_id = urllib.parse.quote(spreadsheet_id, safe="")
    if not existing_values or not any(str(value).strip() for value in existing_values[0]):
        write_values = values
        start_cell = "A1"
    else:
        write_values = values[1:]
        start_cell = f"A{len(existing_values) + 1}"
    update_range = urllib.parse.quote(google_sheet_range(OUTSOURCE_SHEET_NAME, start_cell), safe="")
    google_api_request(
        "PUT",
        f"https://sheets.googleapis.com/v4/spreadsheets/{encoded_id}/values/{update_range}?valueInputOption=RAW",
        token,
        {"values": write_values},
    )
    format_outsource_sheet(token, spreadsheet_id, sheet_id)
    return spreadsheet_url, len(new_candidates), already_count


def repair_outsource_spreadsheet_columns(url: str) -> str:
    ready, message = google_sheet_write_ready()
    if not ready:
        raise ValueError(message)
    if not url.strip().startswith("http"):
        raise ValueError("外注用GoogleスプレッドシートURLを入力してください。")
    save_setting("OUTSOURCE_SPREADSHEET_URL", url.strip())
    token = google_service_account_token(
        [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
        ]
    )
    spreadsheet_id, spreadsheet_url = get_or_create_outsource_spreadsheet(token)
    preferred_gid = extract_google_sheet_gid(spreadsheet_url)
    sheet_id = get_outsource_sheet_id(token, spreadsheet_id, preferred_gid)
    existing_values = read_outsource_sheet_values(token, spreadsheet_id)
    ensure_outsource_sheet_columns(token, spreadsheet_id, existing_values)
    format_outsource_sheet(token, spreadsheet_id, sheet_id)
    return spreadsheet_url


def check_outsource_spreadsheet_connection(url: str) -> str:
    ready, message = google_sheet_write_ready()
    if not ready:
        raise ValueError(message)
    if not url.strip().startswith("http"):
        raise ValueError("外注用GoogleスプレッドシートURLを入力してください。")
    token = google_service_account_token(["https://www.googleapis.com/auth/spreadsheets.readonly"])
    spreadsheet_id = extract_google_file_id(url.strip(), "spreadsheets")
    metadata = google_api_request(
        "GET",
        f"https://sheets.googleapis.com/v4/spreadsheets/{urllib.parse.quote(spreadsheet_id, safe='')}",
        token,
    )
    title = str(metadata.get("properties", {}).get("title") or "名称未設定")
    sheet_count = len(metadata.get("sheets", []))
    return f"接続できました: {title}（タブ{sheet_count}件）"


def refresh_outsource_sheet_if_possible() -> str:
    if not get_setting("OUTSOURCE_SPREADSHEET_ID").strip():
        return ""
    ready, _message = google_sheet_write_ready()
    if not ready:
        return ""
    try:
        _url, count = update_outsource_spreadsheet(fetch_candidates(), False)
        return f"外注用Googleシートも更新しました。残り候補は{count}件です。"
    except Exception:
        return ""


def dataframe_to_xlsx(frame: pd.DataFrame, sheet_name: str = "宛先一覧") -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()


def execute(query: str, params: tuple = ()) -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute(query, params)
        db.commit()
    mark_app_state_dirty()


def normalize_outsource_unit_price(value: object) -> int:
    try:
        price = int(value)
    except (TypeError, ValueError):
        price = OUTSOURCE_DEFAULT_UNIT_PRICE_YEN
    return min(OUTSOURCE_MAX_UNIT_PRICE_YEN, max(OUTSOURCE_MIN_UNIT_PRICE_YEN, price))


def outsource_payment_amount(imported_count: object, unit_price_yen: object) -> int:
    try:
        count = max(0, int(imported_count))
    except (TypeError, ValueError):
        count = 0
    return count * normalize_outsource_unit_price(unit_price_yen)


def save_outsource_import_history(
    source_url: str,
    source_type: str,
    imported_count: int,
    skipped_count: int,
    mapping: dict[str, str | None],
) -> int:
    worker_name = get_setting("OUTSOURCE_DEFAULT_WORKER_NAME")
    unit_price_yen = normalize_outsource_unit_price(
        get_setting("OUTSOURCE_DEFAULT_UNIT_PRICE_YEN", str(OUTSOURCE_DEFAULT_UNIT_PRICE_YEN))
    )
    candidate_removed_count = int(mapping.get("candidate_removed") or 0)
    candidate_discarded_count = int(mapping.get("candidate_discarded") or 0)
    with sqlite3.connect(DB_PATH) as db:
        cursor = db.execute(
            """
            insert into outsource_imports
            (
                user_id, source_url, source_type, imported_count, skipped_count,
                candidate_removed_count, candidate_discarded_count, worker_name,
                unit_price_yen, receipt_note, payment_status, receipt_issued_at, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, '', '未払い', '', ?)
            """,
            (
                current_user_id(),
                source_url.strip(),
                source_type.strip(),
                int(imported_count),
                int(skipped_count),
                candidate_removed_count,
                candidate_discarded_count,
                worker_name,
                unit_price_yen,
                now_iso(),
            ),
        )
        db.commit()
        history_id = int(cursor.lastrowid)
    mark_app_state_dirty()
    return history_id


def fetch_outsource_import_history(limit: int = 100) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as db:
        return pd.read_sql_query(
            """
            select
                id,
                source_url,
                source_type,
                imported_count,
                skipped_count,
                candidate_removed_count,
                candidate_discarded_count,
                worker_name,
                unit_price_yen,
                receipt_note,
                payment_status,
                receipt_issued_at,
                created_at
            from outsource_imports
            where user_id = ?
            order by id desc
            limit ?
            """,
            db,
            params=(current_user_id(), int(limit)),
        ).fillna("")


def update_outsource_import_receipt(
    import_id: int,
    worker_name: str,
    unit_price_yen: int,
    receipt_note: str,
    payment_status: str,
    receipt_issued_at: str,
) -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """
            update outsource_imports
            set worker_name = ?,
                unit_price_yen = ?,
                receipt_note = ?,
                payment_status = ?,
                receipt_issued_at = ?
            where user_id = ? and id = ?
            """,
            (
                worker_name.strip(),
                normalize_outsource_unit_price(unit_price_yen),
                receipt_note.strip(),
                payment_status.strip() or "未払い",
                receipt_issued_at.strip(),
                current_user_id(),
                int(import_id),
            ),
        )
        db.commit()
    mark_app_state_dirty()


def outsource_import_history_display_frame(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame(
            columns=[
                "取り込み日時",
                "実取り込み件数",
                "単価",
                "金額",
                "スキップ",
                "候補から削除",
                "支払い状態",
                "外注さん",
            ]
        )
    display = history.copy()
    display["取り込み日時"] = display["created_at"].apply(format_jst_datetime)
    display["実取り込み件数"] = display["imported_count"].astype(int)
    display["単価"] = display["unit_price_yen"].apply(lambda value: f"{normalize_outsource_unit_price(value):,}円")
    display["金額"] = display.apply(
        lambda row: f"{outsource_payment_amount(row['imported_count'], row['unit_price_yen']):,}円",
        axis=1,
    )
    display["スキップ"] = display["skipped_count"].astype(int)
    display["候補から削除"] = display["candidate_discarded_count"].astype(int)
    display["支払い状態"] = display["payment_status"].replace("", "未払い")
    display["外注さん"] = display["worker_name"].replace("", "-")
    return display[
        [
            "取り込み日時",
            "実取り込み件数",
            "単価",
            "金額",
            "スキップ",
            "候補から削除",
            "支払い状態",
            "外注さん",
        ]
    ]


def outsource_receipt_file_name(record_id: int, issue_date: date) -> str:
    return f"outsource_receipt_OUT-{int(record_id):06d}_{issue_date.strftime('%Y%m%d')}.html"


def build_outsource_receipt_html(
    record: dict,
    worker_name: str,
    payer_name: str,
    unit_price_yen: int,
    issue_date: date,
    receipt_note: str,
    payment_status: str,
) -> str:
    record_id = int(record.get("id") or 0)
    imported_count = int(record.get("imported_count") or 0)
    skipped_count = int(record.get("skipped_count") or 0)
    discarded_count = int(record.get("candidate_discarded_count") or 0)
    normalized_unit_price = normalize_outsource_unit_price(unit_price_yen)
    amount = outsource_payment_amount(imported_count, normalized_unit_price)
    safe_worker_name = html.escape(worker_name.strip() or "外注担当者")
    safe_payer_name = html.escape(payer_name.strip() or "ご担当者")
    safe_note = html.escape(receipt_note.strip()).replace("\n", "<br>")
    safe_source_url = html.escape(str(record.get("source_url") or ""))
    safe_payment_status = html.escape(payment_status.strip() or "未払い")
    imported_at = html.escape(format_jst_datetime(str(record.get("created_at") or "")))
    issue_date_text = issue_date.strftime("%Y年%m月%d日")
    receipt_no = f"OUT-{record_id:06d}"
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>領収書 {receipt_no}</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #111827;
    margin: 40px;
    line-height: 1.65;
}}
.page {{
    max-width: 760px;
    margin: 0 auto;
}}
h1 {{
    text-align: center;
    letter-spacing: 0;
    margin: 0 0 28px;
}}
.meta {{
    text-align: right;
    color: #475569;
    font-size: 14px;
}}
.amount {{
    border: 2px solid #111827;
    padding: 16px 20px;
    font-size: 28px;
    font-weight: 700;
    margin: 24px 0;
    text-align: center;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 18px;
}}
th, td {{
    border: 1px solid #CBD5E1;
    padding: 10px 12px;
    text-align: left;
    vertical-align: top;
}}
th {{
    width: 34%;
    background: #F8FAFC;
}}
.url {{
    word-break: break-all;
}}
.note {{
    margin-top: 20px;
    color: #334155;
}}
@media print {{
    body {{ margin: 18mm; }}
}}
</style>
</head>
<body>
<div class="page">
    <div class="meta">発行日: {issue_date_text}<br>No: {receipt_no}</div>
    <h1>領収書</h1>
    <p>{safe_payer_name} 様</p>
    <p>下記の通り、外注メール収集作業の報酬として受領いたしました。</p>
    <div class="amount">金額 ¥{amount:,}</div>
    <table>
        <tr><th>外注さん</th><td>{safe_worker_name}</td></tr>
        <tr><th>対象作業</th><td>外注用Googleスプレッドシートから宛先一覧への取り込み</td></tr>
        <tr><th>実取り込み件数</th><td>{imported_count:,}件</td></tr>
        <tr><th>単価</th><td>1件あたり ¥{normalized_unit_price:,}</td></tr>
        <tr><th>計算式</th><td>{imported_count:,}件 × ¥{normalized_unit_price:,} = ¥{amount:,}</td></tr>
        <tr><th>取り込み日時</th><td>{imported_at}</td></tr>
        <tr><th>スキップ件数</th><td>{skipped_count:,}件</td></tr>
        <tr><th>候補から削除</th><td>{discarded_count:,}件</td></tr>
        <tr><th>支払い状態</th><td>{safe_payment_status}</td></tr>
        <tr><th>GoogleシートURL</th><td class="url">{safe_source_url}</td></tr>
    </table>
    <div class="note">{safe_note}</div>
</div>
</body>
</html>
"""


APP_STATE_TABLES = [
    "contacts",
    "sends",
    "settings",
    "smtp_accounts",
    "youtube_candidates",
    "outsource_imports",
    "youtube_api_usage",
    "blocked_targets",
    "campaign_templates",
    "unsubscribe_events",
    "scenarios",
    "scenario_steps",
]


def app_state_user_email() -> str:
    return current_user_profile().get("email", "").strip().lower()


def app_state_can_sync() -> bool:
    return bool(supabase_configured() and app_state_user_email())


def table_columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in db.execute(f"pragma table_info({table})").fetchall()]


def export_local_app_state() -> dict:
    user_id = current_user_id()
    state_tables: dict[str, list[dict]] = {}
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        for table in APP_STATE_TABLES:
            columns = table_columns(db, table)
            if not columns:
                continue
            if "user_id" in columns:
                records = db.execute(
                    f"select * from {table} where user_id = ? order by rowid asc",
                    (user_id,),
                ).fetchall()
            else:
                records = db.execute(f"select * from {table} order by rowid asc").fetchall()
            state_tables[table] = [dict(record) for record in records]
    return {
        "version": 1,
        "saved_at": now_iso(),
        "user_id": user_id,
        "tables": state_tables,
    }


def restore_local_app_state(state: dict) -> None:
    tables = state.get("tables") if isinstance(state, dict) else None
    if not isinstance(tables, dict):
        return

    user_id = current_user_id()
    delete_order = [
        "sends",
        "contacts",
        "settings",
        "smtp_accounts",
        "youtube_candidates",
        "outsource_imports",
        "youtube_api_usage",
        "blocked_targets",
        "campaign_templates",
        "unsubscribe_events",
        "scenario_steps",
        "scenarios",
    ]
    insert_order = [
        "contacts",
        "settings",
        "smtp_accounts",
        "youtube_candidates",
        "outsource_imports",
        "youtube_api_usage",
        "blocked_targets",
        "campaign_templates",
        "unsubscribe_events",
        "scenarios",
        "scenario_steps",
        "sends",
    ]

    st.session_state["_restoring_app_state"] = True
    try:
        with sqlite3.connect(DB_PATH) as db:
            for table in delete_order:
                columns = table_columns(db, table)
                if "user_id" in columns:
                    db.execute(f"delete from {table} where user_id = ?", (user_id,))

            for table in insert_order:
                columns = table_columns(db, table)
                if not columns:
                    continue
                for record in tables.get(table, []):
                    if not isinstance(record, dict):
                        continue
                    clean = {key: value for key, value in record.items() if key in columns}
                    if "user_id" in columns:
                        clean["user_id"] = user_id
                    if not clean:
                        continue
                    column_names = list(clean.keys())
                    placeholders = ", ".join(["?"] * len(column_names))
                    db.execute(
                        f"insert or replace into {table} ({', '.join(column_names)}) values ({placeholders})",
                        tuple(clean[column] for column in column_names),
                    )
            db.commit()
    finally:
        st.session_state["_restoring_app_state"] = False


def save_app_state_to_supabase() -> None:
    if not app_state_can_sync() or st.session_state.get("_restoring_app_state"):
        return
    try:
        saved_at = now_iso()
        supabase_request(
            "POST",
            "app_state?on_conflict=user_email",
            {
                "user_email": app_state_user_email(),
                "state": export_local_app_state(),
                "updated_at": saved_at,
            },
            prefer="resolution=merge-duplicates,return=minimal",
        )
        st.session_state["_last_app_state_saved_at"] = saved_at
        st.session_state.pop("_last_app_state_save_error", None)
    except Exception as exc:
        st.session_state["_last_app_state_save_error"] = str(exc)


def load_app_state_from_supabase() -> None:
    if not app_state_can_sync():
        return
    email = app_state_user_email()
    loaded_key = f"_app_state_loaded::{email}"
    if st.session_state.get(loaded_key):
        return
    try:
        query_email = urllib.parse.quote(email, safe="")
        result = supabase_request(
            "GET",
            f"app_state?user_email=eq.{query_email}&select=state,updated_at&limit=1",
        )
        if isinstance(result, list) and result:
            restore_local_app_state(result[0].get("state", {}))
            if result[0].get("updated_at"):
                st.session_state["_last_app_state_saved_at"] = str(result[0].get("updated_at"))
        else:
            save_app_state_to_supabase()
        st.session_state[loaded_key] = True
    except Exception as exc:
        st.session_state["_last_app_state_load_error"] = str(exc)


def mark_app_state_dirty() -> None:
    if st.session_state.get("_restoring_app_state"):
        return
    if app_state_can_sync() and st.session_state.get(f"_app_state_loaded::{app_state_user_email()}"):
        st.session_state["_app_state_dirty"] = True


def flush_app_state_if_dirty() -> None:
    if not st.session_state.get("_app_state_dirty"):
        return
    save_app_state_to_supabase()
    if "_last_app_state_save_error" not in st.session_state:
        st.session_state["_app_state_dirty"] = False


def render_app_state_sync_panel() -> None:
    with st.container():
        st.markdown("#### データ保存")
        if not supabase_configured():
            st.warning("Supabase未設定のため、データ保存はこのアプリ内だけで行われています。")
            return
        if not app_state_user_email():
            st.warning("Googleログインのメールアドレスを確認できないため、Supabase保存を実行できません。")
            return

        status_col, button_col = st.columns([2.2, 1.0])
        last_saved = st.session_state.get("_last_app_state_saved_at", "")
        if last_saved:
            status_col.caption(f"最終保存: {format_jst_datetime(str(last_saved))}")
        else:
            status_col.caption("まだこの画面では保存確認ができていません。")

        if button_col.button("現在のデータを保存", key="manual_save_app_state", width="stretch"):
            save_app_state_to_supabase()
            if "_last_app_state_save_error" in st.session_state:
                st.error("Supabaseへの保存に失敗しました。設定や通信状態を確認してください。")
                st.caption(st.session_state["_last_app_state_save_error"])
            else:
                st.session_state["_app_state_dirty"] = False
                st.success("現在のデータをSupabaseに保存しました。")

        if st.session_state.get("_app_state_dirty"):
            st.info("未保存の変更があります。しばらくすると自動保存されますが、心配な場合は「現在のデータを保存」を押してください。")
        elif last_saved:
            st.success("データ保存は有効です。")


def get_youtube_daily_limit() -> int:
    value = get_setting("YOUTUBE_DAILY_LIMIT", "10000")
    try:
        return max(1, int(value))
    except ValueError:
        return 10000


def estimate_youtube_units(max_results: int, search_mode: str = "キーワード") -> int:
    pages = max(1, (max(1, int(max_results)) + 49) // 50)
    if search_mode == "カテゴリー":
        return pages * 2
    return pages * 101


def get_youtube_units_used(date_key: str | None = None) -> int:
    key = date_key or today_key()
    scoped_key = f"{current_user_id()}::{key}"
    result = rows("select units from youtube_api_usage where usage_date = ?", (scoped_key,))
    return int(result[0]["units"]) if result else 0


def add_youtube_units(units: int, date_key: str | None = None) -> None:
    key = date_key or today_key()
    scoped_key = f"{current_user_id()}::{key}"
    new_total = get_youtube_units_used(key) + int(units)
    execute("delete from youtube_api_usage where usage_date = ?", (scoped_key,))
    execute(
        """
        insert into youtube_api_usage(user_id, usage_date, units)
        values(?, ?, ?)
        """,
        (current_user_id(), scoped_key, new_total),
    )


def get_setting(key: str, default: str = "") -> str:
    if not DB_PATH.exists():
        return default
    scoped_key = f"{current_user_id()}::{key}"
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute("select value from settings where key = ?", (scoped_key,)).fetchone()
        return str(row[0]) if row else default


def save_setting(key: str, value: str) -> None:
    scoped_key = f"{current_user_id()}::{key}"
    delete_setting(key)
    execute(
        "insert into settings(user_id, key, value) values(?, ?, ?)",
        (current_user_id(), scoped_key, value),
    )


def delete_setting(key: str) -> None:
    scoped_key = f"{current_user_id()}::{key}"
    execute("delete from settings where key = ?", (scoped_key,))


def fetch_smtp_accounts() -> list[sqlite3.Row]:
    return rows(
        """
        select id, label, sender_name, sender_email, smtp_host, smtp_port, smtp_ssl, smtp_pass
        from smtp_accounts
        where user_id = ?
        order by id asc
        """,
        (current_user_id(),),
    )


def get_smtp_account(account_id: int) -> sqlite3.Row | None:
    matches = rows(
        """
        select id, label, sender_name, sender_email, smtp_host, smtp_port, smtp_ssl, smtp_pass
        from smtp_accounts
        where user_id = ? and id = ?
        limit 1
        """,
        (current_user_id(), int(account_id)),
    )
    return matches[0] if matches else None


def save_smtp_account(
    account_id: int | None,
    label: str,
    sender_name: str,
    sender_email: str,
    smtp_host: str,
    smtp_port: str,
    smtp_ssl: bool,
    smtp_pass: str,
) -> int:
    clean_label = label.strip() or sender_email.strip()
    existing_pass = ""
    if account_id:
        existing = get_smtp_account(account_id)
        existing_pass = existing["smtp_pass"] if existing else ""
    password_to_save = smtp_pass or existing_pass
    if account_id and get_smtp_account(account_id):
        execute(
            """
            update smtp_accounts
            set label = ?, sender_name = ?, sender_email = ?, smtp_host = ?, smtp_port = ?,
                smtp_ssl = ?, smtp_pass = ?, updated_at = ?
            where user_id = ? and id = ?
            """,
            (
                clean_label,
                sender_name.strip(),
                sender_email.strip(),
                smtp_host.strip(),
                smtp_port.strip(),
                1 if smtp_ssl else 0,
                password_to_save,
                now_iso(),
                current_user_id(),
                int(account_id),
            ),
        )
        return int(account_id)
    execute(
        """
        insert into smtp_accounts
        (user_id, label, sender_name, sender_email, smtp_host, smtp_port, smtp_ssl, smtp_pass, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            current_user_id(),
            clean_label,
            sender_name.strip(),
            sender_email.strip(),
            smtp_host.strip(),
            smtp_port.strip(),
            1 if smtp_ssl else 0,
            password_to_save,
            now_iso(),
            now_iso(),
        ),
    )
    account = rows(
        "select id from smtp_accounts where user_id = ? order by id desc limit 1",
        (current_user_id(),),
    )[0]
    return int(account["id"])


def delete_smtp_account(account_id: int) -> None:
    execute("delete from smtp_accounts where user_id = ? and id = ?", (current_user_id(), int(account_id)))
    if get_setting("ACTIVE_SMTP_ACCOUNT_ID") == str(account_id):
        delete_setting("ACTIVE_SMTP_ACCOUNT_ID")


def active_smtp_account() -> dict[str, str | int]:
    accounts = fetch_smtp_accounts()
    active_id = get_setting("ACTIVE_SMTP_ACCOUNT_ID")
    if active_id:
        try:
            selected = get_smtp_account(int(active_id))
            if selected:
                return dict(selected)
        except ValueError:
            pass
    if accounts:
        return dict(accounts[0])
    sender_name = get_setting("SENDER_NAME", "")
    sender_email = get_setting("SMTP_USER", "")
    return {
        "id": 0,
        "label": sender_email or "送信元設定",
        "sender_name": sender_name,
        "sender_email": sender_email,
        "smtp_host": get_setting("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": get_setting("SMTP_PORT", "587"),
        "smtp_ssl": 1 if get_setting("SMTP_SSL", "false").lower() in {"1", "true", "yes"} else 0,
        "smtp_pass": get_setting("SMTP_PASS", ""),
    }


def smtp_mail_from(account: dict[str, str | int]) -> str:
    sender_name = str(account.get("sender_name") or "").strip()
    sender_email = str(account.get("sender_email") or "").strip()
    return f"{sender_name} <{sender_email}>" if sender_name else sender_email


def fetch_campaign_templates() -> list[sqlite3.Row]:
    return rows(
        """
        select id, name, sort_order, subject, body, updated_at
        from campaign_templates
        where user_id = ?
        order by sort_order asc, id asc
        """,
        (current_user_id(),),
    )


def get_campaign_template(name: str) -> sqlite3.Row | None:
    matches = rows(
        """
        select id, name, sort_order, subject, body, updated_at
        from campaign_templates
        where user_id = ? and name = ?
        limit 1
        """,
        (current_user_id(), name.strip()),
    )
    return matches[0] if matches else None


def save_campaign_template(name: str, subject: str, body: str) -> None:
    clean_name = name.strip()
    if not clean_name:
        return
    existing = get_campaign_template(clean_name)
    if existing:
        execute(
            """
            update campaign_templates
            set subject = ?, body = ?, updated_at = ?
            where user_id = ? and id = ?
            """,
            (subject, body, now_iso(), current_user_id(), int(existing["id"])),
        )
        return
    else:
        max_order = rows(
            "select coalesce(max(sort_order), 0) as max_order from campaign_templates where user_id = ?",
            (current_user_id(),),
        )[0]["max_order"]
        sort_order = int(max_order) + 10
    execute(
        """
        insert into campaign_templates(user_id, name, sort_order, subject, body, updated_at)
        values(?, ?, ?, ?, ?, ?)
        """,
        (current_user_id(), clean_name, sort_order, subject, body, now_iso()),
    )


def delete_campaign_template(name: str) -> None:
    clean_name = name.strip()
    execute(
        "delete from campaign_templates where user_id = ? and name = ?",
        (current_user_id(), clean_name),
    )
    default_names = {template_name for template_name, _, _ in DEFAULT_CAMPAIGN_TEMPLATES}
    if clean_name in default_names:
        deleted_defaults = {
            item.strip()
            for item in get_setting("DELETED_DEFAULT_CAMPAIGN_TEMPLATES", "").split("|")
            if item.strip()
        }
        deleted_defaults.add(clean_name)
        save_setting("DELETED_DEFAULT_CAMPAIGN_TEMPLATES", "|".join(sorted(deleted_defaults)))


def move_campaign_template(name: str, direction: int) -> None:
    templates = fetch_campaign_templates()
    names = [template["name"] for template in templates]
    if name not in names:
        return
    index = names.index(name)
    new_index = index + direction
    if new_index < 0 or new_index >= len(templates):
        return
    current = templates[index]
    other = templates[new_index]
    execute(
        "update campaign_templates set sort_order = ? where user_id = ? and id = ?",
        (int(other["sort_order"]), current_user_id(), int(current["id"])),
    )
    execute(
        "update campaign_templates set sort_order = ? where user_id = ? and id = ?",
        (int(current["sort_order"]), current_user_id(), int(other["id"])),
    )


def save_campaign_template_order(names: list[str]) -> None:
    for index, name in enumerate(names):
        execute(
            "update campaign_templates set sort_order = ? where user_id = ? and name = ?",
            ((index + 1) * 10, current_user_id(), name),
        )


def openai_api_key() -> str:
    return get_nested_secret("openai", "api_key") or read_secret("OPENAI_API_KEY")


def openai_model() -> str:
    model = (get_nested_secret("openai", "model") or read_secret("OPENAI_MODEL") or "gpt-4.1-mini").strip()
    if model in {"gpt-5.5", "gpt-5-mini"}:
        return "gpt-4.1-mini"
    return model


def set_ai_scenario_status(status: str, message: str = "", detail: str = "") -> None:
    st.session_state["ai_scenario_last_status"] = {
        "status": str(status or "").strip(),
        "message": str(message or "").strip(),
        "detail": str(detail or "").strip(),
        "at": now_iso(),
    }


def ai_scenario_status_label(status: str) -> str:
    labels = {
        "idle": "待機中",
        "running": "生成中",
        "generated": "生成済み・未保存",
        "saved": "保存済み",
        "failed": "エラー",
    }
    return labels.get(str(status or "").strip(), "未確認")


def log_ai_scenario_event(event: str, detail: str = "") -> None:
    safe_detail = re.sub(r"\s+", " ", str(detail or "")).strip()[:300]
    suffix = f" {safe_detail}" if safe_detail else ""
    print(f"[AI scenario] {event}{suffix}", flush=True)


def ai_scenario_status_age_seconds(status_record: dict) -> int:
    try:
        created_at = datetime.fromisoformat(str(status_record.get("at") or ""))
    except Exception:
        return 0
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=APP_TIMEZONE)
    elapsed = datetime.now(APP_TIMEZONE) - created_at.astimezone(APP_TIMEZONE)
    return max(0, int(elapsed.total_seconds()))


def format_elapsed_seconds(seconds: int) -> str:
    clean_seconds = max(0, int(seconds))
    minutes, remaining_seconds = divmod(clean_seconds, 60)
    if minutes:
        return f"{minutes}分{remaining_seconds:02d}秒"
    return f"{remaining_seconds}秒"


def refresh_stale_ai_scenario_status() -> None:
    status_record = st.session_state.get("ai_scenario_last_status")
    if not isinstance(status_record, dict):
        return
    if str(status_record.get("status") or "") != "running":
        return
    elapsed_seconds = ai_scenario_status_age_seconds(status_record)
    if elapsed_seconds < AI_SCENARIO_STALE_SECONDS:
        return
    set_ai_scenario_status(
        "failed",
        "前回のAI生成がサーバーから戻らなかったため、停止扱いにしました。もう一度お試しください。",
        f"OpenAI APIの応答が{format_elapsed_seconds(elapsed_seconds)}返りませんでした。通数を減らす、入力文を短くする、または少し時間を置いて再実行してください。",
    )
    log_ai_scenario_event("stale-timeout", f"elapsed={elapsed_seconds}s")


def render_ai_scenario_status(status_record: dict | None) -> None:
    if not isinstance(status_record, dict):
        return
    status_value = str(status_record.get("status") or "").strip()
    if not status_value or status_value == "idle":
        return
    status_at = format_jst_datetime(str(status_record.get("at") or "")) or "-"
    status_message = str(status_record.get("message") or "").strip()
    status_detail = str(status_record.get("detail") or "").strip()
    if status_value == "running":
        elapsed_seconds = ai_scenario_status_age_seconds(status_record)
        progress_value = min(95, max(10, int((elapsed_seconds / AI_SCENARIO_EXPECTED_SECONDS) * 85) + 10))
        st.info(
            "AIでシナリオ案を作成しています。"
            f"\n\n経過: {format_elapsed_seconds(elapsed_seconds)} / 目安: 30秒〜75秒"
            "\n\n75秒を超える場合は、OpenAI API側の混雑や入力文量の多さで戻っていない可能性があります。"
        )
        st.progress(progress_value, text="生成中です。画面を閉じずにお待ちください。")
        return
    status_text = f"AI生成状態: {ai_scenario_status_label(status_value)}（{status_at}）"
    if status_message:
        status_text = f"{status_text}\n\n{status_message}"
    if status_value == "failed":
        st.error(status_text)
        if status_detail:
            st.caption(f"理由: {status_detail[:500]}")
    elif status_value == "generated":
        st.warning(status_text)
    elif status_value == "saved":
        st.success(status_text)


def ai_scenario_schema() -> dict:
    step_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "step_number": {"type": "integer"},
            "template_name": {"type": "string"},
            "purpose": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["step_number", "template_name", "purpose", "subject", "body"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "scenario_name": {"type": "string"},
            "strategy_summary": {"type": "string"},
            "target_persona": {"type": "string"},
            "offer_angle": {"type": "string"},
            "recommended_send_gap_days": {"type": "integer"},
            "steps": {
                "type": "array",
                "items": step_schema,
            },
            "risk_notes": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "scenario_name",
            "strategy_summary",
            "target_persona",
            "offer_angle",
            "recommended_send_gap_days",
            "steps",
            "risk_notes",
        ],
    }


def extract_openai_output_text(response: dict) -> str:
    direct_text = str(response.get("output_text") or "").strip()
    if direct_text:
        return direct_text
    chunks: list[str] = []
    for item in response.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"}:
                chunks.append(str(content.get("text") or ""))
    return "".join(chunks).strip()


def uploaded_image_to_data_url(uploaded_file) -> str:
    if not uploaded_file:
        return ""
    mime_type = str(getattr(uploaded_file, "type", "") or "image/png")
    raw = uploaded_file.getvalue()
    if len(raw) > AI_IMAGE_MAX_BYTES:
        raise RuntimeError("商品写真は8MB以下の画像にしてください。")
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def ai_input_image_reference(uploaded_file) -> str:
    return uploaded_image_to_data_url(uploaded_file)


def friendly_openai_error(detail: str, status_code: int = 0) -> str:
    message = detail.strip()
    try:
        payload = json.loads(detail)
        error = payload.get("error", {})
        message = str(error.get("message") or message)
    except Exception:
        pass
    if status_code == 401:
        return "OpenAI APIキーが正しくありません。Streamlit Secretsの[openai] api_keyを確認してください。"
    if status_code == 429:
        return "OpenAI APIの利用上限、または一時的な制限に達している可能性があります。少し時間を置いて再度試してください。"
    if status_code == 404:
        return "指定したOpenAIモデルが見つかりません。Streamlit Secretsの[openai] modelを確認してください。"
    return f"OpenAI APIエラー: {message[:260]}"


def generate_ai_scenario(
    scenario_name: str,
    product_name: str,
    product_url: str,
    product_info: str,
    persona_info: str,
    tone: str,
    step_count: int,
    image_reference: str = "",
) -> dict:
    api_key = openai_api_key()
    if not api_key:
        raise RuntimeError("OpenAI APIキーが未設定です。Streamlit Secretsの[openai] api_keyに追加してください。")

    model = openai_model()
    clean_step_count = max(1, min(10, int(step_count)))
    max_output_tokens = min(6500, 1800 + clean_step_count * 600)
    instructions = (
        "あなたは日本語のB2Bアウトリーチメールとステップ配信シナリオの設計者です。"
        "商品情報、ASPの紹介文、ペルソナ情報、必要に応じて商品画像を読み取り、"
        "YouTubeチャンネル運営者に送る自然で丁寧な営業シナリオを作成してください。"
        "必ずJSON Schemaに従って出力します。"
        "各メール本文はプレーンテキストで、HTMLやMarkdownは使いません。"
        "チャンネル名の差し込みには必ず ${channel} を使ってください。"
        "成果保証、断定的な収益表現、誇大表現、虚偽の実績、相手を不安にさせすぎる表現は避けてください。"
        "薬機法・景表法・金融/健康/稼げる系のリスクがありそうな場合は、risk_notesに注意点を書いてください。"
        "配信停止URLはアプリが自動付与するため、本文にはURLを入れないでください。"
    )
    user_text = f"""
希望するシナリオ名:
{scenario_name.strip() or "未指定"}

商品名:
{product_name.strip()}

アフィリエイトURL:
{product_url.strip() or "未指定"}

商品・商材情報:
{product_info.strip()}

ASP紹介文・ペルソナ・訴求情報:
{persona_info.strip() or "未指定"}

希望する文体:
{tone}

作成するステップ数:
{clean_step_count}

出力条件:
- 希望するシナリオ名が指定されている場合、scenario_nameは必ずその名前をそのまま使う
- 希望するシナリオ名が未指定の場合、scenario_nameは商品名が分かる短い名前にする
- stepsは必ず{clean_step_count}件作る
- template_nameは各ステップで重複しない名前にする
- subjectは自然な日本語で、釣りすぎない
- bodyは1通ごとに目的が違う内容にする
- bodyは1通あたり500文字以内で、短く読みやすくする
- 1通目は突然の連絡として自然に入る
- 後続メールは前回連絡への補足として自然につなげる
- 相手がYouTubeチャンネル運営者である前提で書く
""".strip()

    content: list[dict] = [{"type": "input_text", "text": user_text}]
    if image_reference:
        content.append({"type": "input_image", "image_url": image_reference, "detail": "auto"})

    payload = {
        "model": model,
        "instructions": instructions,
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "outreach_scenario",
                "schema": ai_scenario_schema(),
                "strict": True,
            }
        },
        "max_output_tokens": max_output_tokens,
    }
    if model.startswith("gpt-5"):
        payload["reasoning"] = {"effort": "minimal"}
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=AI_OPENAI_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(friendly_openai_error(detail, exc.code)) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError(
            f"OpenAI APIから{AI_OPENAI_TIMEOUT_SECONDS}秒以内に応答が返りませんでした。"
            "通数を減らす、入力文を短くする、または少し時間を置いて再度お試しください。"
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", "")
        if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
            raise RuntimeError(
                f"OpenAI APIから{AI_OPENAI_TIMEOUT_SECONDS}秒以内に応答が返りませんでした。"
                "通数を減らす、入力文を短くする、または少し時間を置いて再度お試しください。"
            ) from exc
        raise RuntimeError(f"OpenAI APIに接続できませんでした: {exc.reason}") from exc

    output_text = extract_openai_output_text(result)
    if not output_text:
        raise RuntimeError("OpenAIからシナリオ本文を取得できませんでした。入力内容を少し短くして再度試してください。")
    try:
        scenario = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenAIの出力をシナリオとして読み取れませんでした。もう一度生成してください。") from exc
    steps = scenario.get("steps") or []
    if not isinstance(steps, list) or not steps:
        raise RuntimeError("シナリオのステップが生成されませんでした。入力内容を増やして再度試してください。")
    if scenario_name.strip():
        scenario["scenario_name"] = scenario_name.strip()
    return scenario


def campaign_template_list_key(names: list[str]) -> str:
    digest = hashlib.sha1("|".join(names).encode("utf-8")).hexdigest()[:10]
    return f"campaign_template_sort_{digest}"


def fetch_scenarios() -> list[sqlite3.Row]:
    return rows(
        """
        select id, name, created_at, updated_at
        from scenarios
        where user_id = ?
        order by id asc
        """,
        (current_user_id(),),
    )


def fetch_scenario_steps(scenario_id: int) -> list[sqlite3.Row]:
    return rows(
        """
        select id, scenario_id, step_number, template_name
        from scenario_steps
        where user_id = ? and scenario_id = ?
        order by step_number asc, id asc
        """,
        (current_user_id(), int(scenario_id)),
    )


def fetch_template_names_used_in_scenarios(exclude_scenario_id: int | None = None) -> set[str]:
    params: list[object] = [current_user_id()]
    exclude_clause = ""
    if exclude_scenario_id is not None:
        exclude_clause = "and scenario_id != ?"
        params.append(int(exclude_scenario_id))
    return {
        str(row["template_name"]).strip()
        for row in rows(
            f"""
            select distinct template_name
            from scenario_steps
            where user_id = ? and template_name != ''
            {exclude_clause}
            """,
            tuple(params),
        )
        if str(row["template_name"]).strip()
    }


def save_scenario(name: str, template_names: list[str]) -> int | None:
    clean_name = name.strip()
    clean_templates = [template.strip() for template in template_names if template.strip()]
    if not clean_name or not clean_templates:
        return None
    existing = rows(
        "select id from scenarios where user_id = ? and name = ? limit 1",
        (current_user_id(), clean_name),
    )
    if existing:
        scenario_id = int(existing[0]["id"])
        execute(
            "update scenarios set updated_at = ? where user_id = ? and id = ?",
            (now_iso(), current_user_id(), scenario_id),
        )
    else:
        execute(
            "insert into scenarios(user_id, name, created_at, updated_at) values (?, ?, ?, ?)",
            (current_user_id(), clean_name, now_iso(), now_iso()),
        )
        scenario_id = int(
            rows(
                "select id from scenarios where user_id = ? and name = ? order by id desc limit 1",
                (current_user_id(), clean_name),
            )[0]["id"]
        )
    execute("delete from scenario_steps where user_id = ? and scenario_id = ?", (current_user_id(), scenario_id))
    for index, template_name in enumerate(clean_templates, start=1):
        execute(
            """
            insert into scenario_steps(user_id, scenario_id, step_number, template_name)
            values (?, ?, ?, ?)
            """,
            (current_user_id(), scenario_id, index, template_name),
        )
    return scenario_id


def delete_scenario(scenario_id: int) -> None:
    execute("delete from scenario_steps where user_id = ? and scenario_id = ?", (current_user_id(), int(scenario_id)))
    execute("delete from scenarios where user_id = ? and id = ?", (current_user_id(), int(scenario_id)))


def scenario_step_campaign_name(scenario_name: str, step_number: int, template_name: str) -> str:
    return f"{scenario_name}｜{int(step_number)}通目 {template_name}"


def scenario_step_campaign_key(scenario_id: int, step_number: int) -> str:
    return campaign_key(f"scenario:{int(scenario_id)}:step:{int(step_number)}")


def unsubscribe_reason(scope: str, scope_key: str) -> str:
    clean_scope = str(scope or UNSUBSCRIBE_SCOPE_CAMPAIGN).strip() or UNSUBSCRIBE_SCOPE_CAMPAIGN
    clean_key = str(scope_key or "").strip()
    if clean_scope == UNSUBSCRIBE_SCOPE_GLOBAL:
        return UNSUBSCRIBE_REASON_GLOBAL
    return f"{UNSUBSCRIBE_REASON_PREFIX}{clean_scope}:{clean_key}"


def parse_unsubscribe_reason(reason: str) -> tuple[str, str]:
    clean_reason = str(reason or "").strip()
    if clean_reason in {"配信停止URL", UNSUBSCRIBE_REASON_GLOBAL}:
        return UNSUBSCRIBE_SCOPE_GLOBAL, UNSUBSCRIBE_SCOPE_GLOBAL
    if clean_reason.startswith(UNSUBSCRIBE_REASON_PREFIX):
        payload = clean_reason[len(UNSUBSCRIBE_REASON_PREFIX) :]
        scope, _, scope_key = payload.partition(":")
        if scope in {UNSUBSCRIBE_SCOPE_GLOBAL, UNSUBSCRIBE_SCOPE_SCENARIO, UNSUBSCRIBE_SCOPE_CAMPAIGN}:
            return scope, scope_key or (UNSUBSCRIBE_SCOPE_GLOBAL if scope == UNSUBSCRIBE_SCOPE_GLOBAL else "")
    return "", ""


def normal_campaign_scope_label(name: str) -> str:
    return str(name or "").strip() or "この配信"


def scope_display_label(scope: str, scope_key: str, scope_label: str = "") -> str:
    clean_scope = str(scope or "").strip()
    clean_key = str(scope_key or "").strip()
    clean_label = str(scope_label or "").strip()
    if clean_scope == UNSUBSCRIBE_SCOPE_GLOBAL:
        return "すべての案内"
    if clean_scope == UNSUBSCRIBE_SCOPE_SCENARIO:
        return f"シナリオ: {clean_label or clean_key or '-'}"
    if clean_scope == UNSUBSCRIBE_SCOPE_CAMPAIGN:
        return f"配信: {clean_label or clean_key or '-'}"
    return clean_label or "-"


def unsubscribe_scope_kind_label(scope: str) -> str:
    clean_scope = str(scope or "").strip()
    if clean_scope == UNSUBSCRIBE_SCOPE_GLOBAL:
        return "すべて停止"
    if clean_scope == UNSUBSCRIBE_SCOPE_SCENARIO:
        return "シナリオ停止"
    if clean_scope == UNSUBSCRIBE_SCOPE_CAMPAIGN:
        return "配信停止"
    return "不明"


def campaign_keys_for_unsubscribe_scope(scope: str, scope_key: str) -> list[str]:
    clean_scope = str(scope or "").strip()
    clean_key = str(scope_key or "").strip()
    if clean_scope == UNSUBSCRIBE_SCOPE_GLOBAL:
        return []
    if clean_scope == UNSUBSCRIBE_SCOPE_CAMPAIGN:
        return [clean_key] if clean_key else []
    if clean_scope == UNSUBSCRIBE_SCOPE_SCENARIO and clean_key:
        scenario = rows(
            "select id from scenarios where user_id = ? and name = ? limit 1",
            (current_user_id(), clean_key),
        )
        if not scenario:
            return []
        return [
            scenario_step_campaign_key(int(scenario[0]["id"]), int(step["step_number"]))
            for step in fetch_scenario_steps(int(scenario[0]["id"]))
        ]
    return []


def change_candidate_page(delta: int, total_pages: int) -> None:
    current_page = int(st.session_state.get("candidates_page", 1))
    st.session_state["candidates_page"] = max(1, min(int(total_pages), current_page + int(delta)))
    st.session_state["scroll_to_candidates_top"] = True
    st.session_state["scroll_to_candidates_nonce"] = int(st.session_state.get("scroll_to_candidates_nonce", 0)) + 1


def ensure_default_campaign_template() -> None:
    execute("delete from campaign_templates where user_id = ? and name = ?", (current_user_id(), "2通目"))
    deleted_defaults = {
        item.strip()
        for item in get_setting("DELETED_DEFAULT_CAMPAIGN_TEMPLATES", "").split("|")
        if item.strip()
    }
    existing_names = {template["name"] for template in fetch_campaign_templates()}
    for name, subject, body in DEFAULT_CAMPAIGN_TEMPLATES:
        if name in deleted_defaults:
            continue
        if name not in existing_names:
            save_campaign_template(name, subject, body)
    if not get_setting("CURRENT_CAMPAIGN_NAME"):
        save_setting("CURRENT_CAMPAIGN_NAME", DEFAULT_CAMPAIGN_NAME)


def load_campaign_template_into_session(template_name: str) -> bool:
    template = get_campaign_template(template_name)
    if not template:
        return False
    st.session_state["campaign_name_input"] = template["name"]
    st.session_state["subject_template_input"] = template["subject"]
    st.session_state["body_template_input"] = template["body"]
    st.session_state["loaded_campaign_template"] = template["name"]
    return True


def reset_campaign_template_session(name: str, subject: str, body: str) -> None:
    st.session_state["campaign_name_input"] = name
    st.session_state["subject_template_input"] = subject
    st.session_state["body_template_input"] = body
    st.session_state["loaded_campaign_template"] = name


def block_target(email: str = "", youtube_channel_id: str = "", channel: str = "", reason: str = "") -> None:
    normalized_email = email.strip().lower()
    channel_id = youtube_channel_id.strip()
    if not normalized_email and not channel_id:
        return
    duplicate = rows(
        """
        select id from blocked_targets
        where user_id = ? and ((email != '' and email = ?) or (youtube_channel_id != '' and youtube_channel_id = ?))
        """,
        (current_user_id(), normalized_email, channel_id),
    )
    if duplicate:
        return
    execute(
        """
        insert into blocked_targets(user_id, email, youtube_channel_id, channel, reason, created_at)
        values (?, ?, ?, ?, ?, ?)
        """,
        (current_user_id(), normalized_email, channel_id, channel.strip(), reason, now_iso()),
    )


def is_blocked(email: str = "", youtube_channel_id: str = "") -> bool:
    normalized_email = email.strip().lower()
    channel_id = youtube_channel_id.strip()
    if not normalized_email and not channel_id:
        return False
    return bool(
        rows(
            """
            select id from blocked_targets
            where user_id = ? and ((email != '' and email = ?) or (youtube_channel_id != '' and youtube_channel_id = ?))
            """,
            (current_user_id(), normalized_email, channel_id),
        )
    )


def blocked_target_reason(email: str = "", youtube_channel_id: str = "") -> str:
    normalized_email = email.strip().lower()
    channel_id = youtube_channel_id.strip()
    if not normalized_email and not channel_id:
        return ""
    result = rows(
        """
        select reason from blocked_targets
        where user_id = ? and ((email != '' and email = ?) or (youtube_channel_id != '' and youtube_channel_id = ?))
        order by id desc
        limit 1
        """,
        (current_user_id(), normalized_email, channel_id),
    )
    return str(result[0]["reason"] or "") if result else ""


def unblock_target(email: str = "", youtube_channel_id: str = "") -> None:
    normalized_email = email.strip().lower()
    channel_id = youtube_channel_id.strip()
    if not normalized_email and not channel_id:
        return
    execute(
        """
        delete from blocked_targets
        where user_id = ? and ((email != '' and email = ?) or (youtube_channel_id != '' and youtube_channel_id = ?))
        """,
        (current_user_id(), normalized_email, channel_id),
    )


def unblock_target_by_id(blocked_id: int) -> None:
    blocked = rows(
        "select email, youtube_channel_id from blocked_targets where user_id = ? and id = ?",
        (current_user_id(), int(blocked_id)),
    )
    if blocked:
        unblock_target(str(blocked[0]["email"] or ""), str(blocked[0]["youtube_channel_id"] or ""))
    execute("delete from blocked_targets where user_id = ? and id = ?", (current_user_id(), int(blocked_id)))


def restore_blocked_target_by_id(blocked_id: int) -> tuple[bool, str]:
    blocked = rows(
        "select email, youtube_channel_id, channel from blocked_targets where user_id = ? and id = ?",
        (current_user_id(), int(blocked_id)),
    )
    if not blocked:
        return False, "除外データが見つかりませんでした。"

    item = blocked[0]
    email = str(item["email"] or "").strip().lower()
    youtube_channel_id = str(item["youtube_channel_id"] or "").strip()
    channel = str(item["channel"] or "").strip()

    already_registered = (email and contact_exists(email)) or (
        youtube_channel_id and youtube_channel_in_contacts(youtube_channel_id)
    )
    unblock_target(email, youtube_channel_id)

    if already_registered:
        return True, "すでに宛先一覧にあるため、除外だけ解除しました。"

    restored = add_contact(
        email=email,
        memo="",
        channel=channel or "名称未設定",
        consent=True,
        youtube_channel_id=youtube_channel_id,
    )
    if restored:
        return True, "除外を解除し、宛先一覧に戻しました。"
    return False, "除外は解除しましたが、宛先一覧への復元はできませんでした。メールアドレスやチャンネルの重複を確認してください。"


def cleanup_blocked_targets_for_existing_contacts() -> None:
    execute(
        """
        delete from blocked_targets
        where user_id = ?
          and (
              (email != '' and email in (
                  select lower(email)
                  from contacts
                  where user_id = ? and email != ''
              ))
              or
              (youtube_channel_id != '' and youtube_channel_id in (
                  select youtube_channel_id
                  from contacts
                  where user_id = ? and youtube_channel_id != ''
              ))
          )
        """,
        (current_user_id(), current_user_id(), current_user_id()),
    )


def delete_contact(contact_id: int, block: bool = False, reason: str = "") -> None:
    if block:
        contact = rows("select * from contacts where user_id = ? and id = ?", (current_user_id(), contact_id))
        if contact:
            item = contact[0]
            block_target(item["email"], item["youtube_channel_id"], item["channel"], reason)
    execute("delete from sends where user_id = ? and contact_id = ?", (current_user_id(), contact_id))
    execute("delete from contacts where user_id = ? and id = ?", (current_user_id(), contact_id))


def delete_candidate(candidate_id: int) -> None:
    execute("delete from youtube_candidates where user_id = ? and id = ?", (current_user_id(), candidate_id))


def delete_candidate_and_block(candidate_id: int, reason: str = "YouTube候補から削除") -> None:
    candidate = rows(
        """
        select email, channel_id, title
        from youtube_candidates
        where user_id = ? and id = ?
        limit 1
        """,
        (current_user_id(), int(candidate_id)),
    )
    if candidate:
        block_target(
            str(candidate[0]["email"] or ""),
            str(candidate[0]["channel_id"] or ""),
            str(candidate[0]["title"] or ""),
            reason,
        )
    delete_candidate(candidate_id)


def save_candidate_from_contact(contact_id: int) -> tuple[bool, str]:
    contact = rows("select * from contacts where user_id = ? and id = ?", (current_user_id(), contact_id))
    if not contact:
        return False, "宛先が見つかりません"
    item = contact[0]
    channel_id = item["youtube_channel_id"]
    if not channel_id:
        return False, "この宛先はYouTube候補から登録されたものではありません"
    if youtube_channel_in_candidates(channel_id):
        execute(
            """
            update youtube_candidates
            set email = case when email = '' then ? else email end
            where user_id = ? and channel_id = ?
            """,
            (item["email"], current_user_id(), channel_id),
        )
        delete_contact(contact_id)
        return True, "すでに候補一覧にあるため、宛先一覧からだけ削除しました"

    execute(
        """
        insert into youtube_candidates
        (user_id, channel_id, email, title, channel_url, subscriber_count, video_count, view_count, description, keyword, created_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            current_user_id(),
            channel_id,
            item["email"],
            item["channel"],
            item["youtube_channel_url"] or f"https://www.youtube.com/channel/{channel_id}",
            int(item["youtube_subscriber_count"]),
            int(item["youtube_video_count"]),
            int(item["youtube_view_count"]),
            item["youtube_description"],
            item["youtube_keyword"],
            now_iso(),
        ),
    )
    delete_contact(contact_id)
    return True, "YouTube候補一覧に戻しました"


def contact_exists(email: str) -> bool:
    normalized_email = email.strip().lower()
    if not normalized_email:
        return False
    return bool(rows("select id from contacts where user_id = ? and email = ?", (current_user_id(), normalized_email)))


def candidate_contact_exists(channel: str) -> bool:
    normalized_channel = channel.strip()
    if not normalized_channel:
        return False
    return bool(rows("select id from contacts where user_id = ? and email = '' and channel = ?", (current_user_id(), normalized_channel)))


def youtube_channel_in_contacts(channel_id: str) -> bool:
    if not channel_id:
        return False
    return bool(rows("select id from contacts where user_id = ? and youtube_channel_id = ?", (current_user_id(), channel_id)))


def youtube_channel_in_candidates(channel_id: str) -> bool:
    if not channel_id:
        return False
    return bool(rows("select id from youtube_candidates where user_id = ? and channel_id = ?", (current_user_id(), channel_id)))


def find_candidate_for_import(
    candidate_id: str = "",
    channel_id: str = "",
    channel_url: str = "",
    channel: str = "",
) -> sqlite3.Row | None:
    normalized_candidate_id = str(candidate_id or "").strip()
    if re.fullmatch(r"\d+(?:\.0+)?", normalized_candidate_id):
        found = rows(
            "select * from youtube_candidates where user_id = ? and id = ?",
            (current_user_id(), int(float(normalized_candidate_id))),
        )
        if found:
            return found[0]

    normalized_channel_id = str(channel_id or "").strip()
    if normalized_channel_id:
        found = rows(
            "select * from youtube_candidates where user_id = ? and channel_id = ?",
            (current_user_id(), normalized_channel_id),
        )
        if found:
            return found[0]

    normalized_url = str(channel_url or "").strip()
    if normalized_url:
        found = rows(
            "select * from youtube_candidates where user_id = ? and channel_url = ?",
            (current_user_id(), normalized_url),
        )
        if found:
            return found[0]

    normalized_channel = str(channel or "").strip()
    if normalized_channel:
        found = rows(
            """
            select *
            from youtube_candidates
            where user_id = ? and title = ?
            order by id desc
            limit 2
            """,
            (current_user_id(), normalized_channel),
        )
        if len(found) == 1:
            return found[0]
    return None


def update_contact(contact_id: int, email: str, memo: str, channel: str, consent: bool, contact_status: str) -> tuple[bool, str]:
    normalized_email = email.strip().lower()
    clean_status = contact_status if contact_status in CONTACT_STATUS_OPTIONS else "送信対象"
    duplicate = rows(
        "select id from contacts where user_id = ? and email = ? and id != ?",
        (current_user_id(), normalized_email, contact_id),
    ) if normalized_email else []
    if duplicate:
        return False, "このメールアドレスはすでに登録されています"
    execute(
        """
        update contacts
        set email = ?, memo = ?, channel = ?, consent = ?, contact_status = ?
        where user_id = ? and id = ?
        """,
        (normalized_email, memo.strip(), channel.strip(), 1 if consent else 0, clean_status, current_user_id(), contact_id),
    )
    return True, "宛先を更新しました"


def mark_contact_replied(contact_id: int) -> None:
    execute(
        """
        update contacts
        set contact_status = '返信あり', replied_at = ?
        where user_id = ? and id = ?
        """,
        (now_iso(), current_user_id(), int(contact_id)),
    )


def set_contact_status(contact_id: int, contact_status: str) -> None:
    clean_status = contact_status if contact_status in CONTACT_STATUS_OPTIONS else "送信対象"
    execute(
        """
        update contacts
        set contact_status = ?
        where user_id = ? and id = ?
        """,
        (clean_status, current_user_id(), int(contact_id)),
    )


class YouTubeApiNotFoundError(RuntimeError):
    pass


def youtube_api_error_message(status_code: int, detail: str) -> str:
    message = detail.strip()
    reason = ""
    try:
        payload = json.loads(detail)
        error = payload.get("error", {})
        message = str(error.get("message") or message)
        errors = error.get("errors") or []
        if errors:
            reason = str(errors[0].get("reason") or "")
        else:
            reason = str(error.get("status") or "")
    except Exception:
        pass

    if status_code == 404:
        return (
            "YouTube側で対象が見つかりませんでした。"
            "カテゴリー検索の場合は、別カテゴリーまたはキーワード検索を試してください。"
        )
    if status_code == 403 and reason in {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
        return "YouTube APIの上限に達している可能性があります。時間を置くか、取得件数を減らしてください。"
    if status_code == 400:
        return "YouTube APIの検索条件が正しくありません。キーワードやカテゴリーを変えて再度試してください。"
    return f"YouTube APIエラー: HTTP {status_code} {message[:220]}"


def youtube_api_get(path: str, params: dict[str, str | int]) -> dict:
    api_key = get_secret("YOUTUBE_API_KEY", "")
    if not api_key:
        raise RuntimeError("YouTube APIキーが未設定です")
    query = urllib.parse.urlencode({**params, "key": api_key})
    url = f"https://www.googleapis.com/youtube/v3/{path}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        message = youtube_api_error_message(exc.code, detail)
        if exc.code == 404:
            raise YouTubeApiNotFoundError(message) from exc
        raise RuntimeError(message) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"YouTube APIに接続できませんでした: {exc.reason}") from exc


def save_candidate(candidate: dict, keyword: str) -> bool:
    channel_id = candidate["channel_id"]
    if is_blocked(youtube_channel_id=channel_id):
        return False
    if youtube_channel_in_contacts(channel_id) or youtube_channel_in_candidates(channel_id):
        return False
    execute(
        """
        insert or ignore into youtube_candidates
        (user_id, channel_id, email, title, channel_url, subscriber_count, video_count, view_count, description, keyword, created_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            current_user_id(),
            channel_id,
            candidate.get("email", ""),
            candidate["title"],
            candidate["channel_url"],
            int(candidate.get("subscriber_count", 0)),
            int(candidate.get("video_count", 0)),
            int(candidate.get("view_count", 0)),
            candidate.get("description", ""),
            keyword,
            now_iso(),
        ),
    )
    return True


def search_youtube_channels(
    keyword: str,
    min_subs: int,
    max_subs: int,
    max_results: int,
    search_mode: str = "キーワード",
    category_id: str = "",
    display_label: str = "",
) -> tuple[int, int, int]:
    found = 0
    saved = 0
    units_used = 0
    page_token = ""
    max_results = max(1, min(max_results, 200))
    max_pages = max(1, (max_results + 49) // 50)
    checked_pages = 0
    candidate_label = display_label or keyword

    while found < max_results and checked_pages < max_pages:
        checked_pages += 1
        if search_mode == "カテゴリー":
            units_used += 1
            try:
                video_data = youtube_api_get(
                    "videos",
                    {
                        "part": "snippet",
                        "chart": "mostPopular",
                        "regionCode": "JP",
                        "videoCategoryId": category_id,
                        "maxResults": min(50, max_results - found),
                        "pageToken": page_token,
                    },
                )
            except YouTubeApiNotFoundError:
                break
            keyword_filter = keyword.strip().lower()
            raw_channel_ids = []
            for item in video_data.get("items", []):
                snippet = item.get("snippet", {})
                searchable_text = " ".join(
                    [
                        snippet.get("title", ""),
                        snippet.get("channelTitle", ""),
                        snippet.get("description", ""),
                    ]
                ).lower()
                if keyword_filter and keyword_filter not in searchable_text:
                    continue
                channel_id = snippet.get("channelId", "")
                if channel_id:
                    raw_channel_ids.append(channel_id)
            page_token = video_data.get("nextPageToken", "")
        else:
            units_used += 100
            search_params = {
                "part": "snippet",
                "maxResults": min(50, max_results - found),
                "pageToken": page_token,
                "type": "channel",
                "q": keyword,
            }
            try:
                search_data = youtube_api_get(
                    "search",
                    search_params,
                )
            except YouTubeApiNotFoundError:
                break
            raw_channel_ids = [
                item["snippet"]["channelId"]
                for item in search_data.get("items", [])
                if item.get("snippet", {}).get("channelId")
            ]
            page_token = search_data.get("nextPageToken", "")

        channel_ids = list(dict.fromkeys(raw_channel_ids))
        if not channel_ids:
            if page_token:
                continue
            break

        units_used += 1
        try:
            channel_data = youtube_api_get(
                "channels",
                {
                    "part": "snippet,statistics",
                    "id": ",".join(channel_ids),
                    "maxResults": 50,
                },
            )
        except YouTubeApiNotFoundError:
            if page_token:
                continue
            break

        for item in channel_data.get("items", []):
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            subscriber_count = int(stats.get("subscriberCount", 0))
            if subscriber_count < min_subs:
                continue
            if max_subs and subscriber_count > max_subs:
                continue

            channel_id = item["id"]
            was_saved = save_candidate(
                {
                    "channel_id": channel_id,
                    "title": snippet.get("title", ""),
                    "channel_url": f"https://www.youtube.com/channel/{channel_id}",
                    "subscriber_count": subscriber_count,
                    "video_count": int(stats.get("videoCount", 0)),
                    "view_count": int(stats.get("viewCount", 0)),
                    "description": snippet.get("description", ""),
                },
                candidate_label,
            )
            if was_saved:
                saved += 1

        found += len(channel_ids)
        if not page_token:
            break

    add_youtube_units(units_used)
    return found, saved, units_used


def rows(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        return list(db.execute(query, params))


def smtp_configured() -> bool:
    account = active_smtp_account()
    return all(
        str(account.get(key) or "").strip()
        for key in ["smtp_host", "smtp_port", "sender_email", "smtp_pass"]
    )


def friendly_smtp_error(raw_error: str) -> str:
    message = str(raw_error or "").strip()
    lower = message.lower()
    reasons = []

    if "535" in lower or "authentication failed" in lower or "authentication unsuccessful" in lower:
        reasons.extend(
            [
                "SMTP認証に失敗しています。送信元メールアドレスとSMTPパスワードを確認してください。",
                "Xserverの場合、ユーザー名は基本的にメールアドレス全体です。例: noreply@example.com",
                "パスワード欄を空のまま保存すると、古い保存済みパスワードが使われます。変更したい場合は新しいパスワードを入力して保存してください。",
            ]
        )
    if "getaddrinfo" in lower or "name or service not known" in lower or "nodename" in lower:
        reasons.append("SMTPサーバー名が間違っている可能性があります。Xserverなら sv数字.xserver.jp の形式を確認してください。")
    if "timed out" in lower or "connection refused" in lower or "network is unreachable" in lower:
        reasons.extend(
            [
                "SMTPサーバーまたはポート番号に接続できていません。",
                "587を使う場合はSSL接続をOFF、465を使う場合はSSL接続をONにしてください。",
            ]
        )
    if "wrong version number" in lower or "unknown protocol" in lower or "ssl" in lower and "wrong" in lower:
        reasons.append("SSL設定とポート番号の組み合わせが合っていない可能性があります。587はSSL OFF、465はSSL ONです。")
    if "starttls" in lower:
        reasons.append("STARTTLSの開始に失敗しています。587でSSL OFF、または465でSSL ONを試してください。")
    if "sender address rejected" in lower or "relay access denied" in lower or "553" in lower:
        reasons.append("送信元メールアドレスがSMTPアカウントと合っていない可能性があります。送信元メールアドレスとSMTPユーザーを同じメールアドレスにしてください。")
    if not reasons:
        reasons.extend(
            [
                "SMTP設定のどこかで接続または送信に失敗しています。",
                "まずは SMTPサーバー、ポート、SSL接続、送信元メールアドレス、SMTPパスワードを確認してください。",
            ]
        )

    bullet_list = "\n".join(f"- {reason}" for reason in reasons)
    return f"SMTP送信に失敗しました。\n\n考えられる原因と直し方:\n{bullet_list}\n\n実際のエラー:\n`{message}`"


def classify_send_failure(raw_error: str) -> tuple[str, str]:
    message = str(raw_error or "").strip()
    lower = message.lower()
    if not message:
        return "不明", "送信ログに詳しいエラーが残っていません。送信元設定と宛先を確認してください。"
    if "535" in lower or "authentication failed" in lower or "authentication unsuccessful" in lower:
        return "SMTP認証エラー", "送信元メールアドレス、SMTPパスワード、アプリパスワードを確認してください。"
    if "getaddrinfo" in lower or "name or service not known" in lower or "nodename" in lower:
        return "SMTPサーバー名エラー", "SMTPサーバー名が正しいか確認してください。Xserverなら sv数字.xserver.jp の形式です。"
    if "timed out" in lower or "connection refused" in lower or "network is unreachable" in lower:
        return "接続エラー", "SMTPサーバー、ポート番号、SSL設定の組み合わせを確認してください。"
    if "wrong version number" in lower or "unknown protocol" in lower or ("ssl" in lower and "wrong" in lower):
        return "SSL/ポート設定エラー", "587ならSSL OFF、465ならSSL ONにしてください。"
    if "starttls" in lower:
        return "STARTTLSエラー", "587でSSL OFF、または465でSSL ONを試してください。"
    if "sender address rejected" in lower or "relay access denied" in lower or "553" in lower:
        return "送信元アドレス不一致", "送信元メールアドレスとSMTPアカウントが同じメールか確認してください。"
    if "recipient address rejected" in lower or "user unknown" in lower or "mailbox unavailable" in lower or "550" in lower:
        return "宛先メールアドレス不正", "宛先が存在しない、または受信拒否の可能性があります。削除または確認してください。"
    if "quota" in lower or "rate limit" in lower or "too many" in lower or "daily" in lower or "421" in lower or "450" in lower or "451" in lower or "452" in lower:
        return "送信制限の可能性", "短時間に送りすぎた可能性があります。件数を減らすか、送信間隔を長くしてください。"
    if "spam" in lower or "blocked" in lower or "blacklist" in lower or "policy" in lower or "554" in lower:
        return "迷惑メール判定/ポリシー拒否", "本文、URL、送信頻度、送信元ドメインの信頼性を見直してください。"
    return "その他の送信エラー", "詳細エラーを確認し、SMTP設定・宛先・送信頻度を順番に確認してください。"


def check_smtp_login() -> tuple[bool, str]:
    if not smtp_configured():
        return False, "送信元メール設定が未完了です。SMTPサーバー、ポート、送信元メールアドレス、SMTPパスワードを入力してください。"

    account = active_smtp_account()
    host = str(account.get("smtp_host") or "")
    port = int(str(account.get("smtp_port") or "587"))
    use_ssl = int(account.get("smtp_ssl") or 0) == 1
    sender_email = str(account.get("sender_email") or "")
    smtp_pass = str(account.get("smtp_pass") or "")

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                smtp.login(sender_email, smtp_pass)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(sender_email, smtp_pass)
        return True, "SMTPログイン確認OK"
    except Exception as exc:
        return False, friendly_smtp_error(str(exc))


def render_template(
    text: str,
    contact: sqlite3.Row,
    unsubscribe_url: str,
    unsubscribe_all_url: str = "",
) -> str:
    values = {
        "name": contact["name"] or "ご担当者",
        "email": contact["email"],
        "channel": contact["channel"] or "貴チャンネル",
        "unsubscribe_url": unsubscribe_url,
        "unsubscribe_all_url": unsubscribe_all_url or unsubscribe_url,
    }
    return Template(text).safe_substitute(values)


def ensure_unsubscribe_link_template(body_template: str) -> str:
    has_scoped_url = "${unsubscribe_url}" in body_template
    has_global_url = "${unsubscribe_all_url}" in body_template
    if has_scoped_url and has_global_url:
        return body_template
    suffix = ""
    if not has_scoped_url:
        suffix += "\n\n不要な場合はこちらからこの案内だけ配信停止できます。\n${unsubscribe_url}"
    if not has_global_url:
        suffix += "\n\nすべての案内を停止する場合はこちらから配信停止できます。\n${unsubscribe_all_url}"
    return body_template.rstrip() + suffix


def build_unsubscribe_mailto(
    contact: sqlite3.Row,
    scope: str = UNSUBSCRIBE_SCOPE_CAMPAIGN,
    scope_key: str = "",
    scope_label: str = "",
) -> str:
    account = active_smtp_account()
    reply_to = get_secret("UNSUBSCRIBE_EMAIL", "") or str(account.get("sender_email") or "")
    subject = "配信停止希望"
    body = (
        "配信停止を希望します。\n\n"
        f"停止範囲: {scope_display_label(scope, scope_key, scope_label)}\n"
        f"対象メールアドレス: {contact['email']}\n"
        f"チャンネル名: {contact['channel'] or '-'}\n"
    )
    return f"mailto:{reply_to}?subject={quote(subject)}&body={quote(body)}"


def build_unsubscribe_url(
    contact: sqlite3.Row,
    scope: str = UNSUBSCRIBE_SCOPE_CAMPAIGN,
    scope_key: str = "",
    scope_label: str = "",
) -> str:
    clean_scope = str(scope or UNSUBSCRIBE_SCOPE_CAMPAIGN).strip() or UNSUBSCRIBE_SCOPE_CAMPAIGN
    clean_key = str(scope_key or "").strip()
    clean_label = str(scope_label or "").strip()
    if supabase_configured():
        base_url = supabase_config()["url"].rstrip("/")
        query = urllib.parse.urlencode(
            {
                "token": str(contact["token"]),
                "scope": clean_scope,
                "scope_key": clean_key,
                "scope_label": clean_label,
            },
            quote_via=urllib.parse.quote,
        )
        return f"{base_url}/functions/v1/unsubscribe?{query}"
    return build_unsubscribe_mailto(contact, clean_scope, clean_key, clean_label)


def build_global_unsubscribe_url(contact: sqlite3.Row) -> str:
    return build_unsubscribe_url(
        contact,
        UNSUBSCRIBE_SCOPE_GLOBAL,
        UNSUBSCRIBE_SCOPE_GLOBAL,
        "すべての案内",
    )


def register_unsubscribe_token(contact: sqlite3.Row, user_email: str) -> None:
    if not supabase_configured():
        return
    payload = {
        "user_email": user_email,
        "token": str(contact["token"]),
        "contact_local_id": int(contact["id"]),
        "contact_email": str(contact["email"] or "").strip().lower(),
        "youtube_channel_id": str(contact["youtube_channel_id"] or ""),
        "channel": str(contact["channel"] or ""),
        "updated_at": now_iso(),
    }
    supabase_request(
        "POST",
        "unsubscribe_tokens?on_conflict=token",
        payload,
        prefer="resolution=merge-duplicates,return=minimal",
    )


def register_unsubscribe_tokens(contacts: list[sqlite3.Row], user_email: str) -> None:
    if not supabase_configured() or not contacts:
        return
    token_rows = [
        {
            "user_email": user_email,
            "token": str(contact["token"]),
            "contact_local_id": int(contact["id"]),
            "contact_email": str(contact["email"] or "").strip().lower(),
            "youtube_channel_id": str(contact["youtube_channel_id"] or ""),
            "channel": str(contact["channel"] or ""),
            "updated_at": now_iso(),
        }
        for contact in contacts
    ]
    chunk_size = 500
    for index in range(0, len(token_rows), chunk_size):
        supabase_request(
            "POST",
            "unsubscribe_tokens?on_conflict=token",
            token_rows[index : index + chunk_size],
            prefer="resolution=merge-duplicates,return=minimal",
        )


def next_window_start(moment: datetime, window_start: datetime_time) -> datetime:
    return datetime.combine(moment.date() + timedelta(days=1), window_start, APP_TIMEZONE)


def align_to_send_window(moment: datetime, window_start: datetime_time, window_end: datetime_time) -> datetime:
    cursor = moment.astimezone(APP_TIMEZONE)
    day_start = datetime.combine(cursor.date(), window_start, APP_TIMEZONE)
    day_end = datetime.combine(cursor.date(), window_end, APP_TIMEZONE)
    if cursor < day_start:
        return day_start
    if cursor >= day_end:
        return next_window_start(cursor, window_start)
    return cursor


def build_send_schedule_from(
    send_count: int,
    delay_seconds: int,
    window_start: datetime_time,
    window_end: datetime_time,
    start_after: datetime | None = None,
) -> list[datetime]:
    if send_count <= 0 or window_end <= window_start:
        return []

    scheduled_times = []
    cursor = align_to_send_window(start_after or datetime.now(APP_TIMEZONE), window_start, window_end)

    for _ in range(send_count):
        day_end = datetime.combine(cursor.date(), window_end, APP_TIMEZONE)
        if cursor >= day_end:
            cursor = next_window_start(cursor, window_start)
        scheduled_times.append(cursor.astimezone(timezone.utc))
        cursor = cursor + timedelta(seconds=int(delay_seconds))

    return scheduled_times


def build_send_schedule(
    send_count: int,
    delay_seconds: int,
    window_start: datetime_time,
    window_end: datetime_time,
) -> list[datetime]:
    return build_send_schedule_from(send_count, delay_seconds, window_start, window_end)


def build_scenario_send_schedules(
    recipient_count: int,
    step_count: int,
    delay_seconds: int,
    window_start: datetime_time,
    window_end: datetime_time,
    step_gap_days: int,
) -> list[list[datetime]]:
    schedules: list[list[datetime]] = []
    if recipient_count <= 0 or step_count <= 0 or window_end <= window_start:
        return schedules

    start_after: datetime | None = datetime.now(APP_TIMEZONE)
    gap_days = max(1, int(step_gap_days))
    for _ in range(step_count):
        step_schedule = build_send_schedule_from(
            recipient_count,
            delay_seconds,
            window_start,
            window_end,
            start_after,
        )
        if len(step_schedule) != recipient_count:
            return []
        schedules.append(step_schedule)
        start_after = step_schedule[-1].astimezone(APP_TIMEZONE) + timedelta(days=gap_days)
    return schedules


def flatten_schedules(schedules: list[list[datetime]]) -> list[datetime]:
    return [scheduled_at for schedule in schedules for scheduled_at in schedule]


def schedule_calendar_days(schedule: list[datetime]) -> int:
    if not schedule:
        return 0
    first_day = schedule[0].astimezone(APP_TIMEZONE).date()
    last_day = schedule[-1].astimezone(APP_TIMEZONE).date()
    return max(1, (last_day - first_day).days + 1)


def send_window_seconds(window_start: datetime_time, window_end: datetime_time) -> int:
    if window_end <= window_start:
        return 0
    start_dt = datetime.combine(date.today(), window_start)
    end_dt = datetime.combine(date.today(), window_end)
    return max(0, int((end_dt - start_dt).total_seconds()))


def daily_send_capacity(window_start: datetime_time, window_end: datetime_time, delay_seconds: int) -> int:
    seconds = send_window_seconds(window_start, window_end)
    delay = max(1, int(delay_seconds))
    if seconds <= 0:
        return 0
    return ((seconds - 1) // delay) + 1


def delay_for_daily_target(window_start: datetime_time, window_end: datetime_time, daily_target: int) -> int:
    seconds = send_window_seconds(window_start, window_end)
    target = max(1, int(daily_target))
    if seconds <= 0:
        return 60
    return max(30, min(3600, math.ceil(seconds / target)))


def format_delay_seconds(delay_seconds: int) -> str:
    delay = max(1, int(delay_seconds))
    minutes, seconds = divmod(delay, 60)
    if minutes and seconds:
        return f"{minutes}分{seconds}秒"
    if minutes:
        return f"{minutes}分"
    return f"{seconds}秒"


def estimate_send_days(send_count: int, daily_capacity: int) -> int:
    if int(send_count) <= 0 or int(daily_capacity) <= 0:
        return 0
    return math.ceil(int(send_count) / int(daily_capacity))


def looks_like_email_address(value: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value.strip()))


def mask_email_address(value: str) -> str:
    email = value.strip()
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[:1] + "***"
    else:
        masked_local = local[:2] + "***"
    return f"{masked_local}@{domain}"


def format_local_datetime(value: datetime) -> str:
    return value.astimezone(APP_TIMEZONE).strftime("%Y-%m-%d %H:%M（日本時間）")


def smtp_account_configured(account: dict) -> bool:
    return all(
        str(account.get(key) or "").strip()
        for key in ["smtp_host", "smtp_port", "sender_email", "smtp_pass"]
    )


def smtp_account_uses_ssl(account: dict) -> bool:
    value = account.get("smtp_ssl")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def send_email_with_account(account: dict, to_email: str, subject: str, body: str) -> tuple[bool, str]:
    if not smtp_account_configured(account):
        return False, "送信元メール設定が未完了です。SMTPサーバー、ポート、送信元メールアドレス、SMTPパスワードを確認してください。"

    message = EmailMessage()
    message["From"] = smtp_mail_from(account)
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    host = str(account.get("smtp_host") or "")
    port = int(str(account.get("smtp_port") or "587"))
    use_ssl = smtp_account_uses_ssl(account)
    sender_email = str(account.get("sender_email") or "")
    smtp_pass = str(account.get("smtp_pass") or "")

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                smtp.login(sender_email, smtp_pass)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(sender_email, smtp_pass)
                smtp.send_message(message)
        return True, "送信しました"
    except Exception as exc:
        return False, friendly_smtp_error(str(exc))


def send_email(to_email: str, subject: str, body: str) -> tuple[bool, str]:
    if not smtp_configured():
        return True, "DRY_RUN: SMTP設定がないため実送信はしていません"
    return send_email_with_account(active_smtp_account(), to_email, subject, body)


def post_send_queue_rows(queue_rows: list[dict]) -> None:
    chunk_size = 500
    for index in range(0, len(queue_rows), chunk_size):
        supabase_request(
            "POST",
            "send_queue",
            queue_rows[index : index + chunk_size],
            prefer="return=minimal",
        )


def compact_error_message(error: object, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(error or "")).strip()[:limit]


def supabase_exact_count(path: str) -> int:
    config = supabase_config()
    base_url = config["url"].rstrip("/")
    url = f"{base_url}/rest/v1/{path.lstrip('/')}"
    request = urllib.request.Request(
        url,
        headers={
            "apikey": config["service_role_key"],
            "Authorization": f"Bearer {config['service_role_key']}",
            "Content-Type": "application/json",
            "Prefer": "count=exact",
            "Range-Unit": "items",
            "Range": "0-0",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        content_range = str(response.headers.get("Content-Range") or "")
    match = re.search(r"/(\d+|\*)$", content_range)
    if not match or match.group(1) == "*":
        return 0
    return int(match.group(1))


def count_send_queue_rows(job_id: str) -> int:
    if not supabase_configured() or not str(job_id or "").strip():
        return 0
    query_job_id = urllib.parse.quote(str(job_id), safe="")
    return supabase_exact_count(f"send_queue?job_id=eq.{query_job_id}&select=id")


def send_queue_has_rows(job_id: str) -> bool:
    if not supabase_configured() or not str(job_id or "").strip():
        return False
    query_job_id = urllib.parse.quote(str(job_id), safe="")
    result = supabase_request(
        "GET",
        f"send_queue?job_id=eq.{query_job_id}&select=id&limit=1",
    )
    return bool(isinstance(result, list) and result)


def mark_send_job_failed(job_id: str, error_message: str = "") -> None:
    if not supabase_configured() or not str(job_id or "").strip():
        return
    query_job_id = urllib.parse.quote(str(job_id), safe="")
    try:
        supabase_request(
            "DELETE",
            f"send_queue?job_id=eq.{query_job_id}",
            prefer="return=minimal",
        )
    except Exception:
        pass
    try:
        payload = {"status": "failed", "updated_at": now_iso()}
        supabase_request(
            "PATCH",
            f"send_jobs?id=eq.{query_job_id}",
            payload,
            prefer="return=minimal",
        )
    except Exception as exc:
        print(f"[send queue] failed-job-mark-error job={job_id} error={compact_error_message(exc)}", flush=True)
    if error_message:
        print(f"[send queue] failed-job job={job_id} error={compact_error_message(error_message)}", flush=True)


def finalize_send_queue_creation(job_id: str, queue_rows: list[dict]) -> tuple[bool, str]:
    if not queue_rows:
        mark_send_job_failed(job_id, "send queue is empty")
        return False, "送信予約の中身が空です。宛先とシナリオ設定を確認してください。"
    try:
        post_send_queue_rows(queue_rows)
        expected_count = len(queue_rows)
        created_count = count_send_queue_rows(job_id)
        if created_count != expected_count:
            mark_send_job_failed(job_id, f"send queue count mismatch: expected={expected_count} actual={created_count}")
            return (
                False,
                f"送信予約の中身を保存しきれませんでした（{created_count:,}/{expected_count:,}通）。"
                "中途半端な予約は失敗扱いにしました。もう一度予約を作り直してください。",
            )
        supabase_request(
            "PATCH",
            f"send_jobs?id=eq.{urllib.parse.quote(str(job_id), safe='')}",
            {"status": "queued", "total_count": created_count, "updated_at": now_iso()},
            prefer="return=minimal",
        )
        return True, ""
    except Exception as exc:
        mark_send_job_failed(job_id, exc)
        return (
            False,
            "送信予約の中身をクラウドへ保存できませんでした。中途半端な予約は失敗扱いにしました。"
            f"理由: {compact_error_message(exc, 220)}",
        )


def insert_queued_send_rows(send_rows: list[tuple]) -> None:
    if not send_rows:
        return
    with sqlite3.connect(DB_PATH) as db:
        db.executemany(
            """
            insert into sends(user_id, contact_id, campaign_key, send_job_id, subject, status, error, sent_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            send_rows,
        )
        db.commit()
    mark_app_state_dirty()


def create_send_job(
    campaign_name: str,
    campaign_key_value: str,
    subject_template: str,
    body_template: str,
    contacts: list[sqlite3.Row],
    delay_seconds: int,
    window_start: datetime_time,
    window_end: datetime_time,
    unsubscribe_scope: str = UNSUBSCRIBE_SCOPE_CAMPAIGN,
    unsubscribe_scope_key: str = "",
    unsubscribe_scope_label: str = "",
) -> tuple[bool, str]:
    if not supabase_configured():
        return False, "送信予約にはSupabase設定が必要です"
    account = active_smtp_account()
    if not smtp_configured():
        return False, "送信元メール設定が未完了です"
    smtp_ok, smtp_message = check_smtp_login()
    if not smtp_ok:
        return False, smtp_message
    schedule_times = build_send_schedule(len(contacts), int(delay_seconds), window_start, window_end)
    if len(schedule_times) != len(contacts):
        return False, "送信可能時間帯の設定を確認してください。終了時刻は開始時刻より後にしてください。"
    user_email = current_user_profile()["email"].strip().lower() or current_user_id()
    job_payload = {
        "user_email": user_email,
        "campaign_key": campaign_key_value,
        "campaign_name": campaign_name.strip(),
        "subject_template": subject_template,
        "body_template": ensure_unsubscribe_link_template(body_template),
        "sender_label": str(account.get("label") or ""),
        "sender_name": str(account.get("sender_name") or ""),
        "sender_email": str(account.get("sender_email") or ""),
        "smtp_host": str(account.get("smtp_host") or ""),
        "smtp_port": int(str(account.get("smtp_port") or "587")),
        "smtp_ssl": int(account.get("smtp_ssl") or 0) == 1,
        "smtp_pass": str(account.get("smtp_pass") or ""),
        "delay_seconds": int(delay_seconds),
        "total_count": len(contacts),
        "status": "creating",
        "updated_at": now_iso(),
    }
    created_job = supabase_request("POST", "send_jobs", job_payload, prefer="return=representation")
    if not isinstance(created_job, list) or not created_job:
        return False, "送信予約の作成に失敗しました"
    job_id = created_job[0]["id"]
    queue_rows = []
    register_unsubscribe_tokens(contacts, user_email)
    for index, contact in enumerate(contacts):
        unsubscribe_url = build_unsubscribe_url(
            contact,
            unsubscribe_scope,
            unsubscribe_scope_key or campaign_key_value,
            unsubscribe_scope_label or campaign_name,
        )
        unsubscribe_all_url = build_global_unsubscribe_url(contact)
        subject = render_template(subject_template, contact, unsubscribe_url)
        body = render_template(
            ensure_unsubscribe_link_template(body_template),
            contact,
            unsubscribe_url,
            unsubscribe_all_url,
        )
        queue_rows.append(
            {
                "job_id": job_id,
                "user_email": user_email,
                "campaign_key": campaign_key_value,
                "contact_local_id": int(contact["id"]),
                "contact_email": contact["email"],
                "contact_name": contact["name"],
                "contact_channel": contact["channel"],
                "subject": subject,
                "body": body,
                "status": "pending",
                "scheduled_at": schedule_times[index].isoformat(),
            }
        )
    ok, queue_message = finalize_send_queue_creation(str(job_id), queue_rows)
    if not ok:
        return False, queue_message
    queued_at = now_iso()
    insert_queued_send_rows(
        [
            (
                current_user_id(),
                row["contact_local_id"],
                campaign_key_value,
                str(job_id),
                row["subject"],
                "queued",
                "",
                queued_at,
            )
            for row in queue_rows
        ]
    )
    return True, f"{len(queue_rows)}件の送信予約を作成しました"


def create_scenario_full_send_job(
    scenario: sqlite3.Row,
    scenario_steps: list[sqlite3.Row],
    contacts: list[sqlite3.Row],
    delay_seconds: int,
    window_start: datetime_time,
    window_end: datetime_time,
    step_gap_days: int,
) -> tuple[bool, str]:
    if not supabase_configured():
        return False, "送信予約にはSupabase設定が必要です"
    if not smtp_configured():
        return False, "送信元メール設定が未完了です"
    smtp_ok, smtp_message = check_smtp_login()
    if not smtp_ok:
        return False, smtp_message
    if not contacts:
        return False, "送信できる宛先がありません"
    if not scenario_steps:
        return False, "このシナリオにはステップがありません"

    scenario_name = str(scenario["name"] or "").strip()
    prepared_steps: list[dict] = []
    for step in scenario_steps:
        template_name = str(step["template_name"] or "").strip()
        template = get_campaign_template(template_name)
        if not template:
            return False, f"{step['step_number']}通目のテンプレート「{template_name}」が見つかりません。"
        prepared_steps.append(
            {
                "step_number": int(step["step_number"]),
                "template_name": template_name,
                "campaign_key": scenario_step_campaign_key(int(scenario["id"]), int(step["step_number"])),
                "campaign_name": scenario_step_campaign_name(
                    scenario_name,
                    int(step["step_number"]),
                    template_name,
                ),
                "subject": str(template["subject"] or ""),
                "body": str(template["body"] or ""),
            }
        )

    step_schedules = build_scenario_send_schedules(
        len(contacts),
        len(prepared_steps),
        int(delay_seconds),
        window_start,
        window_end,
        int(step_gap_days),
    )
    if len(step_schedules) != len(prepared_steps):
        return False, "送信可能時間帯の設定を確認してください。終了時刻は開始時刻より後にしてください。"

    account = active_smtp_account()
    user_email = current_user_profile()["email"].strip().lower() or current_user_id()
    total_count = len(contacts) * len(prepared_steps)
    job_payload = {
        "user_email": user_email,
        "campaign_key": campaign_key(f"scenario-full:{int(scenario['id'])}"),
        "campaign_name": f"{scenario_name}｜シナリオ全体",
        "subject_template": prepared_steps[0]["subject"],
        "body_template": ensure_unsubscribe_link_template(prepared_steps[0]["body"]),
        "sender_label": str(account.get("label") or ""),
        "sender_name": str(account.get("sender_name") or ""),
        "sender_email": str(account.get("sender_email") or ""),
        "smtp_host": str(account.get("smtp_host") or ""),
        "smtp_port": int(str(account.get("smtp_port") or "587")),
        "smtp_ssl": int(account.get("smtp_ssl") or 0) == 1,
        "smtp_pass": str(account.get("smtp_pass") or ""),
        "delay_seconds": int(delay_seconds),
        "total_count": total_count,
        "status": "creating",
        "updated_at": now_iso(),
    }
    created_job = supabase_request("POST", "send_jobs", job_payload, prefer="return=representation")
    if not isinstance(created_job, list) or not created_job:
        return False, "送信予約の作成に失敗しました"
    job_id = str(created_job[0]["id"])

    queue_rows: list[dict] = []
    local_rows: list[tuple] = []
    queued_at = now_iso()
    register_unsubscribe_tokens(contacts, user_email)

    for step_index, step in enumerate(prepared_steps):
        for contact_index, contact in enumerate(contacts):
            unsubscribe_url = build_unsubscribe_url(
                contact,
                UNSUBSCRIBE_SCOPE_SCENARIO,
                scenario_name,
                scenario_name,
            )
            unsubscribe_all_url = build_global_unsubscribe_url(contact)
            subject = render_template(step["subject"], contact, unsubscribe_url)
            body = render_template(
                ensure_unsubscribe_link_template(step["body"]),
                contact,
                unsubscribe_url,
                unsubscribe_all_url,
            )
            queue_rows.append(
                {
                    "job_id": job_id,
                    "user_email": user_email,
                    "campaign_key": step["campaign_key"],
                    "contact_local_id": int(contact["id"]),
                    "contact_email": contact["email"],
                    "contact_name": contact["name"],
                    "contact_channel": contact["channel"],
                    "subject": subject,
                    "body": body,
                    "status": "pending",
                    "scheduled_at": step_schedules[step_index][contact_index].isoformat(),
                }
            )
            local_rows.append(
                (
                    current_user_id(),
                    int(contact["id"]),
                    step["campaign_key"],
                    job_id,
                    subject,
                    "queued",
                    "",
                    queued_at,
                )
            )

    ok, queue_message = finalize_send_queue_creation(job_id, queue_rows)
    if not ok:
        return False, queue_message
    insert_queued_send_rows(local_rows)
    return True, f"{len(contacts)}件の宛先に、{len(prepared_steps)}ステップ分（合計{total_count}通）の送信予約を作成しました"


def smtp_account_from_send_job(job: dict) -> dict:
    return {
        "sender_name": str(job.get("sender_name") or ""),
        "sender_email": str(job.get("sender_email") or ""),
        "smtp_host": str(job.get("smtp_host") or ""),
        "smtp_port": str(job.get("smtp_port") or "587"),
        "smtp_ssl": job.get("smtp_ssl"),
        "smtp_pass": str(job.get("smtp_pass") or ""),
    }


def update_send_queue_row_status(row_id: str, status: str, error: str = "") -> None:
    payload = {
        "status": status,
        "error": error,
        "updated_at": now_iso(),
    }
    if status == "sent":
        payload["sent_at"] = now_iso()
    supabase_request(
        "PATCH",
        f"send_queue?id=eq.{urllib.parse.quote(str(row_id), safe='')}",
        payload,
        prefer="return=minimal",
    )


def claim_send_queue_row(row_id: str) -> dict:
    claimed_rows = supabase_request(
        "PATCH",
        f"send_queue?id=eq.{urllib.parse.quote(str(row_id), safe='')}&status=eq.pending",
        {"status": "sending", "updated_at": now_iso()},
        prefer="return=representation",
    )
    if isinstance(claimed_rows, list) and claimed_rows:
        return claimed_rows[0]
    return {}


def recover_stale_sending_queue_rows(user_email: str) -> int:
    if not user_email:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STREAMLIT_SEND_QUEUE_STALE_SENDING_SECONDS)
    query_email = urllib.parse.quote(user_email, safe="")
    cutoff_value = urllib.parse.quote(cutoff.isoformat(timespec="seconds"), safe="")
    recovered = supabase_request(
        "PATCH",
        (
            "send_queue"
            f"?user_email=eq.{query_email}"
            "&status=eq.sending"
            f"&updated_at=lt.{cutoff_value}"
        ),
        {"status": "pending", "error": "", "updated_at": now_iso()},
        prefer="return=representation",
    )
    return len(recovered) if isinstance(recovered, list) else 0


def update_local_queued_send_result(item: dict, status: str, error: str, sent_at: str) -> None:
    contact_id = item.get("contact_local_id")
    campaign_key_value = str(item.get("campaign_key") or "")
    if not contact_id or not campaign_key_value:
        return
    send_job_id = str(item.get("job_id") or "")
    if send_job_id:
        execute(
            """
            update sends
            set status = ?, error = ?, sent_at = ?
            where user_id = ?
              and send_job_id = ?
              and contact_id = ?
              and campaign_key = ?
              and status = 'queued'
            """,
            (status, error, sent_at, current_user_id(), send_job_id, int(contact_id), campaign_key_value),
        )
    execute(
        """
        update sends
        set status = ?, error = ?, sent_at = ?
        where user_id = ?
          and contact_id = ?
          and campaign_key = ?
          and subject = ?
          and status = 'queued'
        """,
        (status, error, sent_at, current_user_id(), int(contact_id), campaign_key_value, str(item.get("subject") or "")),
    )


def process_due_send_queue_from_streamlit(force: bool = False) -> dict[str, int | bool]:
    result: dict[str, int | bool] = {"checked": False, "processed": 0, "failed": 0}
    if not supabase_configured():
        return result
    user_email = current_user_profile()["email"].strip().lower()
    if not user_email:
        return result

    now_epoch = time.time()
    last_checked = float(st.session_state.get("_send_queue_last_checked_at", 0) or 0)
    if not force and now_epoch - last_checked < STREAMLIT_SEND_QUEUE_MIN_INTERVAL_SECONDS:
        return result
    st.session_state["_send_queue_last_checked_at"] = now_epoch
    result["checked"] = True

    try:
        recovered_count = recover_stale_sending_queue_rows(user_email)
        if recovered_count:
            print(f"[send queue] recovered stale sending rows count={recovered_count}", flush=True)
        query_email = urllib.parse.quote(user_email, safe="")
        now_value = urllib.parse.quote(datetime.now(timezone.utc).isoformat(timespec="seconds"), safe="")
        due_rows = supabase_request(
            "GET",
            (
                "send_queue"
                f"?user_email=eq.{query_email}"
                "&status=eq.pending"
                f"&scheduled_at=lte.{now_value}"
                "&select=id,job_id,contact_local_id,campaign_key,contact_email,subject,body,scheduled_at"
                "&order=scheduled_at.asc"
                f"&limit={STREAMLIT_SEND_QUEUE_BATCH_SIZE}"
            ),
        )
    except Exception as exc:
        print(f"[send queue] fetch-failed error={exc}", flush=True)
        return result

    if not isinstance(due_rows, list) or not due_rows:
        return result

    affected_job_ids: set[str] = set()
    for item in due_rows:
        row_id = str(item.get("id") or "").strip()
        job_id = str(item.get("job_id") or "").strip()
        if not row_id or not job_id:
            continue
        claimed = False
        status = "failed"
        error = ""
        try:
            claimed_row = claim_send_queue_row(row_id)
            if not claimed_row:
                continue
            claimed = True

            query_job_id = urllib.parse.quote(job_id, safe="")
            jobs = supabase_request("GET", f"send_jobs?id=eq.{query_job_id}&select=*")
            if not isinstance(jobs, list) or not jobs:
                error = "送信予約の設定が見つかりませんでした。"
            else:
                to_email = str(item.get("contact_email") or "").strip()
                if not to_email:
                    error = "宛先メールアドレスが空です。"
                else:
                    ok, message = send_email_with_account(
                        smtp_account_from_send_job(jobs[0]),
                        to_email,
                        str(item.get("subject") or ""),
                        str(item.get("body") or ""),
                    )
                    status = "sent" if ok else "failed"
                    error = "" if ok else message

            processed_at = now_iso()
            update_send_queue_row_status(row_id, status, error)
            update_local_queued_send_result(item, status, error, processed_at)
            affected_job_ids.add(job_id)
            result["processed"] = int(result["processed"]) + 1
            if status == "failed":
                result["failed"] = int(result["failed"]) + 1
            print(
                f"[send queue] processed status={status} job={job_id} row={row_id} to={mask_email_address(str(item.get('contact_email') or ''))}",
                flush=True,
            )
        except Exception as exc:
            error = friendly_smtp_error(str(exc))
            if claimed and status != "sent":
                try:
                    update_send_queue_row_status(row_id, "failed", error)
                    update_local_queued_send_result(item, "failed", error, now_iso())
                    affected_job_ids.add(job_id)
                    result["processed"] = int(result["processed"]) + 1
                    result["failed"] = int(result["failed"]) + 1
                except Exception:
                    pass
            print(f"[send queue] process-failed job={job_id} row={row_id} error={exc}", flush=True)

    refresh_supabase_send_jobs(affected_job_ids)
    return result


def sync_send_queue_results() -> None:
    if not supabase_configured():
        return
    user_email = current_user_profile()["email"].strip().lower()
    if not user_email:
        return
    try:
        query_email = urllib.parse.quote(user_email, safe="")
        results = supabase_request(
            "GET",
            f"send_queue?user_email=eq.{query_email}&status=in.(sent,failed)&select=job_id,contact_local_id,campaign_key,status,error,sent_at,subject",
        )
        if not isinstance(results, list):
            return
        for item in results:
            sent_at = item.get("sent_at") or now_iso()
            status = item.get("status", "")
            error = item.get("error", "")
            update_local_queued_send_result(item, status, error, sent_at)
    except Exception:
        return


def send_job_status_label(status: str) -> str:
    return {
        "queued": "送信待ち",
        "pending": "送信待ち",
        "creating": "予約作成中",
        "sending": "送信中",
        "running": "送信中",
        "processing": "送信中",
        "completed": "完了",
        "done": "完了",
        "finished": "完了",
        "failed": "失敗",
        "canceled": "取消済み",
        "cancelled": "取消済み",
    }.get(str(status or "").lower(), str(status or "不明"))


def send_job_count(job: dict, key: str) -> int:
    try:
        return max(0, int(job.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def send_job_processed_count(job: dict) -> int:
    total_count = send_job_count(job, "total_count")
    processed_count = send_job_count(job, "sent_count") + send_job_count(job, "failed_count")
    return min(total_count, processed_count) if total_count else processed_count


def send_job_progress_percent(job: dict) -> float:
    total_count = send_job_count(job, "total_count")
    if total_count <= 0:
        return 0.0
    return min(100.0, round(send_job_processed_count(job) / total_count * 100, 1))


def send_job_success_percent(job: dict) -> float:
    total_count = send_job_count(job, "total_count")
    if total_count <= 0:
        return 0.0
    return min(100.0, round(send_job_count(job, "sent_count") / total_count * 100, 1))


def is_active_send_job(job: dict) -> bool:
    status = str(job.get("status") or "").lower()
    if status in {"canceled", "cancelled", "completed", "done", "finished", "failed"}:
        return False
    total_count = send_job_count(job, "total_count")
    return total_count <= 0 or send_job_processed_count(job) < total_count


def is_cancelable_send_job(job: dict) -> bool:
    return is_active_send_job(job)


def delete_local_queued_sends_for_job(send_job_id: str, queue_rows: list[dict]) -> int:
    deleted_count = 0
    with sqlite3.connect(DB_PATH) as db:
        for item in queue_rows:
            contact_id = int(item.get("contact_local_id") or 0)
            campaign_key_value = str(item.get("campaign_key") or "")
            subject = str(item.get("subject") or "")
            if not contact_id or not campaign_key_value:
                continue
            cursor = db.execute(
                """
                delete from sends
                where user_id = ?
                  and contact_id = ?
                  and campaign_key = ?
                  and subject = ?
                  and (send_job_id = ? or send_job_id = '')
                  and status = 'queued'
                """,
                (current_user_id(), contact_id, campaign_key_value, subject, send_job_id),
            )
            deleted_count += max(cursor.rowcount, 0)
        db.commit()
    if deleted_count:
        mark_app_state_dirty()
    return deleted_count


def delete_pending_sends_for_unsubscribe(
    contact_id: int = 0,
    contact_email: str = "",
    youtube_channel_id: str = "",
    scope: str = UNSUBSCRIBE_SCOPE_GLOBAL,
    scope_key: str = "",
) -> int:
    user_id = current_user_id()
    normalized_email = contact_email.strip().lower()
    channel_id = youtube_channel_id.strip()
    clean_scope = str(scope or UNSUBSCRIBE_SCOPE_GLOBAL).strip() or UNSUBSCRIBE_SCOPE_GLOBAL
    clean_key = str(scope_key or "").strip()
    target_campaign_keys = campaign_keys_for_unsubscribe_scope(clean_scope, clean_key)
    local_contact_ids: set[int] = set()
    if contact_id:
        local_contact_ids.add(int(contact_id))
    if normalized_email:
        local_contact_ids.update(
            int(row["id"])
            for row in rows(
                "select id from contacts where user_id = ? and email = ?",
                (user_id, normalized_email),
            )
        )
    if channel_id:
        local_contact_ids.update(
            int(row["id"])
            for row in rows(
                "select id from contacts where user_id = ? and youtube_channel_id = ?",
                (user_id, channel_id),
            )
        )

    deleted_count = 0
    affected_job_ids: set[str] = set()
    if supabase_configured():
        user_email = current_user_profile()["email"].strip().lower()
        if user_email:
            query_email = urllib.parse.quote(user_email, safe="")
            deleted_remote_keys: set[tuple[str, int, str]] = set()
            remote_filters: list[str] = []
            for local_contact_id in sorted(local_contact_ids):
                remote_filters.append(f"contact_local_id=eq.{local_contact_id}")
            if normalized_email:
                remote_filters.append(f"contact_email=eq.{urllib.parse.quote(normalized_email, safe='')}")

            for remote_filter in remote_filters:
                campaign_filters = target_campaign_keys if clean_scope != UNSUBSCRIBE_SCOPE_GLOBAL else [""]
                for campaign_key_filter in campaign_filters:
                    campaign_part = (
                        f"&campaign_key=eq.{urllib.parse.quote(campaign_key_filter, safe='')}"
                        if campaign_key_filter
                        else ""
                    )
                    try:
                        deleted_rows = supabase_request(
                            "DELETE",
                            (
                                "send_queue"
                                f"?user_email=eq.{query_email}"
                                "&status=eq.pending"
                                f"&{remote_filter}"
                                f"{campaign_part}"
                                "&select=job_id,contact_local_id,campaign_key,subject"
                            ),
                            prefer="return=representation",
                        )
                    except Exception:
                        deleted_rows = []
                    if not isinstance(deleted_rows, list):
                        continue
                    for item in deleted_rows:
                        job_id = str(item.get("job_id") or "")
                        if job_id:
                            affected_job_ids.add(job_id)
                        key = (
                            job_id,
                            int(item.get("contact_local_id") or 0),
                            str(item.get("subject") or ""),
                        )
                        deleted_remote_keys.add(key)
            deleted_count += len(deleted_remote_keys)
            refresh_supabase_send_jobs(affected_job_ids)

    local_deleted = 0
    if local_contact_ids:
        placeholders = ",".join("?" for _ in local_contact_ids)
        campaign_clause = ""
        campaign_params: list[str] = []
        if clean_scope != UNSUBSCRIBE_SCOPE_GLOBAL:
            if not target_campaign_keys:
                return max(deleted_count, local_deleted)
            campaign_clause = f"and campaign_key in ({','.join('?' for _ in target_campaign_keys)})"
            campaign_params = target_campaign_keys
        with sqlite3.connect(DB_PATH) as db:
            cursor = db.execute(
                f"""
                delete from sends
                where user_id = ?
                  and status = 'queued'
                  and contact_id in ({placeholders})
                  {campaign_clause}
                """,
                (user_id, *sorted(local_contact_ids), *campaign_params),
            )
            local_deleted = max(cursor.rowcount, 0)
            db.commit()
    if local_deleted:
        mark_app_state_dirty()
    return max(deleted_count, local_deleted)


def refresh_supabase_send_jobs(job_ids: set[str]) -> None:
    if not supabase_configured():
        return
    for job_id in sorted(job_ids):
        if not job_id:
            continue
        try:
            query_job_id = urllib.parse.quote(job_id, safe="")
            queue_rows = supabase_request(
                "GET",
                f"send_queue?job_id=eq.{query_job_id}&select=status",
            )
            if not isinstance(queue_rows, list):
                continue
            sent_count = sum(1 for row in queue_rows if row.get("status") == "sent")
            failed_count = sum(1 for row in queue_rows if row.get("status") == "failed")
            pending_count = sum(1 for row in queue_rows if row.get("status") in ["pending", "sending"])
            status = "finished" if pending_count == 0 else "sending"
            payload = {
                "total_count": len(queue_rows),
                "sent_count": sent_count,
                "failed_count": failed_count,
                "status": status,
                "updated_at": now_iso(),
            }
            if status == "finished":
                payload["finished_at"] = now_iso()
            else:
                payload["started_at"] = now_iso()
            supabase_request(
                "PATCH",
                f"send_jobs?id=eq.{query_job_id}",
                payload,
                prefer="return=minimal",
            )
        except Exception:
            continue


def cancel_send_job(job: dict) -> tuple[bool, str]:
    if not supabase_configured():
        return False, "送信予約の取消にはSupabase設定が必要です。"
    user_email = current_user_profile()["email"].strip().lower()
    if not user_email:
        return False, "Googleログインのメールアドレスを確認できませんでした。"
    job_id = str(job.get("id") or "").strip()
    if not job_id:
        return False, "送信予約IDを確認できませんでした。"
    if not is_cancelable_send_job(job):
        return False, "この送信予約はすでに完了しているため、取り消せません。"

    query_email = urllib.parse.quote(user_email, safe="")
    query_job_id = urllib.parse.quote(job_id, safe="")
    try:
        canceled_rows = supabase_request(
            "DELETE",
            (
                "send_queue"
                f"?user_email=eq.{query_email}"
                f"&job_id=eq.{query_job_id}"
                "&status=eq.pending"
                "&select=contact_local_id,campaign_key,subject"
            ),
            prefer="return=representation",
        )
        if not isinstance(canceled_rows, list):
            canceled_rows = []
        local_deleted = delete_local_queued_sends_for_job(job_id, canceled_rows)
        supabase_request(
            "PATCH",
            f"send_jobs?user_email=eq.{query_email}&id=eq.{query_job_id}",
            {"status": "canceled", "updated_at": now_iso()},
            prefer="return=minimal",
        )
    except Exception as exc:
        return False, f"送信予約を取り消せませんでした: {exc}"

    restored_count = max(len(canceled_rows), local_deleted)
    if restored_count:
        return True, f"送信予約を取り消しました。送信待ちだった{restored_count}件を未送信の状態に戻しました。"
    return True, "送信予約を取り消しました。送信待ちの宛先はすでに処理済み、または見つかりませんでした。"


def record_unsubscribe_event(
    contact_id: int = 0,
    contact_email: str = "",
    youtube_channel_id: str = "",
    channel: str = "",
    unsubscribed_at: str = "",
    campaign_key_value: str = "",
    scope: str = UNSUBSCRIBE_SCOPE_CAMPAIGN,
    scope_key: str = "",
    scope_label: str = "",
) -> None:
    user_id = current_user_id()
    clean_scope = str(scope or UNSUBSCRIBE_SCOPE_CAMPAIGN).strip() or UNSUBSCRIBE_SCOPE_CAMPAIGN
    clean_scope_key = str(scope_key or "").strip()
    clean_scope_label = str(scope_label or "").strip()
    contact_rows = []
    if contact_id:
        contact_rows = rows(
            "select id, email, youtube_channel_id, channel from contacts where user_id = ? and id = ?",
            (user_id, int(contact_id)),
        )
    if not contact_rows and contact_email:
        contact_rows = rows(
            "select id, email, youtube_channel_id, channel from contacts where user_id = ? and email = ?",
            (user_id, contact_email.strip().lower()),
        )
    if not contact_rows and youtube_channel_id:
        contact_rows = rows(
            "select id, email, youtube_channel_id, channel from contacts where user_id = ? and youtube_channel_id = ?",
            (user_id, youtube_channel_id.strip()),
        )

    target_rows = contact_rows or [
        {
            "id": int(contact_id or 0),
            "email": contact_email.strip().lower(),
            "youtube_channel_id": youtube_channel_id.strip(),
            "channel": channel.strip(),
        }
    ]
    event_time = unsubscribed_at or now_iso()
    for contact in target_rows:
        local_contact_id = int(contact["id"] or 0)
        campaign_row = None
        if local_contact_id:
            matches = rows(
                """
                select campaign_key
                from sends
                where user_id = ?
                  and contact_id = ?
                  and campaign_key != ''
                  and status in ('sent', 'queued')
                order by sent_at desc, id desc
                limit 1
                """,
                (user_id, local_contact_id),
            )
            campaign_row = matches[0] if matches else None
        resolved_campaign_key = campaign_key_value or (campaign_row["campaign_key"] if campaign_row else "")
        if clean_scope == UNSUBSCRIBE_SCOPE_CAMPAIGN and not clean_scope_key:
            clean_scope_key = resolved_campaign_key
        if clean_scope == UNSUBSCRIBE_SCOPE_GLOBAL:
            clean_scope_key = UNSUBSCRIBE_SCOPE_GLOBAL
            clean_scope_label = clean_scope_label or "すべての案内"
        email_value = str(contact["email"] or contact_email).strip().lower()
        channel_id_value = str(contact["youtube_channel_id"] or youtube_channel_id).strip()
        channel_value = str(contact["channel"] or channel).strip()
        exists = rows(
            """
            select id
            from unsubscribe_events
            where user_id = ?
              and contact_email = ?
              and scope = ?
              and scope_key = ?
            limit 1
            """,
            (user_id, email_value, clean_scope, clean_scope_key),
        )
        if exists:
            continue
        execute(
            """
            insert into unsubscribe_events
            (user_id, contact_email, youtube_channel_id, channel, campaign_key, scope, scope_key, scope_label, unsubscribed_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                email_value,
                channel_id_value,
                channel_value,
                resolved_campaign_key,
                clean_scope,
                clean_scope_key,
                clean_scope_label or scope_display_label(clean_scope, clean_scope_key),
                event_time,
            ),
        )


def delete_remote_unsubscribe_mirror(event: sqlite3.Row) -> list[str]:
    warnings = []
    if not supabase_configured():
        return warnings
    user_email = current_user_profile()["email"].strip().lower()
    if not user_email:
        return warnings

    query_user_email = urllib.parse.quote(user_email, safe="")
    contact_email = str(event["contact_email"] or "").strip().lower()
    youtube_channel_id = str(event["youtube_channel_id"] or "").strip()
    scope = str(event["scope"] or "").strip() or UNSUBSCRIBE_SCOPE_CAMPAIGN
    scope_key = str(event["scope_key"] or "").strip()
    reason = unsubscribe_reason(scope, scope_key)

    try:
        reason_values = [reason]
        if scope == UNSUBSCRIBE_SCOPE_GLOBAL:
            reason_values.append("配信停止URL")
        for reason_value in dict.fromkeys(reason_values):
            reason_query = urllib.parse.quote(reason_value, safe="")
            base_path = f"blocked_targets?user_email=eq.{query_user_email}&reason=eq.{reason_query}"
            if contact_email:
                contact_query = urllib.parse.quote(contact_email, safe="")
                supabase_request(
                    "DELETE",
                    f"{base_path}&email=eq.{contact_query}",
                    prefer="return=minimal",
                )
            if youtube_channel_id:
                channel_query = urllib.parse.quote(youtube_channel_id, safe="")
                supabase_request(
                    "DELETE",
                    f"{base_path}&youtube_channel_id=eq.{channel_query}",
                    prefer="return=minimal",
                )

        if scope == UNSUBSCRIBE_SCOPE_GLOBAL:
            token_payload = {"unsubscribed_at": None, "updated_at": now_iso()}
            if contact_email:
                contact_query = urllib.parse.quote(contact_email, safe="")
                supabase_request(
                    "PATCH",
                    f"unsubscribe_tokens?user_email=eq.{query_user_email}&contact_email=eq.{contact_query}",
                    token_payload,
                    prefer="return=minimal",
                )
            if youtube_channel_id:
                channel_query = urllib.parse.quote(youtube_channel_id, safe="")
                supabase_request(
                    "PATCH",
                    f"unsubscribe_tokens?user_email=eq.{query_user_email}&youtube_channel_id=eq.{channel_query}",
                    token_payload,
                    prefer="return=minimal",
                )
            contact_matches = []
            if contact_email:
                contact_matches = rows(
                    "select id from contacts where user_id = ? and email = ? limit 1",
                    (current_user_id(), contact_email),
                )
            if not contact_matches and youtube_channel_id:
                contact_matches = rows(
                    "select id from contacts where user_id = ? and youtube_channel_id = ? limit 1",
                    (current_user_id(), youtube_channel_id),
                )
            if contact_matches:
                supabase_request(
                    "PATCH",
                    f"unsubscribe_tokens?user_email=eq.{query_user_email}&contact_local_id=eq.{int(contact_matches[0]['id'])}",
                    token_payload,
                    prefer="return=minimal",
                )
    except Exception as exc:
        warnings.append(f"クラウド側の配信停止記録を消せませんでした: {friendly_smtp_error(str(exc))}")
    return warnings


def delete_unsubscribe_event(event_id: int) -> tuple[bool, str]:
    event_rows = rows(
        """
        select
            id,
            contact_email,
            youtube_channel_id,
            channel,
            campaign_key,
            scope,
            scope_key,
            scope_label,
            unsubscribed_at
        from unsubscribe_events
        where user_id = ? and id = ?
        limit 1
        """,
        (current_user_id(), int(event_id)),
    )
    if not event_rows:
        return False, "削除する配信停止記録が見つかりませんでした。"

    warnings = delete_remote_unsubscribe_mirror(event_rows[0])
    execute(
        "delete from unsubscribe_events where user_id = ? and id = ?",
        (current_user_id(), int(event_id)),
    )
    if warnings:
        return True, "配信停止記録を削除しました。ただし、" + " / ".join(warnings)
    return True, "配信停止記録を削除しました。宛先一覧への自動復活はしていません。"


def sync_unsubscribes_from_supabase() -> None:
    if not supabase_configured():
        return
    user_email = current_user_profile()["email"].strip().lower()
    if not user_email:
        return
    try:
        query_email = urllib.parse.quote(user_email, safe="")
        token_results = supabase_request(
            "GET",
            f"unsubscribe_tokens?user_email=eq.{query_email}&unsubscribed_at=not.is.null&select=contact_local_id,contact_email,youtube_channel_id,channel,unsubscribed_at",
        )
        if not isinstance(token_results, list):
            token_results = []
        for item in token_results:
            contact_id = int(item.get("contact_local_id") or 0)
            contact_email = str(item.get("contact_email") or "").strip().lower()
            youtube_channel_id = str(item.get("youtube_channel_id") or "").strip()
            channel = str(item.get("channel") or "").strip()
            unsubscribed_at = str(item.get("unsubscribed_at") or now_iso())
            record_unsubscribe_event(
                contact_id,
                contact_email,
                youtube_channel_id,
                channel,
                unsubscribed_at,
                scope=UNSUBSCRIBE_SCOPE_GLOBAL,
                scope_key=UNSUBSCRIBE_SCOPE_GLOBAL,
                scope_label="すべての案内",
            )
            delete_pending_sends_for_unsubscribe(
                contact_id,
                contact_email,
                youtube_channel_id,
                UNSUBSCRIBE_SCOPE_GLOBAL,
                UNSUBSCRIBE_SCOPE_GLOBAL,
            )

        remote_blocks = supabase_request(
            "GET",
            f"blocked_targets?user_email=eq.{query_email}&select=email,youtube_channel_id,channel,reason,created_at",
        )
        if not isinstance(remote_blocks, list):
            remote_blocks = []
        for item in remote_blocks:
            reason = str(item.get("reason") or "")
            scope, scope_key = parse_unsubscribe_reason(reason)
            if not scope:
                continue
            contact_email = str(item.get("email") or "").strip().lower()
            youtube_channel_id = str(item.get("youtube_channel_id") or "").strip()
            channel = str(item.get("channel") or "").strip()
            created_at = str(item.get("created_at") or now_iso())
            scope_label = "すべての案内" if scope == UNSUBSCRIBE_SCOPE_GLOBAL else scope_key
            matched = []
            if contact_email:
                matched = rows(
                    "select id from contacts where user_id = ? and email = ?",
                    (current_user_id(), contact_email),
                )
            if not matched and youtube_channel_id:
                matched = rows(
                    "select id from contacts where user_id = ? and youtube_channel_id = ?",
                    (current_user_id(), youtube_channel_id),
                )
            target_ids = [int(row["id"]) for row in matched] or [0]
            for contact_id in target_ids:
                record_unsubscribe_event(
                    contact_id,
                    contact_email,
                    youtube_channel_id,
                    channel,
                    created_at,
                    scope=scope,
                    scope_key=scope_key,
                    scope_label=scope_label,
                )
                delete_pending_sends_for_unsubscribe(
                    contact_id,
                    contact_email,
                    youtube_channel_id,
                    scope,
                    scope_key,
                )
    except Exception:
        return


def fetch_recent_send_jobs(limit: int = 20) -> list[dict]:
    if not supabase_configured():
        return []
    user_email = current_user_profile()["email"].strip().lower()
    if not user_email:
        return []
    try:
        query_email = urllib.parse.quote(user_email, safe="")
        limit_value = max(1, min(50, int(limit or 20)))
        result = supabase_request(
            "GET",
            f"send_jobs?user_email=eq.{query_email}&select=id,campaign_key,campaign_name,total_count,sent_count,failed_count,status,created_at&order=created_at.desc&limit={limit_value}",
        )
        return result if isinstance(result, list) else []
    except Exception:
        return []


def mark_stale_empty_creating_jobs_failed(jobs: list[dict]) -> None:
    if not supabase_configured() or not jobs:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    for job in jobs:
        if str(job.get("status") or "").lower() != "creating":
            continue
        created_at = parse_utc_datetime(str(job.get("created_at") or ""))
        if not created_at or created_at >= cutoff:
            continue
        job_id = str(job.get("id") or "").strip()
        if not job_id or send_queue_has_rows(job_id):
            continue
        try:
            supabase_request(
                "PATCH",
                f"send_jobs?id=eq.{urllib.parse.quote(job_id, safe='')}",
                {"status": "failed", "updated_at": now_iso()},
                prefer="return=minimal",
            )
            job["status"] = "failed"
        except Exception:
            continue


def fetch_send_job_queue_summary(job_id: str) -> dict[str, object]:
    summary: dict[str, object] = {
        "has_queue": False,
        "first_queue_status": "",
        "first_queue_at": "",
        "next_pending_at": "",
        "sending_count": 0,
        "stale_sending_count": 0,
        "overdue_pending": False,
    }
    if not supabase_configured() or not str(job_id or "").strip():
        return summary
    try:
        query_job_id = urllib.parse.quote(str(job_id), safe="")
        first_rows = supabase_request(
            "GET",
            f"send_queue?job_id=eq.{query_job_id}&select=status,scheduled_at&order=scheduled_at.asc&limit=1",
        )
        if isinstance(first_rows, list) and first_rows:
            summary["has_queue"] = True
            summary["first_queue_status"] = str(first_rows[0].get("status") or "")
            summary["first_queue_at"] = str(first_rows[0].get("scheduled_at") or "")

        next_rows = supabase_request(
            "GET",
            f"send_queue?job_id=eq.{query_job_id}&status=eq.pending&select=scheduled_at&order=scheduled_at.asc&limit=1",
        )
        if isinstance(next_rows, list) and next_rows:
            summary["next_pending_at"] = str(next_rows[0].get("scheduled_at") or "")

        sending_rows = supabase_request(
            "GET",
            f"send_queue?job_id=eq.{query_job_id}&status=eq.sending&select=updated_at",
        )
        if isinstance(sending_rows, list):
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=STREAMLIT_SEND_QUEUE_STALE_SENDING_SECONDS)
            summary["sending_count"] = len(sending_rows)
            summary["stale_sending_count"] = sum(
                1
                for row in sending_rows
                if (parse_utc_datetime(str(row.get("updated_at") or "")) or datetime.now(timezone.utc)) < cutoff
            )

        now_value = urllib.parse.quote(datetime.now(timezone.utc).isoformat(timespec="seconds"), safe="")
        overdue_rows = supabase_request(
            "GET",
            f"send_queue?job_id=eq.{query_job_id}&status=eq.pending&scheduled_at=lte.{now_value}&select=scheduled_at&order=scheduled_at.asc&limit=1",
        )
        summary["overdue_pending"] = bool(isinstance(overdue_rows, list) and overdue_rows)
    except Exception:
        summary["has_queue"] = False
        summary["first_queue_status"] = ""
        summary["first_queue_at"] = ""
        summary["next_pending_at"] = ""
        summary["sending_count"] = 0
        summary["stale_sending_count"] = 0
        summary["overdue_pending"] = False
    return summary


def prerequisite_sql(prerequisite_keys: list[str], contact_alias: str = "c") -> tuple[str, list[str]]:
    conditions = []
    params = []
    for index, key in enumerate(prerequisite_keys):
        alias = f"prereq_{index}"
        conditions.append(
            f"""
            and exists (
                select 1
                from sends {alias}
                where {alias}.user_id = {contact_alias}.user_id
                  and {alias}.contact_id = {contact_alias}.id
                  and {alias}.campaign_key = ?
                  and {alias}.status = 'sent'
            )
            """
        )
        params.append(key)
    return "\n".join(conditions), params


def exclusion_sql(exclusion_keys: list[str], contact_alias: str = "c") -> tuple[str, list[str]]:
    conditions = []
    params = []
    for index, key in enumerate(exclusion_keys):
        alias = f"exclude_step_{index}"
        conditions.append(
            f"""
            and not exists (
                select 1
                from sends {alias}
                where {alias}.user_id = {contact_alias}.user_id
                  and {alias}.contact_id = {contact_alias}.id
                  and {alias}.campaign_key = ?
                  and {alias}.status in ('sent', 'queued')
            )
            """
        )
        params.append(key)
    return "\n".join(conditions), params


def unsubscribe_exclusion_sql(
    scope: str,
    scope_key: str,
    contact_alias: str = "c",
) -> tuple[str, list[str]]:
    clean_scope = str(scope or UNSUBSCRIBE_SCOPE_CAMPAIGN).strip() or UNSUBSCRIBE_SCOPE_CAMPAIGN
    clean_key = str(scope_key or "").strip()
    params: list[str] = []
    scope_condition = "ue.scope = 'global'"
    if clean_scope != UNSUBSCRIBE_SCOPE_GLOBAL and clean_key:
        scope_condition = "(ue.scope = 'global' or (ue.scope = ? and ue.scope_key = ?))"
        params.extend([clean_scope, clean_key])
    return (
        f"""
        and not exists (
            select 1
            from unsubscribe_events ue
            where ue.user_id = {contact_alias}.user_id
              and (
                  (ue.contact_email != '' and ue.contact_email = lower({contact_alias}.email))
                  or
                  (ue.youtube_channel_id != '' and ue.youtube_channel_id = {contact_alias}.youtube_channel_id)
              )
              and {scope_condition}
        )
        """,
        params,
    )


def fetch_next_send_contacts(
    campaign_key_value: str,
    limit: int,
    prerequisite_keys: list[str] | None = None,
    exclusion_keys: list[str] | None = None,
    offset: int = 0,
    unsubscribe_scope: str = UNSUBSCRIBE_SCOPE_CAMPAIGN,
    unsubscribe_scope_key: str = "",
) -> list[sqlite3.Row]:
    prereq_sql, prereq_params = prerequisite_sql(prerequisite_keys or [])
    exclude_sql, exclude_params = exclusion_sql(exclusion_keys or [])
    unsub_sql, unsub_params = unsubscribe_exclusion_sql(
        unsubscribe_scope,
        unsubscribe_scope_key or campaign_key_value,
    )
    return rows(
        f"""
        select
            c.*,
            max(s.sent_at) as last_sent
        from contacts c
        left join sends s on s.contact_id = c.id and s.status = 'sent'
        where c.user_id = ? and c.consent = 1 and c.unsubscribed = 0 and c.email != ''
          and coalesce(c.contact_status, '送信対象') in ('未確認', 'メール確認済み', '送信対象')
          and not exists (
              select 1
              from sends sent_campaign
              where sent_campaign.user_id = c.user_id
                and sent_campaign.contact_id = c.id
                and sent_campaign.campaign_key = ?
                and sent_campaign.status in ('sent', 'queued')
          )
        {prereq_sql}
        {exclude_sql}
        {unsub_sql}
        group by c.id
        order by
            case when max(s.sent_at) is null then 0 else 1 end,
            max(s.sent_at) asc,
            c.id asc
        limit ? offset ?
        """,
        (
            current_user_id(),
            campaign_key_value,
            *prereq_params,
            *exclude_params,
            *unsub_params,
            int(limit),
            int(offset),
        ),
    )


def count_next_send_contacts(
    campaign_key_value: str,
    prerequisite_keys: list[str] | None = None,
    exclusion_keys: list[str] | None = None,
    unsubscribe_scope: str = UNSUBSCRIBE_SCOPE_CAMPAIGN,
    unsubscribe_scope_key: str = "",
) -> int:
    prereq_sql, prereq_params = prerequisite_sql(prerequisite_keys or [])
    exclude_sql, exclude_params = exclusion_sql(exclusion_keys or [])
    unsub_sql, unsub_params = unsubscribe_exclusion_sql(
        unsubscribe_scope,
        unsubscribe_scope_key or campaign_key_value,
    )
    return int(
        rows(
            f"""
            select count(*) as count
            from contacts c
            where c.user_id = ?
              and c.consent = 1
              and c.unsubscribed = 0
              and c.email != ''
              and coalesce(c.contact_status, '送信対象') in ('未確認', 'メール確認済み', '送信対象')
              and not exists (
                  select 1
                  from sends s
                  where s.user_id = c.user_id
                    and s.contact_id = c.id
                    and s.campaign_key = ?
                    and s.status in ('sent', 'queued')
              )
              {prereq_sql}
              {exclude_sql}
              {unsub_sql}
            """,
            (
                current_user_id(),
                campaign_key_value,
                *prereq_params,
                *exclude_params,
                *unsub_params,
            ),
        )[0]["count"]
        or 0
    )


def count_waiting_for_prerequisites(
    campaign_key_value: str,
    prerequisite_keys: list[str],
    exclusion_keys: list[str] | None = None,
    unsubscribe_scope: str = UNSUBSCRIBE_SCOPE_CAMPAIGN,
    unsubscribe_scope_key: str = "",
) -> int:
    if not prerequisite_keys:
        return 0
    qualified_count = count_next_send_contacts(
        campaign_key_value,
        prerequisite_keys,
        exclusion_keys or [],
        unsubscribe_scope,
        unsubscribe_scope_key,
    )
    unrestricted_count = count_next_send_contacts(
        campaign_key_value,
        [],
        exclusion_keys or [],
        unsubscribe_scope,
        unsubscribe_scope_key,
    )
    return max(0, int(unrestricted_count) - int(qualified_count))


def count_excluded_by_later_steps(
    campaign_key_value: str,
    prerequisite_keys: list[str],
    exclusion_keys: list[str],
    unsubscribe_scope: str = UNSUBSCRIBE_SCOPE_CAMPAIGN,
    unsubscribe_scope_key: str = "",
) -> int:
    if not exclusion_keys:
        return 0
    unrestricted_count = count_next_send_contacts(
        campaign_key_value,
        prerequisite_keys,
        [],
        unsubscribe_scope,
        unsubscribe_scope_key,
    )
    allowed_count = count_next_send_contacts(
        campaign_key_value,
        prerequisite_keys,
        exclusion_keys,
        unsubscribe_scope,
        unsubscribe_scope_key,
    )
    return max(0, int(unrestricted_count) - int(allowed_count))


def fetch_failed_sends(limit: int = 20) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as db:
        return pd.read_sql_query(
            """
            select
                s.id as send_id,
                c.id as contact_id,
                c.channel,
                c.email,
                s.subject,
                s.error,
                s.sent_at
            from sends s
            left join contacts c on c.id = s.contact_id and c.user_id = s.user_id
            where s.user_id = ? and s.status = 'failed'
            order by s.sent_at desc, s.id desc
            limit ?
            """,
            db,
            params=(current_user_id(), int(limit)),
        )


def send_status_label(status: str) -> str:
    return {
        "sent": "送信済み",
        "queued": "送信待ち",
        "failed": "失敗",
    }.get(str(status or ""), str(status or "不明"))


def fetch_send_history(limit: int = 500) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as db:
        return pd.read_sql_query(
            """
            select
                s.id as send_id,
                s.sent_at,
                s.status,
                s.campaign_key,
                c.channel,
                c.email,
                c.name,
                c.memo,
                s.subject,
                s.error
            from sends s
            left join contacts c on c.id = s.contact_id and c.user_id = s.user_id
            where s.user_id = ?
            order by s.sent_at desc, s.id desc
            limit ?
            """,
            db,
            params=(current_user_id(), int(limit)),
        )


def campaign_display_name_map() -> dict[str, str]:
    name_by_key = {
        campaign_key(str(template["name"] or "")): str(template["name"] or "")
        for template in fetch_campaign_templates()
    }
    for scenario in fetch_scenarios():
        for step in fetch_scenario_steps(int(scenario["id"])):
            step_key = scenario_step_campaign_key(int(scenario["id"]), int(step["step_number"]))
            name_by_key[step_key] = scenario_step_campaign_name(
                str(scenario["name"] or ""),
                int(step["step_number"]),
                str(step["template_name"] or ""),
            )
    return name_by_key


def prepare_send_history_display(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    template_name_by_key = campaign_display_name_map()
    display = frame.copy().fillna("")
    display["日時"] = display["sent_at"].apply(format_jst_datetime)
    display["状態"] = display["status"].apply(send_status_label)
    display["配信名"] = display["campaign_key"].map(template_name_by_key).fillna("削除済み/不明の配信")
    display["チャンネル"] = display["channel"].replace("", "-")
    display["メールアドレス"] = display["email"].replace("", "-")
    display["メモ"] = display["memo"].replace("", "-")
    display["件名"] = display["subject"].replace("", "-")
    failure_info = display["error"].apply(classify_send_failure)
    display["原因分類"] = failure_info.apply(lambda item: item[0])
    display["対応の目安"] = failure_info.apply(lambda item: item[1])
    display["失敗理由"] = display["error"].replace("", "-")
    display.loc[display["状態"] != "失敗", ["原因分類", "対応の目安", "失敗理由"]] = "-"
    return display[["日時", "状態", "原因分類", "配信名", "チャンネル", "メールアドレス", "メモ", "件名", "対応の目安", "失敗理由"]]


def fetch_campaign_template_stats(template_names: list[str]) -> pd.DataFrame:
    records = []
    for name in template_names:
        key = campaign_key(name)
        counts = rows(
            """
            select
                sum(case when status = 'sent' then 1 else 0 end) as sent_count,
                sum(case when status = 'failed' then 1 else 0 end) as failed_count,
                sum(case when status = 'queued' then 1 else 0 end) as queued_count,
                count(*) as total_count
            from sends
            where user_id = ? and campaign_key = ?
            """,
            (current_user_id(), key),
        )[0]
        unsubscribe_count = rows(
            """
            select count(*) as count
            from unsubscribe_events
            where user_id = ?
              and (
                  campaign_key = ?
                  or (scope = 'campaign' and scope_key = ?)
              )
            """,
            (current_user_id(), key, key),
        )[0]["count"]
        sent_count = int(counts["sent_count"] or 0)
        unsubscribe_rate = (int(unsubscribe_count or 0) / sent_count * 100) if sent_count else 0
        records.append(
            {
                "配信テンプレート": name,
                "送信成功": sent_count,
                "送信失敗": int(counts["failed_count"] or 0),
                "送信待ち": int(counts["queued_count"] or 0),
                "配信停止": int(unsubscribe_count or 0),
                "配信停止率": f"{unsubscribe_rate:.1f}%",
                "送信記録合計": int(counts["total_count"] or 0),
            }
        )
    return pd.DataFrame(records)


def fetch_scenario_step_stats(scenario_id: int) -> pd.DataFrame:
    records = []
    scenario = rows(
        "select name from scenarios where user_id = ? and id = ? limit 1",
        (current_user_id(), int(scenario_id)),
    )
    scenario_name = str(scenario[0]["name"] or "") if scenario else ""
    steps = fetch_scenario_steps(int(scenario_id))
    for step in steps:
        step_number = int(step["step_number"])
        key = scenario_step_campaign_key(int(scenario_id), step_number)
        counts = rows(
            """
            select
                sum(case when status = 'sent' then 1 else 0 end) as sent_count,
                sum(case when status = 'failed' then 1 else 0 end) as failed_count,
                sum(case when status = 'queued' then 1 else 0 end) as queued_count,
                count(*) as total_count
            from sends
            where user_id = ? and campaign_key = ?
            """,
            (current_user_id(), key),
        )[0]
        unsubscribe_count = rows(
            """
            select count(*) as count
            from unsubscribe_events
            where user_id = ?
              and (
                  campaign_key = ?
                  or (scope = 'campaign' and scope_key = ?)
                  or (scope = 'scenario' and scope_key = ?)
              )
            """,
            (current_user_id(), key, key, scenario_name),
        )[0]["count"]
        sent_count = int(counts["sent_count"] or 0)
        unsubscribe_rate = (int(unsubscribe_count or 0) / sent_count * 100) if sent_count else 0
        records.append(
            {
                "ステップ": f"{step_number}通目",
                "配信テンプレート": step["template_name"],
                "送信成功": sent_count,
                "送信失敗": int(counts["failed_count"] or 0),
                "送信待ち": int(counts["queued_count"] or 0),
                "配信停止": int(unsubscribe_count or 0),
                "配信停止率": f"{unsubscribe_rate:.1f}%",
                "送信記録合計": int(counts["total_count"] or 0),
            }
        )
    return pd.DataFrame(records)


def safety_check_messages(
    subject_template: str,
    body_template: str,
    send_limit: int,
    planned_count: int,
    preview_available: bool,
    daily_capacity: int = 0,
) -> list[str]:
    messages = []
    clean_subject = subject_template.strip()
    clean_body = body_template.strip()
    if not clean_subject:
        messages.append("件名が空です。送信前に件名を入力してください。")
    if len(clean_subject) > 80:
        messages.append("件名が長めです。相手のメールアプリで途中までしか表示されない可能性があります。")
    if len(clean_body) < 80:
        messages.append("本文がかなり短いです。誤送信でないか確認してください。")
    if "${unsubscribe_url}" not in body_template:
        messages.append("本文に配信停止URLがありません。送信時に末尾へ自動追加されます。")
    if int(daily_capacity or 0) > 800:
        messages.append("1日の送信予定件数が多めです。送信エラーや迷惑メール判定が増えないか確認してください。")
    elif int(send_limit) > 1000:
        messages.append("予約総数が多めです。数日に分けて送信されます。途中で止めたい時は「最近の送信予約」から取り消せます。")
    if planned_count == 0:
        messages.append("今回送信できる未送信の宛先がありません。配信名や送信済み状況を確認してください。")
    if not preview_available:
        messages.append("送信前プレビューを作れる宛先がありません。")
    return messages


def fetch_blocked_targets() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as db:
        return pd.read_sql_query(
            """
            select
                id,
                email,
                youtube_channel_id,
                channel,
                reason,
                created_at
            from blocked_targets
            where user_id = ?
            order by id desc
            """,
            db,
            params=(current_user_id(),),
        )


def fetch_unsubscribe_events(limit: int = 500) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as db:
        return pd.read_sql_query(
            """
            select
                id,
                contact_email,
                youtube_channel_id,
                channel,
                campaign_key,
                scope,
                scope_key,
                scope_label,
                unsubscribed_at
            from unsubscribe_events
            where user_id = ?
            order by id desc
            limit ?
            """,
            db,
            params=(current_user_id(), int(limit)),
        ).fillna("")


def unsubscribe_scope_target_label(
    scope: str,
    scope_key: str,
    scope_label: str = "",
    campaign_names: dict[str, str] | None = None,
) -> str:
    clean_scope = str(scope or "").strip()
    clean_key = str(scope_key or "").strip()
    clean_label = str(scope_label or "").strip()
    campaign_names = campaign_names or {}
    if clean_scope == UNSUBSCRIBE_SCOPE_GLOBAL:
        return "すべての案内"
    if clean_scope == UNSUBSCRIBE_SCOPE_SCENARIO:
        return clean_label or clean_key or "-"
    if clean_scope == UNSUBSCRIBE_SCOPE_CAMPAIGN:
        if clean_label and clean_label != "この配信":
            return clean_label
        return campaign_names.get(clean_key, clean_key or "-")
    return clean_label or clean_key or "-"


def sent_count_for_unsubscribe_scope(scope: str, scope_key: str) -> int:
    clean_scope = str(scope or "").strip()
    clean_key = str(scope_key or "").strip()
    if clean_scope == UNSUBSCRIBE_SCOPE_GLOBAL:
        result = rows(
            "select count(*) as count from sends where user_id = ? and status = 'sent'",
            (current_user_id(),),
        )[0]
        return int(result["count"] or 0)
    campaign_keys = campaign_keys_for_unsubscribe_scope(clean_scope, clean_key)
    if not campaign_keys:
        return 0
    placeholders = ",".join(["?"] * len(campaign_keys))
    result = rows(
        f"""
        select count(*) as count
        from sends
        where user_id = ?
          and status = 'sent'
          and campaign_key in ({placeholders})
        """,
        (current_user_id(), *campaign_keys),
    )[0]
    return int(result["count"] or 0)


def unsubscribe_events_display_frame(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=["_event_id", "停止日時", "停止種類", "停止対象", "メールアドレス", "チャンネル", "停止理由"])
    campaign_names = campaign_display_name_map()
    display = events.copy()
    display["_event_id"] = display["id"].astype(int)
    display["停止日時"] = display["unsubscribed_at"].apply(format_jst_datetime)
    display["停止種類"] = display["scope"].apply(unsubscribe_scope_kind_label)
    display["停止対象"] = display.apply(
        lambda row: unsubscribe_scope_target_label(row["scope"], row["scope_key"], row["scope_label"], campaign_names),
        axis=1,
    )
    display["メールアドレス"] = display["contact_email"].replace("", "-")
    display["チャンネル"] = display["channel"].where(
        display["channel"].astype(str).str.strip() != "",
        display["youtube_channel_id"],
    ).replace("", "-")
    display["停止理由"] = "配信停止URLクリック"
    return display[["_event_id", "停止日時", "停止種類", "停止対象", "メールアドレス", "チャンネル", "停止理由"]]


def unsubscribe_events_summary_frame(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=["停止種類", "停止対象", "配信停止", "送信成功", "停止率", "最新停止日時"])
    campaign_names = campaign_display_name_map()
    prepared = events.copy().fillna("")
    prepared["停止種類"] = prepared["scope"].apply(unsubscribe_scope_kind_label)
    prepared["停止対象"] = prepared.apply(
        lambda row: unsubscribe_scope_target_label(row["scope"], row["scope_key"], row["scope_label"], campaign_names),
        axis=1,
    )
    records = []
    for (_, _), group in prepared.groupby(["停止種類", "停止対象"], dropna=False):
        first = group.iloc[0]
        stopped_count = int(len(group))
        sent_count = sent_count_for_unsubscribe_scope(str(first["scope"]), str(first["scope_key"]))
        stop_rate = f"{(stopped_count / sent_count * 100):.1f}%" if sent_count else "-"
        latest = str(group["unsubscribed_at"].max() or "")
        records.append(
            {
                "停止種類": str(first["停止種類"]),
                "停止対象": str(first["停止対象"]),
                "配信停止": stopped_count,
                "送信成功": sent_count,
                "停止率": stop_rate,
                "最新停止日時": format_jst_datetime(latest) if latest else "-",
            }
        )
    return pd.DataFrame(records).sort_values(["配信停止", "停止対象"], ascending=[False, True])


def add_contact(
    email: str,
    memo: str,
    channel: str,
    consent: bool,
    youtube_channel_id: str = "",
    youtube_channel_url: str = "",
    youtube_subscriber_count: int = 0,
    youtube_video_count: int = 0,
    youtube_view_count: int = 0,
    youtube_keyword: str = "",
    youtube_description: str = "",
) -> bool:
    normalized_email = email.strip().lower()
    if is_blocked(normalized_email, youtube_channel_id):
        return False
    if normalized_email and contact_exists(normalized_email):
        return False
    if youtube_channel_id and youtube_channel_in_contacts(youtube_channel_id):
        return False
    if not normalized_email and candidate_contact_exists(channel):
        return False
    execute(
        """
        insert into contacts
        (
            user_id, email, name, memo, channel, youtube_channel_id, youtube_channel_url,
            youtube_subscriber_count, youtube_video_count, youtube_view_count,
            youtube_keyword, youtube_description, source, consent, unsubscribed, token, created_at
        )
        values (?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, 0, ?, ?)
        """,
        (
            current_user_id(),
            normalized_email,
            memo.strip(),
            channel.strip(),
            youtube_channel_id.strip(),
            youtube_channel_url.strip(),
            int(youtube_subscriber_count),
            int(youtube_video_count),
            int(youtube_view_count),
            youtube_keyword.strip(),
            youtube_description.strip(),
            1 if consent else 0,
            secrets.token_urlsafe(24),
            now_iso(),
        ),
    )
    return True


def settings_panel() -> None:
    st.subheader("送信元メール設定")
    accounts = fetch_smtp_accounts()
    account_labels = [f"{account['label']} / {account['sender_email']}" for account in accounts]
    account_ids = [int(account["id"]) for account in accounts]
    active_account = active_smtp_account()
    active_account_id = int(active_account.get("id") or 0)
    display_account = active_smtp_account()
    if display_account.get("sender_email"):
        st.caption(f"現在の送信元: {smtp_mail_from(display_account)}")
    else:
        st.caption("未設定")

    with st.expander("送信元メール設定を開く", expanded=False):
        st.caption("複数の送信元メールを登録し、送信時に使うアカウントを選べます。相手には「送信者表示名 <送信元メールアドレス>」の形で見えます。")

        if "smtp_account_id_input" not in st.session_state:
            st.session_state["smtp_account_id_input"] = active_account_id
        if "smtp_label_input" not in st.session_state:
            st.session_state["smtp_label_input"] = str(active_account.get("label") or "")
        if "smtp_sender_name_input" not in st.session_state:
            st.session_state["smtp_sender_name_input"] = str(active_account.get("sender_name") or "")
        if "smtp_sender_email_input" not in st.session_state:
            st.session_state["smtp_sender_email_input"] = str(active_account.get("sender_email") or "")
        if "smtp_host_input" not in st.session_state:
            st.session_state["smtp_host_input"] = str(active_account.get("smtp_host") or "smtp.gmail.com")
        if "smtp_port_input" not in st.session_state:
            st.session_state["smtp_port_input"] = str(active_account.get("smtp_port") or "587")
        if "smtp_ssl_input" not in st.session_state:
            st.session_state["smtp_ssl_input"] = int(active_account.get("smtp_ssl") or 0) == 1

        options = ["新しく作る"] + account_labels
        selected_index = 0
        if active_account_id in account_ids:
            selected_index = account_ids.index(active_account_id) + 1
        selected_account = st.selectbox("保存済み送信元", options, index=selected_index)
        load_col, save_col, delete_col = st.columns(3)
        selected_account_id = 0
        if selected_account != "新しく作る":
            selected_account_id = account_ids[options.index(selected_account) - 1]
        if load_col.button("読み込む", key="load_smtp_account", width="stretch", disabled=selected_account_id == 0):
            account = get_smtp_account(selected_account_id)
            if account:
                st.session_state["smtp_account_id_input"] = int(account["id"])
                st.session_state["smtp_label_input"] = account["label"]
                st.session_state["smtp_sender_name_input"] = account["sender_name"]
                st.session_state["smtp_sender_email_input"] = account["sender_email"]
                st.session_state["smtp_host_input"] = account["smtp_host"]
                st.session_state["smtp_port_input"] = account["smtp_port"]
                st.session_state["smtp_ssl_input"] = int(account["smtp_ssl"]) == 1
                save_setting("ACTIVE_SMTP_ACCOUNT_ID", str(account["id"]))
                st.rerun()

        account_label = st.text_input("設定名", key="smtp_label_input", placeholder="例: UniVerse公式")
        sender_name = st.text_input("送信者表示名", key="smtp_sender_name_input")
        sender_email = st.text_input("送信元メールアドレス", key="smtp_sender_email_input")
        smtp_host = st.text_input("SMTPサーバー", key="smtp_host_input")
        smtp_port = st.text_input("SMTPポート", key="smtp_port_input")
        smtp_ssl = st.checkbox("SSL接続を使う（465の場合だけON。587の場合はOFF）", key="smtp_ssl_input")
        port_text = str(smtp_port).strip()
        if port_text == "587" and smtp_ssl:
            st.warning("587を使う場合は、SSL接続をOFFにしてください。587はSTARTTLSで送信します。")
        elif port_text == "465" and not smtp_ssl:
            st.warning("465を使う場合は、SSL接続をONにしてください。465はSSL/TLSで送信します。")
        else:
            st.caption("Xserverの目安: 587ならSSL OFF、465ならSSL ONです。")
        editing_account_id = int(st.session_state.get("smtp_account_id_input") or 0)
        if selected_account == "新しく作る":
            editing_account_id = 0
        editing_account = get_smtp_account(editing_account_id) if editing_account_id else None
        has_password = bool(editing_account["smtp_pass"]) if editing_account else False
        smtp_pass = st.text_input(
            "SMTPパスワード / アプリパスワード",
            type="password",
            placeholder="保存済み" if has_password else "Gmailの場合はアプリパスワード",
        )

        if save_col.button("保存 / 更新", key="save_smtp_account", width="stretch"):
            if not sender_email.strip():
                st.error("送信元メールアドレスを入力してください")
            else:
                account_id = save_smtp_account(
                    editing_account_id or None,
                    account_label,
                    sender_name,
                    sender_email,
                    smtp_host,
                    smtp_port,
                    smtp_ssl,
                    smtp_pass,
                )
                save_setting("ACTIVE_SMTP_ACCOUNT_ID", str(account_id))
                st.session_state["smtp_account_id_input"] = account_id
                st.success(f"保存しました。相手には {smtp_mail_from(active_smtp_account())} から届きます。")
                st.rerun()

        if delete_col.button("削除", key="delete_smtp_account", width="stretch", disabled=selected_account_id == 0):
            delete_smtp_account(selected_account_id)
            st.success("送信元設定を削除しました")
            st.rerun()

        if has_password:
            st.caption("パスワードは保存済みです。変更したい時だけ新しいパスワードを入力してください。")

    st.subheader("YouTube API設定")
    current_youtube_api_key = get_setting("YOUTUBE_API_KEY")
    current_youtube_daily_limit = get_youtube_daily_limit()
    st.caption("保存済み" if current_youtube_api_key else "未設定")

    with st.expander("YouTube API設定を開く", expanded=False):
        youtube_api_key = st.text_input(
            "YouTube APIキー",
            type="password",
            placeholder="保存済み" if current_youtube_api_key else "Google Cloud ConsoleのAPIキー",
        )
        youtube_daily_limit = st.number_input(
            "YouTube API 1日上限 units",
            min_value=1,
            value=current_youtube_daily_limit,
            step=100,
        )
        if st.button("YouTube API設定を保存"):
            if youtube_api_key:
                save_setting("YOUTUBE_API_KEY", youtube_api_key.strip())
            save_setting("YOUTUBE_DAILY_LIMIT", str(int(youtube_daily_limit)))
            st.success("YouTube API設定を保存しました")
        if current_youtube_api_key:
            st.caption("YouTube APIキーは保存済みです。変更したい時だけ新しいキーを入力してください。")


def normalize_column_name(value: object) -> str:
    return re.sub(r"[\s_\-　]+", "", str(value).strip().lower())


def find_column(frame: pd.DataFrame, aliases: set[str]) -> str | None:
    normalized_aliases = {normalize_column_name(alias) for alias in aliases}
    for column in frame.columns:
        if normalize_column_name(column) in normalized_aliases:
            return str(column)
    return None


def guess_email_column(frame: pd.DataFrame) -> str | None:
    email_pattern = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    best_column = None
    best_count = 0
    for column in frame.columns:
        count = frame[column].fillna("").astype(str).str.strip().apply(
            lambda value: bool(email_pattern.match(value))
        ).sum()
        if count > best_count:
            best_column = str(column)
            best_count = int(count)
    return best_column if best_count else None


def decode_downloaded_bytes(data: bytes) -> str:
    for encoding in ["utf-8-sig", "utf-8", "cp932"]:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def fetch_public_google_url(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 CreatorOutreachMailer",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def describe_google_download_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return str(exc.reason)
    message = str(exc).strip()
    return message or exc.__class__.__name__


def google_public_file_error(kind: str, details: list[str] | None = None) -> str:
    detail_text = ""
    if details:
        detail_text = f"（詳細: {' / '.join(details[:3])}）"
    return (
        f"{kind}を読み込めませんでした。Google側の共有設定を"
        "「リンクを知っている全員が閲覧可」にしてから、"
        f"ブラウザのアドレスバーのURLを貼り直してください。{detail_text}"
    )


def extract_google_url_value(url: str, key: str) -> str:
    parsed = urllib.parse.urlparse(url)
    for part in [parsed.query, parsed.fragment]:
        values = urllib.parse.parse_qs(part).get(key)
        if values and values[0].strip():
            return values[0].strip()
    match = re.search(rf"(?:^|[&#?]){re.escape(key)}=([^&#]+)", parsed.fragment)
    if match:
        return urllib.parse.unquote(match.group(1)).strip()
    return ""


def extract_google_file_id(url: str, expected_kind: str) -> str:
    pattern = rf"docs\.google\.com/{expected_kind}(?:/u/\d+)?/d/(?!e/)([^/?#]+)"
    match = re.search(pattern, url)
    if not match:
        raise ValueError("GoogleファイルのURLを読み取れませんでした。ブラウザのアドレスバーからURLをコピーしてください。")
    return match.group(1)


def extract_google_published_file_id(url: str, expected_kind: str) -> str:
    pattern = rf"docs\.google\.com/{expected_kind}(?:/u/\d+)?/d/e/([^/?#]+)"
    match = re.search(pattern, url)
    return match.group(1) if match else ""


def extract_google_sheet_gid(url: str) -> str:
    return extract_google_url_value(url, "gid") or "0"


def build_google_sheet_csv_urls(sheet_id: str, gid: str, resource_key: str = "") -> list[str]:
    candidate_gids = [gid]
    if gid != "0":
        candidate_gids.append("0")

    urls: list[str] = []
    for candidate_gid in candidate_gids:
        quoted_gid = urllib.parse.quote(candidate_gid, safe="")
        resource_suffix = f"&resourcekey={urllib.parse.quote(resource_key, safe='')}" if resource_key else ""
        urls.extend(
            [
                f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={quoted_gid}{resource_suffix}",
                f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&gid={quoted_gid}{resource_suffix}",
            ]
        )
    return list(dict.fromkeys(urls))


def build_google_published_sheet_csv_urls(published_id: str, gid: str) -> list[str]:
    candidate_gids = [gid]
    if gid != "0":
        candidate_gids.append("0")

    urls: list[str] = []
    for candidate_gid in candidate_gids:
        query = urllib.parse.urlencode({"gid": candidate_gid, "single": "true", "output": "csv"})
        urls.append(f"https://docs.google.com/spreadsheets/d/e/{published_id}/pub?{query}")
    urls.append(f"https://docs.google.com/spreadsheets/d/e/{published_id}/pub?output=csv")
    return list(dict.fromkeys(urls))


def read_google_csv_bytes(data: bytes) -> pd.DataFrame:
    text = decode_downloaded_bytes(data)
    if "<html" in text[:300].lower():
        raise ValueError("Googleの権限画面が返されました")
    if not text.strip():
        raise ValueError("CSVが空でした")
    return pd.read_csv(BytesIO(text.encode("utf-8"))).fillna("")


def read_google_sheet_url(url: str) -> pd.DataFrame:
    service_account_error = ""
    if google_service_account_configured():
        try:
            return read_google_sheet_url_with_service_account(url)
        except Exception as exc:
            service_account_error = describe_google_download_error(exc)
    gid = extract_google_sheet_gid(url)
    published_id = extract_google_published_file_id(url, "spreadsheets")
    if published_id:
        export_urls = build_google_published_sheet_csv_urls(published_id, gid)
    else:
        sheet_id = extract_google_file_id(url, "spreadsheets")
        resource_key = extract_google_url_value(url, "resourcekey")
        export_urls = build_google_sheet_csv_urls(sheet_id, gid, resource_key)

    errors: list[str] = []
    if service_account_error:
        errors.append(service_account_error)
    for export_url in export_urls:
        try:
            return read_google_csv_bytes(fetch_public_google_url(export_url))
        except Exception as exc:
            error_detail = describe_google_download_error(exc)
            if error_detail not in errors:
                errors.append(error_detail)
    raise ValueError(google_public_file_error("Googleスプレッドシート", errors))


def read_google_doc_url(url: str) -> str:
    document_id = extract_google_file_id(url, "document")
    resource_key = extract_google_url_value(url, "resourcekey")
    resource_suffix = f"&resourcekey={urllib.parse.quote(resource_key, safe='')}" if resource_key else ""
    export_url = f"https://docs.google.com/document/d/{document_id}/export?format=txt{resource_suffix}"
    try:
        text = decode_downloaded_bytes(fetch_public_google_url(export_url))
    except Exception as exc:
        raise ValueError(google_public_file_error("Googleドキュメント", [describe_google_download_error(exc)])) from exc
    if "<html" in text[:300].lower():
        raise ValueError(google_public_file_error("Googleドキュメント", ["Googleの権限画面が返されました"]))
    return text


def read_contacts_file(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file).fillna("")
    if name.endswith(".tsv"):
        return pd.read_csv(uploaded_file, sep="\t").fillna("")
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded_file).fillna("")
    raise ValueError("対応している形式は CSV / TSV / XLSX / XLS です")


def is_discard_requested(value: object) -> bool:
    text = str(value or "").strip().lower()
    return text in {
        "1",
        "true",
        "yes",
        "on",
        "checked",
        "x",
        "✓",
        "○",
        "はい",
        "除外",
        "削除",
        "不要",
        "なし",
        "メールなし",
        "取り込まない",
        "取込まない",
        "候補から削除",
        "候補削除",
        "削除",
        "no email",
    }


def import_contacts_frame(frame: pd.DataFrame) -> tuple[int, int, dict[str, str | None]]:
    email_column = find_column(
        frame,
        {
            "email",
            "e-mail",
            "mail",
            "メール",
            "メールアドレス",
            "メアド",
            "連絡先",
            "emailaddress",
        },
    ) or guess_email_column(frame)
    memo_column = find_column(
        frame,
        {
            "memo",
            "note",
            "notes",
            "メモ",
            "備考",
            "コメント",
            "名前",
            "name",
            "担当者",
            "担当者名",
            "contact",
            "contactname",
        },
    )
    channel_column = find_column(
        frame,
        {
            "channel",
            "channelname",
            "チャンネル",
            "チャンネル名",
            "youtube",
            "youtubeチャンネル",
            "youtubeチャンネル名",
        },
    )
    candidate_id_column = find_column(
        frame,
        {
            "candidate_id",
            "candidateid",
            "候補id",
            "候補ID",
            "候補ID（編集しない）",
            "候補id編集しない",
            "候補ID編集しない",
        },
    )
    channel_id_column = find_column(
        frame,
        {
            "channel_id",
            "channelid",
            "youtube_channel_id",
            "youtubechannelid",
            "チャンネルid",
            "チャンネルID",
            "チャンネルID（編集しない）",
            "チャンネルID編集しない",
        },
    )
    youtube_url_column = find_column(
        frame,
        {
            "url",
            "youtubeurl",
            "youtube_url",
            "youtubeチャンネルurl",
            "youtubeチャンネルURL",
            "youtube url",
            "YouTube URL",
            "チャンネルurl",
            "チャンネルURL",
        },
    )
    discard_column = find_column(
        frame,
        {
            "取り込まない",
            "取込まない",
            "候補から削除",
            "候補削除",
            "インポートしない",
            "読み込まない",
            "宛先にしない",
            "メールなし",
            "メール無し",
            "除外",
            "削除",
            "discard",
            "skip",
            "ignore",
            "noemail",
            "no email",
        },
    )

    if not email_column and not discard_column:
        raise ValueError("メールアドレスの列を見つけられませんでした。列名に email または メールアドレス を入れてください。")

    added = 0
    skipped = 0
    removed_candidates = 0
    discarded_candidates = 0
    seen_in_file: set[str] = set()
    for _, row in frame.iterrows():
        channel = str(row.get(channel_column, "")) if channel_column else ""
        candidate = find_candidate_for_import(
            str(row.get(candidate_id_column, "")) if candidate_id_column else "",
            str(row.get(channel_id_column, "")) if channel_id_column else "",
            str(row.get(youtube_url_column, "")) if youtube_url_column else "",
            channel,
        )
        if discard_column and is_discard_requested(row.get(discard_column, "")):
            if candidate:
                delete_candidate(int(candidate["id"]))
                removed_candidates += 1
                discarded_candidates += 1
            else:
                skipped += 1
            continue
        email = str(row.get(email_column, "")).strip().lower() if email_column else ""
        if not email:
            continue
        if email in seen_in_file:
            skipped += 1
            continue
        seen_in_file.add(email)
        if candidate:
            channel = str(candidate["title"] or channel)
        memo = str(row.get(memo_column, "")) if memo_column else ""
        was_added = add_contact(
            email=email,
            memo=memo,
            channel=channel,
            consent=True,
            youtube_channel_id=str(candidate["channel_id"] or "") if candidate else "",
            youtube_channel_url=str(candidate["channel_url"] or "") if candidate else "",
            youtube_subscriber_count=int(candidate["subscriber_count"] or 0) if candidate else 0,
            youtube_video_count=int(candidate["video_count"] or 0) if candidate else 0,
            youtube_view_count=int(candidate["view_count"] or 0) if candidate else 0,
            youtube_keyword=str(candidate["keyword"] or "") if candidate else "",
            youtube_description=str(candidate["description"] or "") if candidate else "",
        )
        if was_added:
            added += 1
            if candidate:
                delete_candidate(int(candidate["id"]))
                removed_candidates += 1
        else:
            if candidate and (
                contact_exists(email) or youtube_channel_in_contacts(str(candidate["channel_id"] or ""))
            ):
                delete_candidate(int(candidate["id"]))
                removed_candidates += 1
            skipped += 1
    return added, skipped, {
        "email": email_column,
        "memo": memo_column,
        "channel": channel_column,
        "candidate_id": candidate_id_column,
        "discard": discard_column,
        "candidate_removed": str(removed_candidates),
        "candidate_discarded": str(discarded_candidates),
    }


def import_contacts_file(uploaded_file) -> tuple[int, int, dict[str, str | None]]:
    return import_contacts_frame(read_contacts_file(uploaded_file))


def import_contacts_text(text: str) -> tuple[int, int, dict[str, str | None]]:
    email_pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    added = 0
    skipped = 0
    seen: set[str] = set()
    for line in text.splitlines():
        matches = email_pattern.findall(line)
        if not matches:
            continue
        for email in matches:
            normalized_email = email.strip().lower()
            if normalized_email in seen:
                skipped += 1
                continue
            seen.add(normalized_email)
            inferred_channel = email_pattern.sub("", line).strip(" \t-–—:：,，/／|｜")
            if len(inferred_channel) > 80:
                inferred_channel = ""
            if add_contact(normalized_email, "", inferred_channel, True):
                added += 1
            else:
                skipped += 1
    if not seen:
        raise ValueError("Googleドキュメント内にメールアドレスを見つけられませんでした。")
    return added, skipped, {"email": "本文から抽出", "memo": None, "channel": "メール行から推定"}


def import_contacts_google_url(url: str) -> tuple[int, int, dict[str, str | None], str]:
    clean_url = url.strip()
    if "docs.google.com/spreadsheets/" in clean_url:
        added, skipped, mapping = import_contacts_frame(read_google_sheet_url(clean_url))
        return added, skipped, mapping, "Googleスプレッドシート"
    if "docs.google.com/document/" in clean_url:
        added, skipped, mapping = import_contacts_text(read_google_doc_url(clean_url))
        return added, skipped, mapping, "Googleドキュメント"
    raise ValueError("対応しているURLは、GoogleスプレッドシートまたはGoogleドキュメントです。")


def show_candidate_import_cleanup(mapping: dict[str, str | None]) -> None:
    removed_candidates = int(mapping.get("candidate_removed") or 0)
    discarded_candidates = int(mapping.get("candidate_discarded") or 0)
    imported_removed = max(0, removed_candidates - discarded_candidates)
    if imported_removed:
        st.caption(f"YouTube候補一覧から取込済み候補を{imported_removed}件外しました。")
    if discarded_candidates:
        st.caption(f"「候補から削除」指定の候補をYouTube候補一覧から{discarded_candidates}件削除しました。")


def queue_google_contacts_url_import() -> None:
    st.session_state["pending_google_contacts_url"] = str(st.session_state.get("google_contacts_url", "")).strip()
    st.session_state["google_contacts_url"] = ""


def render_outsource_import_history_panel() -> None:
    with st.expander("外注取り込み履歴 / 領収書", expanded=False):
        history = fetch_outsource_import_history()
        if history.empty:
            st.caption("まだ外注用Googleシートから取り込んだ履歴はありません。")
            return

        display_history = outsource_import_history_display_frame(history)
        st.dataframe(display_history, width="stretch", hide_index=True, height=240)
        export_name = datetime.now(APP_TIMEZONE).strftime("outsource_import_history_%Y%m%d_%H%M")
        history_csv_col, history_xlsx_col = st.columns(2)
        history_csv_col.download_button(
            "履歴CSVをダウンロード",
            data=display_history.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{export_name}.csv",
            mime="text/csv",
            width="stretch",
        )
        history_xlsx_col.download_button(
            "履歴Excelをダウンロード",
            data=dataframe_to_xlsx(display_history, "外注取り込み履歴"),
            file_name=f"{export_name}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )

        records = history.to_dict("records")
        labels = [
            f"No.{int(record.get('id') or 0):06d} / "
            f"{format_jst_datetime(str(record.get('created_at') or ''))} / "
            f"{int(record.get('imported_count') or 0):,}件"
            for record in records
        ]
        selected_label = st.selectbox("領収書にする履歴", labels, key="outsource_receipt_history_select")
        selected_record = records[labels.index(selected_label)]
        record_id = int(selected_record.get("id") or 0)

        default_worker_name = str(selected_record.get("worker_name") or get_setting("OUTSOURCE_DEFAULT_WORKER_NAME"))
        default_payer_name = get_setting("OUTSOURCE_RECEIPT_PAYER_NAME") or current_user_profile().get("email", "")
        default_unit_price = normalize_outsource_unit_price(
            selected_record.get("unit_price_yen")
            or get_setting("OUTSOURCE_DEFAULT_UNIT_PRICE_YEN", str(OUTSOURCE_DEFAULT_UNIT_PRICE_YEN))
        )
        default_issue_date = datetime.now(APP_TIMEZONE).date()
        stored_issue_date = str(selected_record.get("receipt_issued_at") or "").strip()
        if stored_issue_date:
            try:
                default_issue_date = date.fromisoformat(stored_issue_date[:10])
            except ValueError:
                default_issue_date = datetime.now(APP_TIMEZONE).date()

        worker_col, payer_col = st.columns(2)
        worker_name = worker_col.text_input(
            "外注さん名",
            value=default_worker_name,
            key=f"outsource_receipt_worker_{record_id}",
        )
        payer_name = payer_col.text_input(
            "宛名 / 支払者名",
            value=default_payer_name,
            key=f"outsource_receipt_payer_{record_id}",
        )
        unit_col, date_col, status_col = st.columns([1.0, 1.0, 1.0])
        unit_price = unit_col.number_input(
            "1件あたり単価",
            min_value=OUTSOURCE_MIN_UNIT_PRICE_YEN,
            max_value=OUTSOURCE_MAX_UNIT_PRICE_YEN,
            value=default_unit_price,
            step=10,
            key=f"outsource_receipt_unit_price_{record_id}",
        )
        issue_date = date_col.date_input(
            "領収書の日付",
            value=default_issue_date,
            key=f"outsource_receipt_issue_date_{record_id}",
        )
        status_options = ["未払い", "支払い済み"]
        payment_status = str(selected_record.get("payment_status") or "未払い")
        if payment_status not in status_options:
            payment_status = "未払い"
        payment_status = status_col.selectbox(
            "支払い状態",
            status_options,
            index=status_options.index(payment_status),
            key=f"outsource_receipt_payment_status_{record_id}",
        )
        receipt_note = st.text_area(
            "領収書メモ",
            value=str(selected_record.get("receipt_note") or ""),
            placeholder="例: 5月分のメールアドレス収集作業",
            key=f"outsource_receipt_note_{record_id}",
        )

        imported_count = int(selected_record.get("imported_count") or 0)
        total_amount = outsource_payment_amount(imported_count, unit_price)
        st.metric(
            "領収書金額",
            f"{total_amount:,}円",
            f"{imported_count:,}件 × {int(unit_price):,}円",
        )

        receipt_html = build_outsource_receipt_html(
            selected_record,
            worker_name,
            payer_name,
            int(unit_price),
            issue_date,
            receipt_note,
            payment_status,
        )
        save_receipt_col, download_receipt_col = st.columns(2)
        if save_receipt_col.button(
            "領収書情報を保存",
            key=f"save_outsource_receipt_{record_id}",
            width="stretch",
        ):
            save_setting("OUTSOURCE_DEFAULT_WORKER_NAME", worker_name.strip())
            save_setting("OUTSOURCE_DEFAULT_UNIT_PRICE_YEN", str(int(unit_price)))
            save_setting("OUTSOURCE_RECEIPT_PAYER_NAME", payer_name.strip())
            update_outsource_import_receipt(
                record_id,
                worker_name,
                int(unit_price),
                receipt_note,
                payment_status,
                issue_date.isoformat(),
            )
            st.success("領収書情報を保存しました。")
            st.rerun()
        download_receipt_col.download_button(
            "領収書HTMLをダウンロード",
            data=receipt_html.encode("utf-8-sig"),
            file_name=outsource_receipt_file_name(record_id, issue_date),
            mime="text/html",
            width="stretch",
        )


def main() -> None:
    st.set_page_config(page_title="Creator Outreach Mailer", layout="wide")
    inject_loading_indicator()
    inject_mail_preview_styles()
    init_db()

    if not require_login():
        return

    require_active_subscription()
    load_app_state_from_supabase()
    ensure_default_campaign_template()
    sync_send_queue_results()
    sync_unsubscribes_from_supabase()
    cleanup_blocked_targets_for_existing_contacts()
    process_due_send_queue_from_streamlit()

    st.title("Creator Outreach Mailer")
    st.caption("許諾済みの宛先だけに、1件ずつ送信する個人用Webアプリ")
    render_login_status_bar()
    render_app_state_sync_panel()

    if smtp_configured():
        st.success("SMTP設定あり: 実送信できます")
    else:
        st.warning("SMTP未設定: 送信操作は記録のみのテストモードです")

    send_booking_notice = st.session_state.pop("send_booking_notice", "")
    if send_booking_notice:
        st.success(send_booking_notice)
        st.caption("送信予約の作成後、進捗確認と送信処理をすぐ開始できるように画面を更新しました。")

    st.info(
        "営業メールは、送信先の国や地域のルールに従ってください。"
        "日本では広告宣伝メールは原則オプトインです。"
    )

    left, right = st.columns([0.75, 1.75], gap="large")

    with left:
        settings_panel()
        st.divider()

        st.subheader("宛先を追加")
        with st.form("add_contact", clear_on_submit=True):
            email = st.text_input("メールアドレス")
            channel = st.text_input("チャンネル名", placeholder="例: Sample Channel")
            memo = st.text_input("メモ", placeholder="例: 返信早め / 案件候補 / 要確認")
            consent = st.checkbox("営業メール送信の許諾がある")
            submitted = st.form_submit_button("追加")
        if submitted:
            if email:
                normalized_email = email.strip().lower()
                blocked_reason = blocked_target_reason(normalized_email)
                if "restore_blocked_email" not in st.session_state:
                    st.session_state["restore_blocked_email"] = ""
                    st.session_state["restore_blocked_memo"] = ""
                    st.session_state["restore_blocked_channel"] = ""
                    st.session_state["restore_blocked_consent"] = False
                was_added = add_contact(email, memo, channel, consent)
                if was_added:
                    st.success("宛先を追加しました")
                elif blocked_reason:
                    st.session_state["restore_blocked_email"] = normalized_email
                    st.session_state["restore_blocked_memo"] = memo
                    st.session_state["restore_blocked_channel"] = channel
                    st.session_state["restore_blocked_consent"] = consent
                    st.warning(
                        "このメールアドレスは以前に登録され、配信停止または削除されています。"
                        "再度、宛先一覧に戻す場合は下のボタンを押してください。"
                    )
                    st.caption(f"記録理由: {blocked_reason}")
                else:
                    st.warning("このメールアドレスはすでに登録されています")
            else:
                st.error("メールアドレスを入力してください")
        restore_email = st.session_state.get("restore_blocked_email", "")
        if restore_email:
            st.info(f"{restore_email} を宛先一覧に戻しますか？")
            restore_yes_col, restore_no_col = st.columns(2)
            if restore_yes_col.button("はい、再登録する", key="confirm_restore_blocked_email", width="stretch"):
                unblock_target(restore_email)
                restored = add_contact(
                    restore_email,
                    st.session_state.get("restore_blocked_memo", ""),
                    st.session_state.get("restore_blocked_channel", ""),
                    bool(st.session_state.get("restore_blocked_consent", False)),
                )
                st.session_state["restore_blocked_email"] = ""
                if restored:
                    st.success("宛先一覧に戻しました")
                    st.rerun()
                else:
                    st.error("再登録できませんでした。すでに宛先一覧にある可能性があります。")
            if restore_no_col.button("いいえ、戻さない", key="cancel_restore_blocked_email", width="stretch"):
                st.session_state["restore_blocked_email"] = ""
                st.rerun()

        st.subheader("ファイル取り込み")
        uploaded = st.file_uploader("CSV / Excelファイル", type=["csv", "tsv", "xlsx", "xls"])
        st.caption("email / メールアドレス、channel / チャンネル名、memo / メモ などの列名を自動判別します。取り込んだ宛先は自動的に送信可になります。")
        if uploaded and st.button("取り込む"):
            try:
                added, skipped, mapping = import_contacts_file(uploaded)
                st.success(f"{added}件を取り込みました。重複や空欄は{skipped}件スキップしました。")
                st.caption(
                    f"判別した列: email={mapping['email'] or '-'} / "
                    f"channel={mapping['channel'] or '-'} / memo={mapping['memo'] or '-'}"
                )
                show_candidate_import_cleanup(mapping)
                if int(mapping.get("candidate_removed") or 0):
                    refreshed_message = refresh_outsource_sheet_if_possible()
                    if refreshed_message:
                        st.caption(refreshed_message)
            except Exception as exc:
                st.error(str(exc))

        with st.expander("Googleスプレッドシート / ドキュメントURLから取り込む"):
            google_contacts_url = st.text_input(
                "GoogleファイルのURL",
                placeholder="Googleスプレッドシート、またはGoogleドキュメントのURL",
                key="google_contacts_url",
            )
            st.caption(
                "Google側の共有設定を「リンクを知っている全員が閲覧可」にしてください。"
                "スプレッドシートは列名と中身から自動判別し、ドキュメントは本文中のメールアドレスを抽出します。"
            )
            if st.button(
                "URLから取り込む",
                key="import_google_contacts_url",
                width="stretch",
                disabled=not google_contacts_url.strip(),
                on_click=queue_google_contacts_url_import,
            ):
                target_google_contacts_url = str(st.session_state.pop("pending_google_contacts_url", "")).strip()
                try:
                    added, skipped, mapping, source_type = import_contacts_google_url(target_google_contacts_url)
                    st.success(f"{source_type}から{added}件を取り込みました。重複や空欄は{skipped}件スキップしました。")
                    st.caption(
                        f"判別した項目: email={mapping['email'] or '-'} / "
                        f"channel={mapping['channel'] or '-'} / memo={mapping['memo'] or '-'}"
                    )
                    show_candidate_import_cleanup(mapping)
                    if int(mapping.get("candidate_removed") or 0):
                        refreshed_message = refresh_outsource_sheet_if_possible()
                        if refreshed_message:
                            st.caption(refreshed_message)
                except Exception as exc:
                    st.error(str(exc))

        st.subheader("YouTube候補検索")
        st.caption("メールアドレスは取得しません。条件に合うチャンネル候補だけを保存します。")
        yt_search_mode = st.radio("検索方法", ["カテゴリー", "キーワード"], horizontal=True)
        yt_category_name = ""
        yt_category_id = ""
        if yt_search_mode == "カテゴリー":
            yt_category_name = st.selectbox("カテゴリー", options=list(YOUTUBE_VIDEO_CATEGORIES.keys()))
            yt_category_id = YOUTUBE_VIDEO_CATEGORIES[yt_category_name]
            yt_keyword = st.text_input("補助キーワード（任意）", placeholder="例: 初心者 / 日本 / レビュー")
            st.caption("カテゴリー検索は、チャンネル自体ではなく、そのカテゴリーの人気動画を出しているチャンネルを候補化します。補助キーワードを入れると動画タイトル・説明文・チャンネル名で絞り込みます。")
        else:
            yt_keyword = st.text_input("検索キーワード", placeholder="例: 料理 レシピ / ゲーム実況 / 英会話")
        yt_min_subs = st.number_input("登録者数 最小", min_value=0, value=1000, step=1000)
        yt_max_subs = st.number_input("登録者数 最大（0なら上限なし）", min_value=0, value=100000, step=1000)
        yt_max_results = st.number_input("最大取得件数", min_value=1, max_value=200, value=50)
        daily_limit = get_youtube_daily_limit()
        used_units = get_youtube_units_used()
        estimated_units = estimate_youtube_units(int(yt_max_results), yt_search_mode)
        remaining_units = max(0, daily_limit - used_units)
        usage_ratio = min(1.0, used_units / daily_limit)
        st.progress(usage_ratio)
        st.caption(
            f"YouTube API使用量（概算）: 今日 {used_units:,} / {daily_limit:,} units、"
            f"残り目安 {remaining_units:,} units、今回予定 約{estimated_units:,} units"
        )
        st.caption("目安: キーワード検索は50件ごとに約101 unitsです。カテゴリー検索は人気動画から拾う方式なので50件ごとに約2 unitsです。")
        if used_units >= daily_limit:
            st.error("今日の推定上限に達しています。Google側のリセット後に再度試してください。")
        elif used_units + estimated_units > daily_limit:
            st.warning("この検索を実行すると、今日の推定上限を超える可能性があります。取得件数を減らしてください。")
        elif used_units / daily_limit >= 0.8:
            st.warning("YouTube API使用量が上限に近づいています。")
        yt_submitted = st.button("候補を検索して保存")
        if yt_submitted:
            if yt_search_mode == "キーワード" and not yt_keyword.strip():
                st.error("検索キーワードを入力してください")
            elif get_youtube_units_used() + estimate_youtube_units(int(yt_max_results), yt_search_mode) > get_youtube_daily_limit():
                st.error("推定上限を超えるため検索を止めました。最大取得件数を減らすか、明日以降に実行してください。")
            else:
                try:
                    checked, saved, units_used = search_youtube_channels(
                        yt_keyword.strip(),
                        int(yt_min_subs),
                        int(yt_max_subs),
                        int(yt_max_results),
                        yt_search_mode,
                        yt_category_id,
                        f"カテゴリー: {yt_category_name}" if yt_search_mode == "カテゴリー" else yt_keyword.strip(),
                    )
                    if checked == 0:
                        st.warning(
                            "YouTube側で該当候補が見つかりませんでした。"
                            "別カテゴリー、またはキーワード検索で再度試してください。"
                        )
                    else:
                        st.success(f"{checked}件を確認し、新規候補を{saved}件保存しました。推定使用量: {units_used} units")
                except Exception as exc:
                    st.error(str(exc))

    with right:
        st.subheader("メール作成")
        current_campaign_name = get_setting("CURRENT_CAMPAIGN_NAME", DEFAULT_CAMPAIGN_NAME)
        current_template = get_campaign_template(current_campaign_name)
        if (
            current_template
            and "campaign_name_input" not in st.session_state
            and "loaded_campaign_template" not in st.session_state
        ):
            load_campaign_template_into_session(current_campaign_name)
        if "campaign_name_input" not in st.session_state:
            st.session_state["campaign_name_input"] = current_template["name"] if current_template else current_campaign_name
        if "subject_template_input" not in st.session_state:
            st.session_state["subject_template_input"] = current_template["subject"] if current_template else DEFAULT_CAMPAIGN_SUBJECT
        if "body_template_input" not in st.session_state:
            st.session_state["body_template_input"] = current_template["body"] if current_template else DEFAULT_CAMPAIGN_BODY

        templates = fetch_campaign_templates()
        template_names = [template["name"] for template in templates]
        scenario_template_names = fetch_template_names_used_in_scenarios()
        saved_template_names = [name for name in template_names if name.strip() not in scenario_template_names]
        if current_campaign_name.strip() in scenario_template_names:
            current_campaign_name = saved_template_names[0] if saved_template_names else ""
            save_setting("CURRENT_CAMPAIGN_NAME", current_campaign_name)
            if current_campaign_name:
                fallback_template = get_campaign_template(current_campaign_name)
                if fallback_template:
                    reset_campaign_template_session(
                        fallback_template["name"],
                        fallback_template["subject"],
                        fallback_template["body"],
                    )
            else:
                reset_campaign_template_session("", "", "")
        if saved_template_names:
            if st.session_state.get("saved_campaign_template_select") not in saved_template_names:
                st.session_state.pop("saved_campaign_template_select", None)
            selected_index = saved_template_names.index(current_campaign_name) if current_campaign_name in saved_template_names else 0
            selected_template = st.selectbox(
                "保存済み配信",
                saved_template_names,
                index=selected_index,
                key="saved_campaign_template_select",
            )
        else:
            selected_template = ""
            st.session_state.pop("saved_campaign_template_select", None)
            if template_names and scenario_template_names:
                st.info("通常配信用の保存済み配信はありません。シナリオに含まれているテンプレートは、ここでは非表示にしています。")
            else:
                st.info("保存済み配信はまだありません。新しいテンプレートを作成してください。")
        st.caption("保存済みのテンプレートを選んで「読み込む」と、下の件名・本文に反映されます。シナリオに含まれるテンプレートは通常配信側では非表示になります。")
        load_col, new_col, save_col, delete_col = st.columns(4)
        if load_col.button("読み込む", key="load_campaign_template", width="stretch", disabled=not selected_template):
            if load_campaign_template_into_session(selected_template):
                save_setting("CURRENT_CAMPAIGN_NAME", selected_template)
                st.success(f"{selected_template} を読み込みました")
        if new_col.button("新しいテンプレートを作る", key="new_campaign_template", width="stretch"):
            reset_campaign_template_session("", "", "")
            save_setting("CURRENT_CAMPAIGN_NAME", "")
            st.session_state["confirm_delete_campaign_template"] = ""
            st.success("新しいテンプレートを作成できます。配信名、件名、本文を入力して保存してください。")
        if delete_col.button("このテンプレートを削除", key="delete_campaign_template", width="stretch", disabled=not selected_template):
            st.session_state["confirm_delete_campaign_template"] = selected_template
        pending_delete_template = st.session_state.get("confirm_delete_campaign_template", "")
        if pending_delete_template:
            st.warning(f"配信テンプレート「{pending_delete_template}」を削除しますか？この操作は元に戻せません。")
            confirm_delete_col, cancel_delete_col = st.columns(2)
            if confirm_delete_col.button("はい、削除する", key="confirm_delete_campaign_template_yes", width="stretch"):
                delete_campaign_template(pending_delete_template)
                st.session_state["confirm_delete_campaign_template"] = ""
                remaining_templates = fetch_campaign_templates()
                if remaining_templates:
                    first_template = remaining_templates[0]
                    save_setting("CURRENT_CAMPAIGN_NAME", first_template["name"])
                    reset_campaign_template_session(first_template["name"], first_template["subject"], first_template["body"])
                else:
                    save_setting("CURRENT_CAMPAIGN_NAME", "")
                    reset_campaign_template_session("", "", "")
                st.success(f"{pending_delete_template} を削除しました")
                st.rerun()
            if cancel_delete_col.button("いいえ、削除しない", key="confirm_delete_campaign_template_no", width="stretch"):
                st.session_state["confirm_delete_campaign_template"] = ""
                st.rerun()
        if len(template_names) > 1:
            with st.expander("配信テンプレートの並び替え"):
                if sort_items:
                    vertical_sort_style = """
                    .sortable-component {
                        border: 1px solid #E5E7EB;
                        border-radius: 6px;
                        padding: 8px;
                    }
                    .sortable-container-body {
                        display: flex;
                        flex-direction: column;
                        gap: 8px;
                    }
                    .sortable-item, .sortable-item:hover {
                        display: block;
                        width: 100%;
                        box-sizing: border-box;
                        background-color: #F8FAFC;
                        border: 1px solid #CBD5E1;
                        border-radius: 6px;
                        padding: 10px 12px;
                        color: #111827;
                    }
                    .sortable-item::before {
                        content: "↕ ";
                        color: #64748B;
                    }
                    """
                    sorted_template_names = sort_items(
                        template_names,
                        key=campaign_template_list_key(template_names),
                        custom_style=vertical_sort_style,
                    )
                    if sorted_template_names != template_names:
                        if st.button("この順番で保存", width="stretch"):
                            save_campaign_template_order(sorted_template_names)
                            st.success("並び順を保存しました")
                            st.rerun()
                else:
                    st.caption("ドラッグで並び替えるには、依存パッケージの反映後にアプリを再起動してください。")
        if template_names:
            normal_template_names = [name for name in template_names if name.strip() not in scenario_template_names]
            with st.expander("配信テンプレートごとの成績"):
                st.caption("通常配信用テンプレートの送信成功・失敗・送信待ち・配信停止を確認できます。シナリオに含まれるテンプレートは、下の「シナリオごとの成績」で確認できます。")
                if normal_template_names:
                    st.dataframe(
                        fetch_campaign_template_stats(normal_template_names),
                        width="stretch",
                        hide_index=True,
                    )
                else:
                    st.write("通常配信用のテンプレートはありません。シナリオに含まれるテンプレートは「シナリオごとの成績」で確認してください。")
        if template_names:
            scenarios = fetch_scenarios()
            with st.expander("シナリオ設定"):
                st.caption("テンプレートの並び順とは別に、ステップメールの順番を固定できます。最初は10通分を表示し、必要なら11通目以降も追加できます。")
                if st.session_state.pop("_force_new_scenario_editor", False):
                    st.session_state.pop("scenario_editor_select", None)
                reset_scenario_key = st.session_state.pop("_reset_scenario_editor_keys", "")
                if reset_scenario_key:
                    st.session_state.pop(f"scenario_name_input_{reset_scenario_key}", None)
                    step_count_key = f"scenario_step_count_{reset_scenario_key}"
                    step_count = int(st.session_state.get(step_count_key, 10))
                    for step_number in range(1, max(10, step_count) + 1):
                        st.session_state.pop(f"scenario_step_{reset_scenario_key}_{step_number}", None)
                    st.session_state.pop(step_count_key, None)
                scenario_options = ["新しく作る"] + [scenario["name"] for scenario in scenarios]
                selected_scenario_name = st.selectbox("編集するシナリオ", scenario_options, key="scenario_editor_select")
                selected_scenario = None
                selected_scenario_steps = []
                if selected_scenario_name != "新しく作る":
                    selected_scenario = next((scenario for scenario in scenarios if scenario["name"] == selected_scenario_name), None)
                    if selected_scenario:
                        selected_scenario_steps = fetch_scenario_steps(int(selected_scenario["id"]))
                used_template_names = fetch_template_names_used_in_scenarios(
                    int(selected_scenario["id"]) if selected_scenario else None
                )
                selectable_template_names = [
                    template_name
                    for template_name in template_names
                    if template_name not in used_template_names
                ]
                if selected_scenario:
                    st.caption("他のシナリオで使われているテンプレートは候補から外しています。")
                elif used_template_names:
                    st.caption("すでに他のシナリオで使われているテンプレートは候補に出ません。")
                if not selectable_template_names:
                    st.info("未使用のテンプレートがありません。新しいテンプレートを作るか、既存シナリオから外してから選んでください。")
                scenario_name_input = st.text_input(
                    "シナリオ名",
                    value=selected_scenario["name"] if selected_scenario else "",
                    placeholder="例: 初回営業シナリオ",
                    key=f"scenario_name_input_{selected_scenario_name}",
                )
                existing_step_map = {
                    int(step["step_number"]): step["template_name"]
                    for step in selected_scenario_steps
                }
                step_count_key = f"scenario_step_count_{selected_scenario_name}"
                if step_count_key not in st.session_state:
                    st.session_state[step_count_key] = max(10, len(existing_step_map))
                step_count = int(st.session_state.get(step_count_key, 10))
                step_values = []
                for step_number in range(1, step_count + 1):
                    default_template = existing_step_map.get(step_number, "")
                    step_options = selectable_template_names
                    if default_template and default_template not in step_options:
                        step_options = [default_template] + step_options
                    default_index = step_options.index(default_template) + 1 if default_template in step_options else 0
                    step_template = st.selectbox(
                        f"{step_number}通目",
                        ["使わない"] + step_options,
                        index=default_index,
                        key=f"scenario_step_{selected_scenario_name}_{step_number}",
                    )
                    if step_template != "使わない":
                        step_values.append(step_template)
                add_step_col, step_note_col = st.columns([1.0, 2.0])
                if add_step_col.button("ステップを追加", key=f"add_scenario_step_{selected_scenario_name}", width="stretch"):
                    st.session_state[step_count_key] = step_count + 1
                    st.rerun()
                step_note_col.caption(f"現在 {step_count}通目まで表示しています。不要なステップは「使わない」のままで大丈夫です。")
                scenario_save_col, scenario_delete_col = st.columns(2)
                if scenario_save_col.button("シナリオを保存", key=f"save_scenario_{selected_scenario_name}", width="stretch"):
                    if not scenario_name_input.strip():
                        st.error("シナリオ名を入力してください")
                    elif not step_values:
                        st.error("1通目以降に使うテンプレートを選んでください")
                    else:
                        save_scenario(scenario_name_input, step_values)
                        st.success(f"シナリオ「{scenario_name_input}」を保存しました")
                        st.session_state["_reset_scenario_editor_keys"] = selected_scenario_name
                        st.session_state["_force_new_scenario_editor"] = True
                        st.rerun()
                if selected_scenario and scenario_delete_col.button("このシナリオを削除", key=f"delete_scenario_{selected_scenario['id']}", width="stretch"):
                    delete_scenario(int(selected_scenario["id"]))
                    st.success(f"シナリオ「{selected_scenario_name}」を削除しました")
                    st.rerun()
                if selected_scenario and selected_scenario_steps:
                    st.divider()
                    st.caption(
                        "シナリオに組み込んだテンプレートを編集できます。"
                        "ここで本文を直しても、シナリオIDとステップ番号は変わらないため、送信済み判定は引き継がれます。"
                    )
                    edit_step_options = [
                        f"{step['step_number']}通目: {step['template_name']}"
                        for step in selected_scenario_steps
                    ]
                    selected_edit_step_label = st.selectbox(
                        "編集するステップ",
                        edit_step_options,
                        key=f"scenario_template_edit_step_{selected_scenario['id']}",
                    )
                    selected_edit_step = selected_scenario_steps[edit_step_options.index(selected_edit_step_label)]
                    edit_template_name = str(selected_edit_step["template_name"] or "")
                    edit_template = get_campaign_template(edit_template_name)
                    if not edit_template:
                        st.warning("このステップのテンプレートが見つかりません。テンプレートを選び直してシナリオを保存してください。")
                    else:
                        usage_count = sum(1 for step in rows(
                            """
                            select template_name
                            from scenario_steps
                            where user_id = ? and template_name = ?
                            """,
                            (current_user_id(), edit_template_name),
                        ))
                        st.text_input(
                            "テンプレート名",
                            value=edit_template_name,
                            disabled=True,
                            key=f"scenario_template_name_preview_{selected_scenario['id']}_{selected_edit_step['step_number']}",
                        )
                        if usage_count > 1:
                            st.caption(f"このテンプレートは他のステップ/シナリオでも使われています。保存すると同じテンプレートを使う箇所にも反映されます。")
                        edit_subject = st.text_input(
                            "件名",
                            value=str(edit_template["subject"] or ""),
                            key=f"scenario_template_subject_{selected_scenario['id']}_{selected_edit_step['step_number']}_{edit_template['id']}",
                        )
                        edit_body = st.text_area(
                            "本文",
                            value=str(edit_template["body"] or ""),
                            height=360,
                            key=f"scenario_template_body_{selected_scenario['id']}_{selected_edit_step['step_number']}_{edit_template['id']}",
                        )
                        if st.button(
                            "このステップのテンプレートを更新",
                            key=f"save_scenario_step_template_{selected_scenario['id']}_{selected_edit_step['step_number']}_{edit_template['id']}",
                            width="stretch",
                        ):
                            save_campaign_template(edit_template_name, edit_subject, edit_body)
                            st.success(
                                f"{selected_edit_step['step_number']}通目のテンプレートを更新しました。"
                                "シナリオの送信済み判定キーは変えていません。"
                            )
                            st.rerun()
            if scenarios:
                with st.expander("シナリオごとの成績"):
                    st.caption("シナリオを選ぶと、その中に入っている各テンプレートの送信成功・失敗・送信待ち・配信停止を確認できます。")
                    scenario_stat_labels = [scenario["name"] for scenario in scenarios]
                    selected_stat_scenario_name = st.selectbox(
                        "成績を見るシナリオ",
                        scenario_stat_labels,
                        key="scenario_stats_select",
                    )
                    selected_stat_scenario = next(
                        (scenario for scenario in scenarios if scenario["name"] == selected_stat_scenario_name),
                        None,
                    )
                    if selected_stat_scenario:
                        scenario_step_stats = fetch_scenario_step_stats(int(selected_stat_scenario["id"]))
                        if scenario_step_stats.empty:
                            st.write("このシナリオには、まだテンプレートが登録されていません。")
                        else:
                            st.dataframe(
                                scenario_step_stats,
                                width="stretch",
                                hide_index=True,
                            )
        scenarios_for_send = fetch_scenarios()
        send_mode = "通常配信"
        if scenarios_for_send:
            send_mode = st.radio("送信方式", ["通常配信", "シナリオ配信"], horizontal=True, key="send_mode")

        campaign_name = str(st.session_state.get("campaign_name_input", ""))
        subject_template = str(st.session_state.get("subject_template_input", ""))
        body_template = str(st.session_state.get("body_template_input", ""))
        effective_campaign_name = campaign_name
        effective_campaign_key = campaign_key(campaign_name)
        effective_subject_template = subject_template
        effective_body_template = body_template
        unsubscribe_scope = UNSUBSCRIBE_SCOPE_CAMPAIGN
        unsubscribe_scope_key = effective_campaign_key
        unsubscribe_scope_label = normal_campaign_scope_label(effective_campaign_name)
        prerequisite_campaign_keys: list[str] = []
        later_step_campaign_keys: list[str] = []
        scenario_context = ""
        scenario_full_auto = False
        scenario_full_steps: list[sqlite3.Row] = []
        scenario_step_gap_days = 1
        send_scenario = None
        if send_mode == "シナリオ配信":
            scenario_labels = [scenario["name"] for scenario in scenarios_for_send]
            scenario_label = st.selectbox("送信するシナリオ", scenario_labels, key="send_scenario_select")
            send_scenario = next((scenario for scenario in scenarios_for_send if scenario["name"] == scenario_label), None)
            if send_scenario:
                send_steps = fetch_scenario_steps(int(send_scenario["id"]))
                if not send_steps:
                    st.warning("このシナリオにはステップがありません。シナリオ設定でテンプレートを割り当ててください。")
                else:
                    scenario_delivery_mode = st.radio(
                        "シナリオの予約範囲",
                        ["今回のステップだけ予約", "シナリオ全体を最後まで予約"],
                        horizontal=True,
                        key="scenario_delivery_mode",
                    )
                    scenario_full_auto = scenario_delivery_mode == "シナリオ全体を最後まで予約"
                    scenario_full_steps = send_steps if scenario_full_auto else []
                    step_labels = [f"{step['step_number']}通目: {step['template_name']}" for step in send_steps]
                    if scenario_full_auto:
                        selected_step_index = 0
                        selected_step = send_steps[0]
                    else:
                        selected_step_label = st.selectbox("今回送るステップ", step_labels, key="send_scenario_step_select")
                        selected_step_index = step_labels.index(selected_step_label)
                        selected_step = send_steps[selected_step_index]
                    selected_template_for_step = get_campaign_template(selected_step["template_name"])
                    prerequisite_campaign_keys = [
                        scenario_step_campaign_key(int(send_scenario["id"]), int(step["step_number"]))
                        for step in send_steps[:selected_step_index]
                    ]
                    later_step_campaign_keys = [
                        scenario_step_campaign_key(int(send_scenario["id"]), int(step["step_number"]))
                        for step in send_steps[selected_step_index + 1 :]
                    ]
                    effective_campaign_name = scenario_step_campaign_name(
                        send_scenario["name"],
                        int(selected_step["step_number"]),
                        selected_step["template_name"],
                    )
                    effective_campaign_key = scenario_step_campaign_key(
                        int(send_scenario["id"]),
                        int(selected_step["step_number"]),
                    )
                    unsubscribe_scope = UNSUBSCRIBE_SCOPE_SCENARIO
                    unsubscribe_scope_key = str(send_scenario["name"] or "").strip()
                    unsubscribe_scope_label = str(send_scenario["name"] or "").strip()
                    if selected_template_for_step:
                        effective_subject_template = selected_template_for_step["subject"]
                        effective_body_template = selected_template_for_step["body"]
                    if scenario_full_auto:
                        scenario_context = (
                            f"シナリオ「{send_scenario['name']}」を1通目から最後までまとめて予約します。"
                            "各ステップは、前ステップの全予約が終わってから次に進むため、1日の送信目標はシナリオ全体で守られます。"
                            "同じ宛先へ同じ日に複数ステップは送りません。"
                        )
                    else:
                        scenario_context = (
                            f"シナリオ「{send_scenario['name']}」の{selected_step['step_number']}通目です。"
                            f"{'前のステップを送信済みの宛先だけが対象です。' if prerequisite_campaign_keys else '1通目なので前のステップ条件はありません。'}"
                            "後ろのステップをすでに送っている宛先は、戻り送信を防ぐため対象外にします。"
                        )
                    st.info(scenario_context)
                    if scenario_full_auto:
                        st.caption(f"予約するステップ数: {len(send_steps)}通")
                        with st.expander("シナリオ全体で送る内容を確認", expanded=False):
                            for step in send_steps:
                                template = get_campaign_template(step["template_name"])
                                st.markdown(f"**{step['step_number']}通目: {step['template_name']}**")
                                if template:
                                    st.text_input(
                                        "件名",
                                        value=str(template["subject"] or ""),
                                        disabled=True,
                                        key=f"scenario_full_subject_{send_scenario['id']}_{step['step_number']}",
                                    )
                                    render_readonly_mail_body("本文", str(template["body"] or ""), min_height=320)
                                else:
                                    st.warning("このステップのテンプレートが見つかりません。")
                    else:
                        st.caption(f"このステップで使うテンプレート: {selected_step['template_name']}")
                        with st.expander("このステップで送る内容を確認", expanded=False):
                            st.text_input("配信名", value=effective_campaign_name, disabled=True, key="scenario_effective_campaign_name")
                            st.text_input("件名", value=effective_subject_template, disabled=True, key="scenario_effective_subject")
                            render_readonly_mail_body("本文", effective_body_template, min_height=460)
        else:
            st.caption("通常配信では、配信名ごとに送信済み・送信待ちを判定します。")
            campaign_name = st.text_input("配信名", key="campaign_name_input")
            st.caption("同じ配信名の間は、本文を少し直しても同じ配信として進捗を引き継ぎます。新しい別メールを送る時だけ配信名を変えてください。")
            subject_template = st.text_input("件名", key="subject_template_input")
            body_template = st.text_area("本文", height=260, key="body_template_input")
            effective_campaign_name = campaign_name
            effective_campaign_key = campaign_key(campaign_name)
            effective_subject_template = subject_template
            effective_body_template = body_template
            unsubscribe_scope = UNSUBSCRIBE_SCOPE_CAMPAIGN
            unsubscribe_scope_key = effective_campaign_key
            unsubscribe_scope_label = normal_campaign_scope_label(effective_campaign_name)
            if save_col.button("保存 / 更新", key="save_campaign_template", width="stretch"):
                if campaign_name.strip():
                    save_campaign_template(campaign_name, subject_template, body_template)
                    save_setting("CURRENT_CAMPAIGN_NAME", campaign_name.strip())
                    reset_campaign_template_session(campaign_name.strip(), subject_template, body_template)
                    st.success(f"{campaign_name} を保存しました")
                else:
                    st.error("配信名を入力してください")
        current_campaign_key = effective_campaign_key
        if unsubscribe_scope == UNSUBSCRIBE_SCOPE_CAMPAIGN:
            unsubscribe_scope_key = current_campaign_key
            unsubscribe_scope_label = normal_campaign_scope_label(effective_campaign_name)
        estimated_remaining_count = count_next_send_contacts(
            current_campaign_key,
            prerequisite_campaign_keys,
            later_step_campaign_keys,
            unsubscribe_scope,
            unsubscribe_scope_key,
        )
        window_col_start, window_col_end = st.columns(2)
        send_window_start = window_col_start.time_input(
            "メールを送ってよい時間（この時間から）",
            value=datetime_time(10, 0),
            step=1800,
        )
        send_window_end = window_col_end.time_input(
            "メールを送ってよい時間（この時間まで）",
            value=datetime_time(18, 0),
            step=1800,
        )
        if send_window_end <= send_window_start:
            st.warning("メールを送ってよい時間は、「この時間まで」を「この時間から」より後にしてください。")
        st.caption("この時間帯の外では送信しません。時間を超えた分は、翌日の「この時間から」に自動で持ち越します。")
        st.caption(f"時刻は日本時間（東京）で扱います。現在の日本時間: {datetime.now(APP_TIMEZONE).strftime('%Y-%m-%d %H:%M')}")

        send_pace_mode = st.radio(
            "送信ペース",
            ["1日の目標件数で決める", "送信間隔を直接指定"],
            horizontal=True,
            key="send_pace_mode",
        )
        if send_pace_mode == "1日の目標件数で決める":
            daily_target = st.number_input(
                "1日の目標送信数",
                min_value=50,
                max_value=1500,
                value=500,
                step=50,
                key="daily_send_target",
            )
            delay = delay_for_daily_target(send_window_start, send_window_end, int(daily_target))
            daily_capacity = daily_send_capacity(send_window_start, send_window_end, int(delay))
            st.info(
                f"この時間帯で1日約{daily_capacity:,}件にするため、"
                f"送信間隔は自動で「{format_delay_seconds(int(delay))}に1通」にします。"
            )
        else:
            delay = st.number_input("送信間隔（秒）", min_value=30, max_value=3600, value=90, step=10)
            daily_capacity = daily_send_capacity(send_window_start, send_window_end, int(delay))
            st.info(
                f"この設定だと、1日最大で約{daily_capacity:,}件送れます。"
                f"送信間隔は「{format_delay_seconds(int(delay))}に1通」です。"
            )

        if int(daily_capacity) > 800:
            st.warning("1日の送信数が多めです。最初は500〜600件くらいから始め、失敗や迷惑メール判定が増えないか確認するのがおすすめです。")

        if scenario_full_auto:
            scenario_step_gap_days = st.number_input(
                "次のステップまで空ける日数",
                min_value=1,
                max_value=30,
                value=3,
                step=1,
                key="scenario_full_step_gap_days",
            )
            st.caption(
                "シナリオ全体予約では、1ステップ目を予約し終えてから指定日数を空け、次のステップを予約します。"
                "1日の目標送信数は全ステップ合計で守ります。"
            )

        reserve_all_remaining = st.checkbox(
            "このシナリオの未送信宛先をすべて予約する" if scenario_full_auto else "この配信の未送信をすべて予約する",
            value=False,
            disabled=int(estimated_remaining_count) <= 0,
            key="reserve_all_remaining_contacts",
        )
        if reserve_all_remaining:
            send_limit = max(1, int(estimated_remaining_count))
            st.caption(f"今回予約する宛先数: {send_limit:,}件")
        else:
            default_send_limit = max(1, min(int(estimated_remaining_count) if int(estimated_remaining_count) > 0 else 500, 500))
            send_limit = st.number_input(
                "今回予約する宛先数" if scenario_full_auto else "今回予約する総件数",
                min_value=1,
                max_value=10000,
                value=default_send_limit,
                step=50,
                key="send_limit_input",
            )

        scenario_booking_step_count = len(scenario_full_steps) if scenario_full_auto else 1
        estimated_planned_count = min(int(send_limit), int(estimated_remaining_count))
        estimated_message_count = estimated_planned_count * max(1, int(scenario_booking_step_count))
        if scenario_full_auto:
            estimated_schedules = build_scenario_send_schedules(
                estimated_planned_count,
                scenario_booking_step_count,
                int(delay),
                send_window_start,
                send_window_end,
                int(scenario_step_gap_days),
            )
            estimated_flat_schedule = flatten_schedules(estimated_schedules)
            estimated_days = schedule_calendar_days(estimated_flat_schedule)
            if estimated_planned_count > 0 and estimated_days > 0:
                st.caption(
                    f"この予約は、約{estimated_days}日でシナリオ全体が完了する見込みです"
                    f"（宛先 {estimated_planned_count:,}件 × {scenario_booking_step_count}ステップ = 合計 {estimated_message_count:,}通 / 1日 約{int(daily_capacity):,}通）。"
                )
        else:
            estimated_days = estimate_send_days(estimated_planned_count, int(daily_capacity))
            if estimated_planned_count > 0 and estimated_days > 0:
                st.caption(
                    f"この予約は、約{estimated_days}日で送信完了する見込みです"
                    f"（予約 {estimated_planned_count:,}件 / 1日 約{int(daily_capacity):,}件）。"
                )
        confirmed = st.checkbox("送信対象が許諾済み、または法的に送信可能な宛先であることを確認しました")

        target_count = rows(
            """
            select count(*) as count
            from contacts c
            where c.user_id = ?
              and c.consent = 1
              and c.unsubscribed = 0
              and c.email != ''
              and coalesce(c.contact_status, '送信対象') in ('未確認', 'メール確認済み', '送信対象')
              and not exists (
                  select 1
                  from unsubscribe_events ue
                  where ue.user_id = c.user_id
                    and ue.scope = 'global'
                    and (
                        (ue.contact_email != '' and ue.contact_email = lower(c.email))
                        or
                        (ue.youtube_channel_id != '' and ue.youtube_channel_id = c.youtube_channel_id)
                    )
              )
            """,
            (current_user_id(),),
        )[0]["count"]
        already_sent_count = rows(
            """
            select count(distinct contact_id) as count
            from sends
            where user_id = ? and campaign_key = ? and status = 'sent'
            """,
            (current_user_id(), current_campaign_key),
        )[0]["count"]
        queued_count = rows(
            """
            select count(distinct contact_id) as count
            from sends
            where user_id = ? and campaign_key = ? and status = 'queued'
            """,
            (current_user_id(), current_campaign_key),
        )[0]["count"]
        remaining_count = count_next_send_contacts(
            current_campaign_key,
            prerequisite_campaign_keys,
            later_step_campaign_keys,
            unsubscribe_scope,
            unsubscribe_scope_key,
        )
        prerequisite_waiting_count = count_waiting_for_prerequisites(
            current_campaign_key,
            prerequisite_campaign_keys,
            later_step_campaign_keys,
            unsubscribe_scope,
            unsubscribe_scope_key,
        )
        later_step_excluded_count = count_excluded_by_later_steps(
            current_campaign_key,
            prerequisite_campaign_keys,
            later_step_campaign_keys,
            unsubscribe_scope,
            unsubscribe_scope_key,
        )
        metric_cols = st.columns(4)
        metric_cols[0].metric("送信対象", f"{target_count}件")
        metric_cols[1].metric("1通目を送信済み" if scenario_full_auto else "この配信を送信済み", f"{already_sent_count}件")
        metric_cols[2].metric("送信待ち", f"{queued_count}件")
        metric_cols[3].metric("予約できる宛先" if scenario_full_auto else "この配信の未送信", f"{remaining_count}件")
        if prerequisite_waiting_count:
            st.warning(f"前のステップが未送信のため、{prerequisite_waiting_count}件は今回の対象から外れています。")
        if later_step_excluded_count:
            st.warning(f"後ろのステップを送信済み、または送信待ちのため、{later_step_excluded_count}件は今回の対象から外れています。")
        planned_count = min(int(send_limit), int(remaining_count))
        scenario_preview_schedules: list[list[datetime]] = []
        if scenario_full_auto:
            scenario_preview_schedules = build_scenario_send_schedules(
                planned_count,
                scenario_booking_step_count,
                int(delay),
                send_window_start,
                send_window_end,
                int(scenario_step_gap_days),
            )
            preview_schedule = flatten_schedules(scenario_preview_schedules)
        else:
            preview_schedule = build_send_schedule(
                planned_count,
                int(delay),
                send_window_start,
                send_window_end,
            )
        planned_message_count = planned_count * max(1, int(scenario_booking_step_count))
        if planned_count > 0 and preview_schedule:
            first_time = format_local_datetime(preview_schedule[0])
            last_time = format_local_datetime(preview_schedule[-1])
            total_minutes = max(1, int((preview_schedule[-1] - preview_schedule[0]).total_seconds() // 60) + 1)
            plan_days = schedule_calendar_days(preview_schedule) if scenario_full_auto else estimate_send_days(int(planned_count), int(daily_capacity))
            day_label = f" / 約{plan_days}日分" if plan_days else ""
            planned_label = f"{planned_count}件 × {scenario_booking_step_count}ステップ = {planned_message_count}通" if scenario_full_auto else f"{planned_count}件"
            st.info(
                f"送信予定: {planned_label} / 開始予定 {first_time} / 完了予定 {last_time} / "
                f"所要目安 約{total_minutes:,}分{day_label}"
            )
        elif planned_count > 0:
            st.warning("送信可能時間帯の設定を確認してください。終了時刻は開始時刻より後にしてください。")
        if remaining_count == 0 and target_count > 0:
            st.success("この配信名では、現在の送信対象すべてが送信済み、または送信待ちです。")
        if scenario_full_auto:
            st.caption("シナリオ全体予約では、1通目を送信済み・送信待ちの宛先、または後続ステップをすでに送っている宛先は除外します。")
        else:
            st.caption("同じ配信名ですでに送った宛先、または送信待ちの宛先は自動で除外します。送信対象は、未送信の宛先を優先し、その後は最終送信日時が古い順に選ばれます。")

        preview_contacts = fetch_next_send_contacts(
            current_campaign_key,
            1,
            prerequisite_campaign_keys,
            later_step_campaign_keys,
            0,
            unsubscribe_scope,
            unsubscribe_scope_key,
        ) if effective_campaign_name.strip() else []
        confirmation_page_size = 10
        confirmation_total_pages = max(1, (int(planned_count) + confirmation_page_size - 1) // confirmation_page_size)
        if "final_confirmation_page" not in st.session_state:
            st.session_state["final_confirmation_page"] = 1
        st.session_state["final_confirmation_page"] = max(
            1,
            min(int(confirmation_total_pages), int(st.session_state.get("final_confirmation_page", 1))),
        )
        confirmation_page = int(st.session_state["final_confirmation_page"])
        confirmation_offset = (confirmation_page - 1) * confirmation_page_size
        confirmation_contacts = (
            fetch_next_send_contacts(
                current_campaign_key,
                confirmation_page_size,
                prerequisite_campaign_keys,
                later_step_campaign_keys,
                confirmation_offset,
                unsubscribe_scope,
                unsubscribe_scope_key,
            )
            if effective_campaign_name.strip() and planned_count > 0
            else []
        )
        safety_messages = safety_check_messages(
            effective_subject_template,
            effective_body_template,
            int(planned_message_count),
            int(planned_message_count),
            bool(preview_contacts),
            int(daily_capacity),
        )
        if safety_messages:
            with st.expander(f"送信前安全チェック（{len(safety_messages)}件）", expanded=True):
                for message in safety_messages:
                    st.warning(message)
        with st.expander("送信前プレビュー", expanded=False):
            if not preview_contacts:
                st.write("プレビューできる送信対象がありません。宛先一覧、配信名、送信済み状況を確認してください。")
            else:
                preview_contact = preview_contacts[0]
                preview_unsubscribe_url = build_unsubscribe_url(
                    preview_contact,
                    unsubscribe_scope,
                    unsubscribe_scope_key,
                    unsubscribe_scope_label,
                )
                preview_unsubscribe_all_url = build_global_unsubscribe_url(preview_contact)
                preview_subject = render_template(effective_subject_template, preview_contact, preview_unsubscribe_url)
                preview_body = render_template(
                    ensure_unsubscribe_link_template(effective_body_template),
                    preview_contact,
                    preview_unsubscribe_url,
                    preview_unsubscribe_all_url,
                )
                st.caption(
                    f"送信対象の先頭1件で確認しています: "
                    f"{preview_contact['channel'] or '-'} / {preview_contact['email']}"
                )
                if scenario_full_auto:
                    st.caption("プレビューは1通目の内容です。2通目以降は「シナリオ全体で送る内容を確認」で確認できます。")
                st.text_input("プレビュー件名", value=preview_subject, disabled=True)
                render_readonly_mail_body("プレビュー本文", preview_body, min_height=520)

        with st.expander("送信前の最終確認", expanded=False):
            account = active_smtp_account()
            sender_label = smtp_mail_from(account).strip() or "未設定"
            finish_label = "-"
            start_label = "-"
            duration_label = "-"
            if planned_count > 0 and preview_schedule:
                start_label = format_local_datetime(preview_schedule[0])
                finish_label = format_local_datetime(preview_schedule[-1])
                duration_minutes = max(1, int((preview_schedule[-1] - preview_schedule[0]).total_seconds() // 60) + 1)
                duration_days = schedule_calendar_days(preview_schedule) if scenario_full_auto else estimate_send_days(int(planned_count), int(daily_capacity))
                duration_label = f"約{duration_minutes:,}分"
                if duration_days:
                    duration_label += f" / 約{duration_days}日"

            confirm_cols = st.columns(3)
            confirm_cols[0].metric("今回送信予約する件数", f"{planned_message_count}通" if scenario_full_auto else f"{planned_count}件")
            confirm_cols[1].metric("送信間隔", f"{format_delay_seconds(int(delay))}に1通")
            confirm_cols[2].metric("完了予定", finish_label)

            detail_rows = [
                {"確認項目": "配信名", "内容": f"{send_scenario['name']}｜シナリオ全体" if scenario_full_auto and send_scenario else effective_campaign_name.strip() or "-"},
                {"確認項目": "送信元", "内容": sender_label},
                {"確認項目": "件名", "内容": "各ステップの件名を使用" if scenario_full_auto else effective_subject_template.strip() or "-"},
                {"確認項目": "送信してよい時間", "内容": f"{send_window_start:%H:%M} から {send_window_end:%H:%M} まで"},
                {"確認項目": "1日の送信目安", "内容": f"約{int(daily_capacity):,}通"},
                {"確認項目": "開始予定", "内容": start_label},
                {"確認項目": "所要時間の目安", "内容": duration_label},
            ]
            if scenario_full_auto:
                detail_rows.extend(
                    [
                        {"確認項目": "予約宛先数", "内容": f"{planned_count}件"},
                        {"確認項目": "ステップ数", "内容": f"{scenario_booking_step_count}通"},
                        {"確認項目": "予約メール総数", "内容": f"{planned_message_count}通"},
                        {"確認項目": "次のステップまで", "内容": f"{int(scenario_step_gap_days)}日空ける"},
                        {"確認項目": "1通目を送信済み", "内容": f"{already_sent_count}件"},
                        {"確認項目": "1通目の送信待ち", "内容": f"{queued_count}件"},
                        {"確認項目": "予約できる宛先", "内容": f"{remaining_count}件"},
                    ]
                )
            else:
                detail_rows.extend(
                    [
                        {"確認項目": "この配信の送信済み", "内容": f"{already_sent_count}件"},
                        {"確認項目": "この配信の送信待ち", "内容": f"{queued_count}件"},
                        {"確認項目": "この配信の未送信", "内容": f"{remaining_count}件"},
                    ]
                )
            detail_frame = pd.DataFrame(detail_rows)
            st.dataframe(detail_frame, width="stretch", hide_index=True)

            if confirmation_contacts:
                st.caption("今回の選択候補です。実際の送信対象は、未送信優先・最終送信が古い順で選ばれます。10件ずつ確認できます。")
                page_col, prev_col, next_col = st.columns([2.0, 1.0, 1.0])
                page_col.caption(f"{confirmation_page}/{confirmation_total_pages}ページ（今回送信予定 {planned_count}件）")
                if prev_col.button(
                    "前の10件",
                    key="final_confirmation_prev_page",
                    width="stretch",
                    disabled=confirmation_page <= 1,
                ):
                    st.session_state["final_confirmation_page"] = max(1, confirmation_page - 1)
                    st.rerun()
                if next_col.button(
                    "次の10件",
                    key="final_confirmation_next_page",
                    width="stretch",
                    disabled=confirmation_page >= confirmation_total_pages,
                ):
                    st.session_state["final_confirmation_page"] = min(confirmation_total_pages, confirmation_page + 1)
                    st.rerun()
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "チャンネル名": contact["channel"] or "-",
                                "Eメール": contact["email"] or "-",
                                "メモ": contact["memo"] or "-",
                                "最終送信": contact["last_sent"] or "未送信",
                            }
                            for contact in confirmation_contacts
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.warning("今回送信予約できる宛先がありません。")
            final_confirmed = st.checkbox("上の送信内容・件数・送信元・時間帯を確認しました", key="final_send_confirmed")

        recent_jobs = fetch_recent_send_jobs(limit=20)
        if recent_jobs:
            mark_stale_empty_creating_jobs_failed(recent_jobs)
            active_jobs = [job for job in recent_jobs if is_active_send_job(job)]
            job_queue_summaries = {
                str(job.get("id") or ""): fetch_send_job_queue_summary(str(job.get("id") or ""))
                for job in recent_jobs
                if str(job.get("id") or "")
            }
            with st.expander(f"シナリオ・送信予約の進捗（稼働中{len(active_jobs)}件）", expanded=bool(active_jobs)):
                refresh_col, note_col = st.columns([1.0, 2.4])
                if refresh_col.button("状態を更新", width="stretch"):
                    process_due_send_queue_from_streamlit(force=True)
                    sync_send_queue_results()
                    st.rerun()
                note_col.caption("送信予約の進捗は30秒ごとに自動更新されます。この画面を開いている間は、予定時刻を過ぎた送信待ちも1通ずつ処理します。")
                cancel_notice = st.session_state.pop("send_job_cancel_notice", "")
                cancel_error = st.session_state.pop("send_job_cancel_error", "")
                if cancel_notice:
                    st.success(cancel_notice)
                if cancel_error:
                    st.error(cancel_error)
                st.markdown(
                    """
                    <style>
                    @keyframes refreshCountdown {
                        from { width: 100%; }
                        to { width: 0%; }
                    }
                    .refresh-countdown-wrap {
                        width: 100%;
                        height: 10px;
                        background: #E5E7EB;
                        border-radius: 999px;
                        overflow: hidden;
                        margin: 2px 0 8px;
                    }
                    .refresh-countdown-bar {
                        height: 100%;
                        background: #2563EB;
                        animation: refreshCountdown 30s linear forwards;
                    }
                    .refresh-countdown-text {
                        color: #64748B;
                        font-size: 0.85rem;
                        margin-bottom: 4px;
                    }
                    </style>
                    <div class="refresh-countdown-text">次の自動更新まで約30秒</div>
                    <div class="refresh-countdown-wrap">
                        <div class="refresh-countdown-bar"></div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st_autorefresh:
                    st_autorefresh(interval=30_000, key="send_jobs_autorefresh")
                else:
                    st.caption("自動更新部品の反映後は、30秒ごとに進捗が更新されます。")

                if active_jobs:
                    active_total = sum(send_job_count(job, "total_count") for job in active_jobs)
                    active_sent = sum(send_job_count(job, "sent_count") for job in active_jobs)
                    active_failed = sum(send_job_count(job, "failed_count") for job in active_jobs)
                    active_processed = sum(send_job_processed_count(job) for job in active_jobs)
                    active_progress = min(100.0, round(active_processed / active_total * 100, 1)) if active_total else 0.0
                    st.caption("メールアドレス単位のログではなく、シナリオ単位の進み具合を表示しています。")
                    summary_cols = st.columns(5)
                    summary_cols[0].metric("稼働中シナリオ", f"{len(active_jobs)}件")
                    summary_cols[1].metric("予約総数", f"{active_total:,}通")
                    summary_cols[2].metric("送信済み", f"{active_sent:,}通")
                    summary_cols[3].metric("失敗", f"{active_failed:,}通")
                    summary_cols[4].metric("全体進捗", f"{active_progress:.1f}%")

                    st.markdown("**稼働中のシナリオ**")
                    for job in active_jobs[:8]:
                        job_id = str(job.get("id") or "")
                        queue_summary = job_queue_summaries.get(job_id, {})
                        has_queue = bool(queue_summary.get("has_queue"))
                        next_pending_at = str(queue_summary.get("next_pending_at") or "")
                        sending_count = int(queue_summary.get("sending_count") or 0)
                        stale_sending_count = int(queue_summary.get("stale_sending_count") or 0)
                        overdue_pending = bool(queue_summary.get("overdue_pending"))
                        campaign_name_value = str(job.get("campaign_name") or "名称未設定")
                        progress_percent = send_job_progress_percent(job)
                        progress_ratio = min(1.0, max(0.0, progress_percent / 100))
                        st.write(f"**{campaign_name_value}**")
                        if next_pending_at:
                            st.caption(f"次の送信予定: {format_jst_datetime_compact(next_pending_at)}")
                        elif send_job_processed_count(job) < send_job_count(job, "total_count"):
                            if not has_queue:
                                st.error("送信予約の中身が見つかりません。予約作成中に中断された可能性があります。いったん予約を取消して、もう一度作り直してください。")
                            else:
                                st.warning("送信キューはありますが、次の送信待ちが見つかりません。処理中のまま止まっている可能性があります。")
                        if overdue_pending:
                            st.warning("予定時刻を過ぎた送信待ちがあります。この画面を開いている間は、アプリ側でも1通ずつ処理します。")
                        if stale_sending_count:
                            st.warning("送信処理中のまま止まった予約があります。「状態を更新」を押すと復旧して再開します。")
                        st.progress(progress_ratio)
                        progress_cols = st.columns([1.0, 1.0, 1.0, 1.0, 1.0, 1.2])
                        progress_cols[0].metric("進捗", f"{progress_percent:.1f}%")
                        progress_cols[1].metric("予約数", f"{send_job_count(job, 'total_count'):,}通")
                        progress_cols[2].metric("送信済み", f"{send_job_count(job, 'sent_count'):,}通")
                        progress_cols[3].metric("失敗", f"{send_job_count(job, 'failed_count'):,}通")
                        progress_cols[4].metric("処理中", f"{sending_count:,}通")
                        progress_cols[5].metric("状態", send_job_status_label(str(job.get("status") or "")))
                    if len(active_jobs) > 8:
                        st.caption(f"ほか{len(active_jobs) - 8}件の稼働中シナリオは下の一覧で確認できます。")
                else:
                    st.info("現在稼働中のシナリオはありません。過去の予約は下の一覧で確認できます。")

                st.caption("複数のシナリオを同時に予約できます。予約が重なった場合は、サーバー側の送信キューで予定時刻の古いものから順に処理されます。")
                jobs_frame = pd.DataFrame(recent_jobs)
                if not jobs_frame.empty:
                    jobs_display = jobs_frame.copy()
                    jobs_display["progress_percent"] = jobs_display.apply(lambda row: f"{send_job_progress_percent(row):.1f}%", axis=1)
                    jobs_display["success_percent"] = jobs_display.apply(lambda row: f"{send_job_success_percent(row):.1f}%", axis=1)
                    jobs_display["processed_count"] = jobs_display.apply(send_job_processed_count, axis=1)
                    jobs_display["status"] = jobs_display["status"].apply(send_job_status_label)
                    jobs_display["created_at_jst"] = jobs_display["created_at"].apply(format_jst_datetime_compact)
                    jobs_display["queue_state"] = jobs_display["id"].apply(
                        lambda value: "あり" if bool(job_queue_summaries.get(str(value), {}).get("has_queue")) else "なし"
                    )
                    jobs_display["next_pending_at"] = jobs_display["id"].apply(
                        lambda value: format_jst_datetime_compact(
                            str(job_queue_summaries.get(str(value), {}).get("next_pending_at") or "")
                        )
                    )
                    jobs_display["overdue_pending"] = jobs_display["id"].apply(
                        lambda value: "あり" if bool(job_queue_summaries.get(str(value), {}).get("overdue_pending")) else "なし"
                    )
                    jobs_display["sending_count"] = jobs_display["id"].apply(
                        lambda value: int(job_queue_summaries.get(str(value), {}).get("sending_count") or 0)
                    )
                    jobs_display["stale_sending_count"] = jobs_display["id"].apply(
                        lambda value: int(job_queue_summaries.get(str(value), {}).get("stale_sending_count") or 0)
                    )
                    st.dataframe(
                        jobs_display[
                            [
                                "campaign_name",
                                "total_count",
                                "processed_count",
                                "sent_count",
                                "failed_count",
                                "progress_percent",
                                "success_percent",
                                "status",
                                "queue_state",
                                "sending_count",
                                "stale_sending_count",
                                "created_at_jst",
                                "next_pending_at",
                                "overdue_pending",
                            ]
                        ].rename(
                            columns={
                                "campaign_name": "配信名",
                                "total_count": "予約数",
                                "processed_count": "処理済み",
                                "sent_count": "送信済み",
                                "failed_count": "失敗",
                                "progress_percent": "進捗",
                                "success_percent": "送信成功率",
                                "status": "状態",
                                "queue_state": "送信キュー",
                                "sending_count": "処理中",
                                "stale_sending_count": "停止中",
                                "created_at_jst": "作成日時",
                                "next_pending_at": "次の送信予定",
                                "overdue_pending": "予定時刻超過",
                            }
                        ),
                        width="stretch",
                        hide_index=True,
                    )

                cancelable_jobs = [job for job in recent_jobs if is_cancelable_send_job(job)]
                if cancelable_jobs:
                    st.caption("送信待ちの予約は取り消せます。取消した宛先は、未送信の状態に戻ります。すでに送信済みの宛先は戻せません。")
                    pending_cancel_job_id = str(st.session_state.get("confirm_cancel_send_job_id", ""))
                    header = st.columns([2.0, 0.9, 0.9, 0.9, 1.0, 1.1])
                    for column, label in zip(header, ["配信名", "予約数", "送信済み", "進捗", "状態", "操作"]):
                        column.markdown(f"**{label}**")
                    for job in cancelable_jobs:
                        job_id = str(job.get("id") or "")
                        columns = st.columns([2.0, 0.9, 0.9, 0.9, 1.0, 1.1])
                        columns[0].write(job.get("campaign_name") or "-")
                        columns[1].write(f"{send_job_count(job, 'total_count'):,}件")
                        columns[2].write(f"{send_job_count(job, 'sent_count'):,}件")
                        columns[3].write(f"{send_job_progress_percent(job):.1f}%")
                        columns[4].write(send_job_status_label(str(job.get("status") or "")))
                        if columns[5].button("予約を取消", key=f"request_cancel_send_job_{job_id}", width="stretch"):
                            st.session_state["confirm_cancel_send_job_id"] = job_id
                            st.rerun()

                    if pending_cancel_job_id:
                        pending_job = next(
                            (job for job in cancelable_jobs if str(job.get("id") or "") == pending_cancel_job_id),
                            None,
                        )
                        if pending_job:
                            st.warning(
                                f"送信予約「{pending_job.get('campaign_name') or '-'}」を取り消しますか？"
                                "送信待ちの宛先は未送信の状態に戻ります。"
                            )
                            yes_col, no_col = st.columns(2)
                            if yes_col.button("はい、取り消す", key=f"confirm_cancel_send_job_yes_{pending_cancel_job_id}", width="stretch"):
                                ok, message = cancel_send_job(pending_job)
                                st.session_state["confirm_cancel_send_job_id"] = ""
                                if ok:
                                    st.session_state["send_job_cancel_notice"] = message
                                else:
                                    st.session_state["send_job_cancel_error"] = message
                                st.rerun()
                            if no_col.button("いいえ、取り消さない", key=f"confirm_cancel_send_job_no_{pending_cancel_job_id}", width="stretch"):
                                st.session_state["confirm_cancel_send_job_id"] = ""
                                st.rerun()

        failed_sends = fetch_failed_sends()
        if not failed_sends.empty:
            with st.expander(f"送信失敗理由の一覧（直近{len(failed_sends)}件）"):
                st.caption("送信できなかった宛先だけを表示します。不要な宛先は削除して、今後取り込まないようにできます。")
                failed_summary = failed_sends.copy()
                failed_summary[["原因分類", "対応の目安"]] = failed_summary["error"].apply(
                    lambda error: pd.Series(classify_send_failure(error))
                )
                cause_counts = failed_summary["原因分類"].value_counts().reset_index()
                cause_counts.columns = ["原因分類", "件数"]
                st.dataframe(cause_counts, width="stretch", hide_index=True)

                header = st.columns([1.3, 1.8, 1.8, 1.8, 2.6, 1.2, 1.2])
                headers = ["チャンネル", "メールアドレス", "件名", "原因分類", "対応の目安", "日時", "操作"]
                for column, label in zip(header, headers):
                    column.markdown(f"**{label}**")
                for row in failed_sends.itertuples():
                    cause_label, action_hint = classify_send_failure(row.error)
                    columns = st.columns([1.3, 1.8, 1.8, 1.8, 2.6, 1.2, 1.2])
                    columns[0].write(row.channel or "-")
                    columns[1].write(row.email or "-")
                    columns[2].write(row.subject or "-")
                    columns[3].write(cause_label)
                    columns[4].write(action_hint)
                    columns[5].write(format_jst_datetime(row.sent_at) if row.sent_at else "-")
                    if row.contact_id and columns[6].button("削除して除外", key=f"delete_failed_send_{row.send_id}"):
                        delete_contact(int(row.contact_id), block=True, reason="送信失敗")
                        st.success(f"{row.email} を削除し、再取り込みしないようにしました")
                        st.rerun()

        send_history = fetch_send_history()
        with st.expander(f"詳細送信ログ（メールアドレスを含む・最新{len(send_history)}件）", expanded=False):
            if send_history.empty:
                st.write("まだ送信ログがありません。")
            else:
                st.caption("通常は上のシナリオ進捗だけ見れば大丈夫です。メールアドレス単位の確認や失敗調査が必要な時だけ開いてください。")
                history_metrics = st.columns(4)
                history_metrics[0].metric("送信済み", f"{int((send_history['status'] == 'sent').sum())}件")
                history_metrics[1].metric("送信待ち", f"{int((send_history['status'] == 'queued').sum())}件")
                history_metrics[2].metric("失敗", f"{int((send_history['status'] == 'failed').sum())}件")
                history_metrics[3].metric("合計", f"{len(send_history)}件")

                history_display = prepare_send_history_display(send_history)
                filter_cols = st.columns([1.5, 1.0, 1.0])
                history_keyword = filter_cols[0].text_input(
                    "送信ログを検索",
                    placeholder="メールアドレス、チャンネル名、配信名、件名で検索",
                    key="send_history_search",
                )
                history_status = filter_cols[1].selectbox(
                    "状態",
                    ["すべて", "送信済み", "送信待ち", "失敗"],
                    key="send_history_status_filter",
                )
                history_limit = filter_cols[2].selectbox(
                    "表示件数",
                    [20, 50, 100, 200, 500],
                    index=1,
                    key="send_history_limit",
                )

                filtered_history = history_display.copy()
                if history_status != "すべて":
                    filtered_history = filtered_history[filtered_history["状態"] == history_status]
                if history_keyword.strip():
                    keyword = history_keyword.strip().lower()
                    search_text = filtered_history.astype(str).agg(" ".join, axis=1).str.lower()
                    filtered_history = filtered_history[search_text.str.contains(re.escape(keyword), na=False)]

                st.caption(f"{len(filtered_history)}件を表示しています。日時は日本時間です。")
                visible_history = filtered_history.head(int(history_limit))
                st.dataframe(visible_history, width="stretch", hide_index=True)

                export_name = datetime.now(APP_TIMEZONE).strftime("send_history_%Y%m%d_%H%M")
                log_csv_col, log_xlsx_col = st.columns(2)
                log_csv_col.download_button(
                    "送信ログをCSVでダウンロード",
                    data=filtered_history.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{export_name}.csv",
                    mime="text/csv",
                    width="stretch",
                )
                log_xlsx_col.download_button(
                    "送信ログをExcelでダウンロード",
                    data=dataframe_to_xlsx(filtered_history, sheet_name="送信ログ"),
                    file_name=f"{export_name}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                )

        if "test_email_input" not in st.session_state:
            st.session_state["test_email_input"] = get_setting("TEST_EMAIL_ADDRESS", "")
        with st.expander("テスト送信", expanded=False):
            saved_test_email = get_setting("TEST_EMAIL_ADDRESS", "")
            if saved_test_email:
                st.caption(f"保存済み: {mask_email_address(saved_test_email)}")
            test_email_notice = st.session_state.pop("test_email_notice", "")
            test_email_error = st.session_state.pop("test_email_error", "")
            if test_email_notice:
                st.success(test_email_notice)
            if test_email_error:
                st.error(test_email_error)
            show_test_email = st.checkbox("テストメールアドレスを表示する", key="show_test_email_address")
            test_email_input_col, test_email_save_col = st.columns([2.3, 0.7])
            test_email_address = test_email_input_col.text_input(
                "テストメールアドレス",
                key="test_email_input",
                type="default" if show_test_email else "password",
                placeholder="自分の確認用メールアドレス",
            ).strip()
            if test_email_save_col.button("保存", key="save_test_email_address", width="stretch"):
                if not looks_like_email_address(test_email_address):
                    st.session_state["test_email_error"] = "テストメールアドレスを正しく入力してください。"
                else:
                    save_setting("TEST_EMAIL_ADDRESS", test_email_address)
                    st.session_state["test_email_notice"] = f"{mask_email_address(test_email_address)} を保存しました。"
                st.rerun()
            st.caption(
                "本番の宛先には送りません。送信対象の先頭1件を差し込み例として使い、"
                "ここに入力したテストメールアドレスへ1通だけ送ります。"
            )

        test_button, send_button = st.columns(2)
        with test_button:
            run_test = st.button(
                "テストメールアドレスに1通送る",
                width="stretch",
                disabled=not test_email_address,
            )
        with send_button:
            run_all = st.button(
                "シナリオ全体を送信予約" if scenario_full_auto else "指定件数を送信予約",
                type="primary",
                width="stretch",
            )
        st.info("送信予約を作成すると、送信キューに保存して予定時刻順に処理します。この画面を開いている間は30秒ごとに1通ずつ進めます。サーバー側の定期実行が有効な場合は、タブを閉じても送信が続きます。進捗は「シナリオ・送信予約の進捗」で確認できます。")

        if run_test or run_all:
            preflight_errors = []
            if not effective_campaign_name.strip():
                preflight_errors.append("配信名を入力してください。")
            if not smtp_configured():
                preflight_errors.append("送信元メール設定が未完了です。SMTPサーバー、ポート、送信元メールアドレス、SMTPパスワードを確認してください。")
            if send_window_end <= send_window_start:
                preflight_errors.append("メールを送ってよい時間は、「この時間まで」を「この時間から」より後にしてください。")
            if run_test and not looks_like_email_address(test_email_address):
                preflight_errors.append("テストメールアドレスを正しく入力してください。")
            if run_all and not confirmed:
                preflight_errors.append("送信前の確認にチェックしてください。これは、送信対象が許諾済み、または法的に送信可能な宛先であることを確認するためのチェックです。")
            if run_all and not final_confirmed:
                preflight_errors.append("送信前の最終確認にチェックしてください。")
            if run_all and scenario_full_auto and (not send_scenario or not scenario_full_steps):
                preflight_errors.append("シナリオ全体予約に使うステップがありません。シナリオ設定を確認してください。")
            if preflight_errors:
                st.error("送信前に直す項目があります。\n\n" + "\n".join(f"- {error}" for error in preflight_errors))
            else:
                if not scenario_context:
                    save_setting("CURRENT_CAMPAIGN_NAME", campaign_name.strip())
                contacts = fetch_next_send_contacts(
                    current_campaign_key,
                    1 if run_test else int(send_limit),
                    prerequisite_campaign_keys,
                    later_step_campaign_keys,
                    0,
                    unsubscribe_scope,
                    unsubscribe_scope_key,
                )

                if not contacts:
                    st.error("送信できる宛先がありません。宛先一覧、送信済み状況、配信名を確認してください。")
                elif run_all:
                    if scenario_full_auto and send_scenario:
                        ok, message = create_scenario_full_send_job(
                            send_scenario,
                            scenario_full_steps,
                            contacts,
                            int(delay),
                            send_window_start,
                            send_window_end,
                            int(scenario_step_gap_days),
                        )
                    else:
                        ok, message = create_send_job(
                            effective_campaign_name,
                            current_campaign_key,
                            effective_subject_template,
                            effective_body_template,
                            contacts,
                            int(delay),
                            send_window_start,
                            send_window_end,
                            unsubscribe_scope,
                            unsubscribe_scope_key,
                            unsubscribe_scope_label,
                        )
                    if ok:
                        st.session_state["send_booking_notice"] = message
                        st.session_state["_send_queue_last_checked_at"] = 0
                        st.rerun()
                    else:
                        st.error(message)
                else:
                    contact = contacts[0]
                    test_unsubscribe_url = "https://example.com/test-unsubscribe"
                    subject = render_template(effective_subject_template, contact, test_unsubscribe_url)
                    body = render_template(
                        ensure_unsubscribe_link_template(effective_body_template),
                        contact,
                        test_unsubscribe_url,
                        test_unsubscribe_url,
                    )
                    ok, result = send_email(test_email_address, subject, body)
                    if ok:
                        save_setting("TEST_EMAIL_ADDRESS", test_email_address)
                        st.success(f"{mask_email_address(test_email_address)} にテストメールを1通送信しました。")
                        st.caption("テスト送信は本番の送信ログに残さず、宛先一覧の送信済み状態も変更しません。")
                    else:
                        st.error(result)

    query = st.query_params
    token = query.get("unsubscribe_token") or query.get("token")
    if token:
        unsubscribe_scope_from_query = str(query.get("scope") or UNSUBSCRIBE_SCOPE_GLOBAL).strip() or UNSUBSCRIBE_SCOPE_GLOBAL
        unsubscribe_scope_key_from_query = str(query.get("scope_key") or "").strip()
        unsubscribe_scope_label_from_query = str(query.get("scope_label") or "").strip()
        if unsubscribe_scope_from_query == UNSUBSCRIBE_SCOPE_GLOBAL:
            unsubscribe_scope_key_from_query = UNSUBSCRIBE_SCOPE_GLOBAL
            unsubscribe_scope_label_from_query = "すべての案内"
        contact = rows("select id, email, youtube_channel_id, channel from contacts where token = ?", (token,))
        if contact:
            item = contact[0]
            record_unsubscribe_event(
                int(item["id"]),
                str(item["email"] or ""),
                str(item["youtube_channel_id"] or ""),
                str(item["channel"] or ""),
                scope=unsubscribe_scope_from_query,
                scope_key=unsubscribe_scope_key_from_query,
                scope_label=unsubscribe_scope_label_from_query,
            )
            delete_pending_sends_for_unsubscribe(
                int(item["id"]),
                str(item["email"] or ""),
                str(item["youtube_channel_id"] or ""),
                unsubscribe_scope_from_query,
                unsubscribe_scope_key_from_query,
            )
        st.success("配信停止を受け付けました。対象範囲の未送信予約から外しました。")

    st.divider()
    st.subheader("宛先一覧")
    cleanup_blocked_targets_for_existing_contacts()
    contacts = fetch_contacts()
    unsubscribe_events = fetch_unsubscribe_events()
    if not unsubscribe_events.empty:
        with st.expander(f"配信停止管理（{len(unsubscribe_events)}件）"):
            st.caption(
                "配信停止は宛先自体を消さず、どの範囲で停止されたかを記録します。"
                "停止種類と停止対象を見ると、どのシナリオ・どの配信で止まったかを確認できます。"
            )
            unsubscribe_delete_notice = st.session_state.pop("unsubscribe_delete_notice", "")
            unsubscribe_delete_error = st.session_state.pop("unsubscribe_delete_error", "")
            if unsubscribe_delete_notice:
                st.success(unsubscribe_delete_notice)
            if unsubscribe_delete_error:
                st.error(unsubscribe_delete_error)
            display_unsubscribes = unsubscribe_events_display_frame(unsubscribe_events)
            downloadable_unsubscribes = display_unsubscribes.drop(columns=["_event_id"], errors="ignore")
            unsubscribe_summary = unsubscribe_events_summary_frame(unsubscribe_events)
            stop_counts = display_unsubscribes["停止種類"].value_counts()
            metric_cols = st.columns(4)
            metric_cols[0].metric("配信停止合計", f"{len(display_unsubscribes)}件")
            metric_cols[1].metric("すべて停止", f"{int(stop_counts.get('すべて停止', 0))}件")
            metric_cols[2].metric("シナリオ停止", f"{int(stop_counts.get('シナリオ停止', 0))}件")
            metric_cols[3].metric("配信停止", f"{int(stop_counts.get('配信停止', 0))}件")

            analysis_tab, history_tab, download_tab = st.tabs(["分析", "停止履歴", "ダウンロード"])
            with analysis_tab:
                st.caption("停止対象ごとの件数と停止率です。停止率は、その対象の送信成功数に対する配信停止件数で計算しています。")
                st.dataframe(unsubscribe_summary, width="stretch", hide_index=True)
            with history_tab:
                filter_cols = st.columns([1.2, 2.0])
                unsubscribe_type = filter_cols[0].selectbox(
                    "停止種類",
                    ["すべて", "すべて停止", "シナリオ停止", "配信停止"],
                    key="unsubscribe_events_type_filter",
                )
                unsubscribe_search = filter_cols[1].text_input(
                    "配信停止を検索",
                    placeholder="メールアドレス、チャンネル、停止対象で検索",
                    key="unsubscribe_events_search",
                ).strip().lower()
                filtered_unsubscribes = display_unsubscribes.copy()
                if unsubscribe_type != "すべて":
                    filtered_unsubscribes = filtered_unsubscribes[filtered_unsubscribes["停止種類"] == unsubscribe_type]
                if unsubscribe_search:
                    mask = filtered_unsubscribes.fillna("").astype(str).apply(
                        lambda column: column.str.lower().str.contains(unsubscribe_search, regex=False)
                    ).any(axis=1)
                    filtered_unsubscribes = filtered_unsubscribes[mask]
                st.caption(f"{len(filtered_unsubscribes)}件を表示しています。")
                if not filtered_unsubscribes.empty:
                    st.caption("誤って配信停止した記録は、表の右端から削除できます。宛先一覧へ自動追加はしません。")
                    visible_unsubscribes = filtered_unsubscribes.head(120)
                    if len(filtered_unsubscribes) > len(visible_unsubscribes):
                        st.caption("表示が多い場合は、検索でメールアドレスや停止対象を絞り込んでください。")
                    header = st.columns([1.5, 1.0, 1.8, 1.7, 1.5, 1.2, 0.8])
                    headers = ["停止日時", "種類", "停止対象", "メールアドレス", "チャンネル", "理由", "操作"]
                    for column, label in zip(header, headers):
                        column.markdown(f"**{label}**")
                    for _, row in visible_unsubscribes.iterrows():
                        event_id = int(row["_event_id"])
                        columns = st.columns([1.5, 1.0, 1.8, 1.7, 1.5, 1.2, 0.8])
                        columns[0].write(row["停止日時"])
                        columns[1].write(row["停止種類"])
                        columns[2].write(row["停止対象"])
                        columns[3].write(row["メールアドレス"])
                        columns[4].write(row["チャンネル"])
                        columns[5].write(row["停止理由"])
                        if columns[6].button("削除", key=f"request_delete_unsubscribe_event_{event_id}", width="stretch"):
                            st.session_state["confirm_delete_unsubscribe_event_id"] = event_id
                            st.rerun()
                else:
                    st.write("検索条件に合う配信停止記録はありません。")

                pending_delete_unsubscribe_id = int(st.session_state.get("confirm_delete_unsubscribe_event_id") or 0)
                if pending_delete_unsubscribe_id:
                    pending_label = ""
                    if pending_delete_unsubscribe_id in set(display_unsubscribes["_event_id"].astype(int).tolist()):
                        pending_row = display_unsubscribes[
                            display_unsubscribes["_event_id"].astype(int) == pending_delete_unsubscribe_id
                        ].iloc[0]
                        pending_label = (
                            f"{pending_row['停止種類']} / {pending_row['停止対象']} / "
                            f"{pending_row['メールアドレス']}"
                        )
                    st.warning(
                        f"配信停止記録「{pending_label or pending_delete_unsubscribe_id}」を削除しますか？"
                        "宛先一覧への自動復活はしません。"
                    )
                    yes_col, no_col = st.columns(2)
                    if yes_col.button("はい、削除する", key="confirm_delete_unsubscribe_event_yes", width="stretch"):
                        ok, message = delete_unsubscribe_event(pending_delete_unsubscribe_id)
                        st.session_state["confirm_delete_unsubscribe_event_id"] = 0
                        if ok:
                            st.session_state["unsubscribe_delete_notice"] = message
                        else:
                            st.session_state["unsubscribe_delete_error"] = message
                        st.rerun()
                    if no_col.button("いいえ、削除しない", key="confirm_delete_unsubscribe_event_no", width="stretch"):
                        st.session_state["confirm_delete_unsubscribe_event_id"] = 0
                        st.rerun()
            with download_tab:
                export_name = datetime.now(APP_TIMEZONE).strftime("unsubscribe_analytics_%Y%m%d_%H%M")
                csv_col, xlsx_col = st.columns(2)
                csv_col.download_button(
                    "配信停止履歴をCSVでダウンロード",
                    data=downloadable_unsubscribes.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{export_name}_history.csv",
                    mime="text/csv",
                    width="stretch",
                )
                xlsx_col.download_button(
                    "配信停止履歴をExcelでダウンロード",
                    data=dataframe_to_xlsx(downloadable_unsubscribes, sheet_name="配信停止履歴"),
                    file_name=f"{export_name}_history.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                )
                summary_csv_col, summary_xlsx_col = st.columns(2)
                summary_csv_col.download_button(
                    "配信停止分析をCSVでダウンロード",
                    data=unsubscribe_summary.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{export_name}_summary.csv",
                    mime="text/csv",
                    width="stretch",
                )
                summary_xlsx_col.download_button(
                    "配信停止分析をExcelでダウンロード",
                    data=dataframe_to_xlsx(unsubscribe_summary, sheet_name="配信停止分析"),
                    file_name=f"{export_name}_summary.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                )

    blocked_targets = fetch_blocked_targets()
    if not blocked_targets.empty:
        with st.expander(f"削除済み・除外リスト（{len(blocked_targets)}件）"):
            st.caption("ここは手動削除や送信失敗などで、再取り込みしたくない宛先のリストです。配信停止だけの宛先は上の配信停止管理に残します。")
            blocked_search = st.text_input(
                "除外リストを検索",
                placeholder="メールアドレス、チャンネル名、理由で検索",
                key="blocked_targets_search",
            ).strip().lower()
            visible_blocked = blocked_targets
            if blocked_search:
                mask = visible_blocked[["email", "channel", "reason"]].fillna("").astype(str).apply(
                    lambda column: column.str.lower().str.contains(blocked_search, regex=False)
                ).any(axis=1)
                visible_blocked = visible_blocked[mask]
            if visible_blocked.empty:
                st.write("検索条件に合う除外データはありません。")
            else:
                header = st.columns([2.0, 2.0, 1.4, 1.5, 1.2])
                headers = ["メールアドレス", "チャンネル", "理由", "登録日時", "操作"]
                for column, label in zip(header, headers):
                    column.markdown(f"**{label}**")
                for row in visible_blocked.itertuples():
                    columns = st.columns([2.0, 2.0, 1.4, 1.5, 1.2])
                    columns[0].write(row.email or "-")
                    columns[1].write(row.channel or row.youtube_channel_id or "-")
                    columns[2].write(row.reason or "-")
                    columns[3].write(row.created_at or "-")
                    if columns[4].button("宛先へ戻す", key=f"unblock_target_{row.id}"):
                        ok, message = restore_blocked_target_by_id(int(row.id))
                        if ok:
                            st.success(message)
                        else:
                            st.error(message)
                        st.rerun()

    show_contacts_list = st.toggle("宛先一覧を表示する", value=False, key="show_contacts_list")
    if not show_contacts_list:
        st.caption(f"非表示中（{len(contacts)}件）。画面共有や紹介時はこのまま閉じておけます。")
    elif contacts.empty:
        st.write("まだ宛先がありません。")
    else:
        replied_contacts = contacts[contacts["contact_status"].fillna("") == "返信あり"]
        if not replied_contacts.empty:
            with st.expander(f"返信あり管理（{len(replied_contacts)}件）"):
                st.caption("返信があった宛先です。返信ありの宛先は自動送信対象から外れます。")
                header = st.columns([2.0, 2.0, 1.4, 1.4, 1.0])
                headers = ["チャンネル名", "Eメール", "メモ", "返信日時", "操作"]
                for column, label in zip(header, headers):
                    column.markdown(f"**{label}**")
                for row in replied_contacts.itertuples():
                    columns = st.columns([2.0, 2.0, 1.4, 1.4, 1.0])
                    columns[0].write(row.channel or "-")
                    columns[1].write(row.email or "-")
                    columns[2].write(row.memo or "-")
                    columns[3].write(row.replied_at or "-")
                    if columns[4].button("送信対象に戻す", key=f"restore_sendable_status_{row.id}"):
                        set_contact_status(int(row.id), "送信対象")
                        st.success(f"{row.email} を送信対象に戻しました")
                        st.rerun()

        search_col, sort_col, direction_col = st.columns([2.4, 1.2, 1.0])
        search_text = search_col.text_input(
            "宛先一覧を検索",
            placeholder="メールアドレス、メモ、チャンネル名で検索",
        ).strip().lower()
        sort_key = sort_col.selectbox(
            "並び順",
            options=["登録順", "最終送信"],
        )
        sort_direction = direction_col.selectbox(
            "向き",
            options=["古い順", "新しい順"],
        )
        contacts["状態"] = contacts.apply(
            lambda row: "全体停止"
            if row.get("global_unsubscribed")
            else ("一部停止" if row.get("scoped_unsubscribed") else ("送信可" if row["consent"] else "要確認")),
            axis=1,
        )

        if search_text:
            search_columns = ["email", "memo", "channel", "contact_status"]
            mask = contacts[search_columns].fillna("").astype(str).apply(
                lambda column: column.str.lower().str.contains(search_text, regex=False)
            ).any(axis=1)
            contacts = contacts[mask]

        ascending = sort_direction == "古い順"
        if sort_key == "登録順":
            contacts = contacts.sort_values(["id"], ascending=ascending)
        else:
            contacts["_last_sent_sort"] = contacts["last_sent"].replace("", "9999-12-31T23:59:59+00:00" if ascending else "")
            contacts = contacts.sort_values(["_last_sent_sort", "id"], ascending=[ascending, True])

        if contacts.empty:
            st.write("検索条件に合う宛先はありません。")
            return

        with st.expander("宛先一覧の一括操作"):
            st.caption(f"現在の検索・並び順で表示対象になっている {len(contacts)} 件にまとめて操作できます。削除系の操作は元に戻せません。")
            bulk_action = st.selectbox(
                "一括操作",
                ["分類を変更", "返信ありにする", "削除して今後取り込まない"],
                key="bulk_contacts_action",
            )
            bulk_status = "送信対象"
            if bulk_action == "分類を変更":
                bulk_status = st.selectbox("変更後の分類", CONTACT_STATUS_OPTIONS, index=CONTACT_STATUS_OPTIONS.index("送信対象"), key="bulk_contacts_status")
            bulk_confirm = st.checkbox("この一括操作を実行することを確認しました", key="bulk_contacts_confirm")
            if st.button("一括操作を実行", key="bulk_contacts_apply", width="stretch", disabled=not bulk_confirm):
                target_ids = [int(contact_id) for contact_id in contacts["id"].tolist()]
                if bulk_action == "分類を変更":
                    for contact_id in target_ids:
                        set_contact_status(contact_id, bulk_status)
                    st.success(f"{len(target_ids)}件の分類を「{bulk_status}」に変更しました")
                elif bulk_action == "返信ありにする":
                    for contact_id in target_ids:
                        mark_contact_replied(contact_id)
                    st.success(f"{len(target_ids)}件を返信ありにしました。自動送信対象から外れます。")
                else:
                    for contact_id in target_ids:
                        delete_contact(contact_id, block=True, reason="一括削除")
                    st.success(f"{len(target_ids)}件を削除し、再取り込みしないようにしました")
                st.rerun()

        export_frame = contacts_export_frame(contacts)
        export_name = datetime.now(APP_TIMEZONE).strftime("contacts_%Y%m%d_%H%M")
        download_csv_col, download_xlsx_col = st.columns(2)
        download_csv_col.download_button(
            "CSVでダウンロード",
            data=export_frame.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{export_name}.csv",
            mime="text/csv",
            width="stretch",
        )
        download_xlsx_col.download_button(
            "Excelでダウンロード",
            data=dataframe_to_xlsx(export_frame),
            file_name=f"{export_name}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )

        total_contacts = len(contacts)
        page_col, size_col, info_col = st.columns([1.0, 1.0, 2.0])
        page_size = size_col.selectbox("表示件数", [20, 50, 100], index=0, key="contacts_page_size")
        total_pages = max(1, (total_contacts + page_size - 1) // page_size)
        current_page = page_col.number_input(
            "ページ",
            min_value=1,
            max_value=total_pages,
            value=min(st.session_state.get("contacts_page", 1), total_pages),
            step=1,
            key="contacts_page",
        )
        start_index = (int(current_page) - 1) * page_size
        end_index = min(start_index + page_size, total_contacts)
        visible_contacts = contacts.iloc[start_index:end_index]
        info_col.caption(f"{total_contacts}件中 {start_index + 1}〜{end_index}件を表示 / {total_pages}ページ")

        header = st.columns([1.8, 2.1, 1.8, 1.2, 1.2, 0.9, 0.8, 0.7, 0.7])
        headers = ["チャンネル名", "Eメール", "メモ", "分類", "last_sent", "返信あり", "候補へ戻す", "保存", "削除"]
        for column, label in zip(header, headers):
            column.markdown(f"**{label}**")

        for row in visible_contacts.itertuples():
            columns = st.columns([1.8, 2.1, 1.8, 1.2, 1.2, 0.9, 0.8, 0.7, 0.7])
            edited_channel = columns[0].text_input("channel", value=row.channel or "", key=f"contact_channel_{row.id}", label_visibility="collapsed")
            edited_email = columns[1].text_input("email", value=row.email or "", key=f"contact_email_{row.id}", label_visibility="collapsed")
            edited_memo = columns[2].text_input("memo", value=row.memo or "", key=f"contact_memo_{row.id}", label_visibility="collapsed")
            current_status = row.contact_status if row.contact_status in CONTACT_STATUS_OPTIONS else "送信対象"
            edited_status = columns[3].selectbox(
                "分類",
                CONTACT_STATUS_OPTIONS,
                index=CONTACT_STATUS_OPTIONS.index(current_status),
                key=f"contact_status_{row.id}",
                label_visibility="collapsed",
            )
            columns[4].write(row.last_sent or "-")
            if columns[5].button("返信あり", key=f"mark_replied_{row.id}", disabled=current_status == "返信あり"):
                mark_contact_replied(int(row.id))
                st.success(f"{row.email} を返信ありにしました。今後の自動送信対象から外れます。")
                st.rerun()
            if columns[6].button("戻す", key=f"restore_candidate_{row.id}"):
                ok, message = save_candidate_from_contact(int(row.id))
                if ok:
                    st.success(message)
                    st.rerun()
                else:
                    st.warning(message)
            if columns[7].button("保存", key=f"save_contact_{row.id}"):
                ok, message = update_contact(int(row.id), edited_email, edited_memo, edited_channel, True, edited_status)
                if ok:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)
            if columns[8].button("削除", key=f"delete_contact_{row.id}"):
                delete_contact(int(row.id), block=True, reason="手動削除")
                st.success(f"{row.email} を削除しました")
                st.rerun()

    st.divider()
    st.subheader("YouTube候補一覧")
    candidates = fetch_candidates()
    with st.expander("外注用Googleシートを登録 / 回収する"):
        st.caption(
            "外注用に用意したGoogleスプレッドシートのURLを登録できます。"
            "登録したシートを開き、メールアドレスがあれば入力し、なければ「候補から削除」にチェックして回収します。"
        )
        stored_outsource_url = get_setting("OUTSOURCE_SPREADSHEET_URL").strip()
        create_sheet_col, sheet_home_col = st.columns(2)
        create_sheet_col.link_button(
            "新しいGoogleスプレッドシートを作る",
            "https://sheets.new",
            width="stretch",
        )
        sheet_home_col.link_button(
            "Googleスプレッドシート一覧を開く",
            "https://docs.google.com/spreadsheets/u/0/",
            width="stretch",
        )
        registered_outsource_url = st.text_input(
            "外注用GoogleスプレッドシートURL",
            value=stored_outsource_url,
            placeholder="https://docs.google.com/spreadsheets/d/...",
            key="registered_outsource_sheet_url",
        )
        ready_for_sheet, sheet_ready_message = google_sheet_write_ready()
        service_account_email = google_service_account_email()
        if service_account_email:
            st.caption("このGoogleシートを下のサービスアカウントに編集者として共有すると、アプリが候補一覧を書き込めます。")
            st.code(service_account_email, language=None)
        if not ready_for_sheet:
            st.info(sheet_ready_message or "空のGoogleシートへ自動で候補を書き込むには、アプリ用のサービスアカウント設定が必要です。")
        save_url_col, open_url_col = st.columns(2)
        if save_url_col.button("このURLを保存", key="save_outsource_sheet_url", width="stretch"):
            cleaned_outsource_url = registered_outsource_url.strip()
            save_setting("OUTSOURCE_SPREADSHEET_URL", cleaned_outsource_url)
            st.session_state["last_outsource_sheet_url"] = cleaned_outsource_url
            if cleaned_outsource_url:
                st.success("外注用GoogleシートURLを保存しました。")
                if ready_for_sheet:
                    try:
                        if candidates.empty:
                            spreadsheet_url = repair_outsource_spreadsheet_columns(cleaned_outsource_url)
                            st.success("Googleシートの列を準備しました。")
                        else:
                            spreadsheet_url, exported_count, already_count = append_new_outsource_candidates(candidates)
                            if exported_count:
                                st.success(
                                    f"新規候補{exported_count}件をGoogleシートへ追加しました。"
                                    f"反映済みの候補は{already_count}件スキップしました。"
                                )
                            else:
                                st.info(f"新しく追加できる候補はありません。反映済みの候補: {already_count}件")
                        st.session_state["last_outsource_sheet_url"] = spreadsheet_url
                        st.session_state["outsource_reflection_snapshot"] = {
                            "url": spreadsheet_url,
                            "signature": outsource_candidates_signature(candidates),
                            "pending_keys": [],
                            "reflected_count": len(candidates),
                            "checked_at": now_iso(),
                        }
                    except Exception as exc:
                        st.warning(f"URLは保存しましたが、シートへの反映はできませんでした: {exc}")
                elif not ready_for_sheet:
                    st.caption(sheet_ready_message)
            else:
                st.success("外注用GoogleシートURLを空にしました。")

        active_outsource_url = str(
            st.session_state.get("last_outsource_sheet_url") or registered_outsource_url.strip() or stored_outsource_url
        )
        with st.expander("外注シート連携の状態"):
            st.write(f"GoogleシートURL: {'設定あり' if active_outsource_url.startswith('http') else '未設定'}")
            st.write(f"サービスアカウント: {'設定あり' if service_account_email else '未設定'}")
            if service_account_email:
                st.code(service_account_email)
            st.write(f"Google連携ライブラリ: {'利用可能' if ready_for_sheet else '未確認または不足'}")
            if not ready_for_sheet:
                st.caption(sheet_ready_message or "サービスアカウント設定を確認してください。")
            st.write(f"YouTube候補: {len(candidates)}件")
        if active_outsource_url.startswith("http"):
            open_url_col.link_button("登録したGoogleシートを開く", active_outsource_url, width="stretch")
        else:
            open_url_col.button("登録したGoogleシートを開く", key="open_empty_outsource_sheet_url", width="stretch", disabled=True)
        sync_blockers = []
        if not active_outsource_url.startswith("http"):
            sync_blockers.append("外注用GoogleスプレッドシートURLが保存されていません。")
        if not ready_for_sheet:
            sync_blockers.append(sheet_ready_message or "サービスアカウント設定を確認してください。")

        candidates_signature = outsource_candidates_signature(candidates)
        sync_candidates = candidates
        reflected_count = 0
        reflected_checked_at = ""
        reflected_check_error = ""
        reflection_snapshot = st.session_state.get("outsource_reflection_snapshot", {})
        if (
            isinstance(reflection_snapshot, dict)
            and reflection_snapshot.get("url") == active_outsource_url
            and reflection_snapshot.get("signature") == candidates_signature
        ):
            sync_candidates = filter_outsource_candidates_by_keys(
                candidates,
                list(reflection_snapshot.get("pending_keys") or []),
            )
            reflected_count = int(reflection_snapshot.get("reflected_count") or 0)
            reflected_checked_at = str(reflection_snapshot.get("checked_at") or "")

        check_col, refresh_col = st.columns(2)
        if check_col.button("Googleシート接続を確認", key="check_outsource_sheet_connection", width="stretch"):
            try:
                save_setting("OUTSOURCE_SPREADSHEET_URL", active_outsource_url)
                st.success(check_outsource_spreadsheet_connection(active_outsource_url))
            except Exception as exc:
                st.error(f"接続できませんでした: {exc}")
        if refresh_col.button(
            "反映状態を更新",
            key="refresh_outsource_reflection_status",
            width="stretch",
            disabled=bool(sync_blockers) or candidates.empty,
        ):
            try:
                active_outsource_url = repair_outsource_spreadsheet_columns(active_outsource_url)
                st.session_state["last_outsource_sheet_url"] = active_outsource_url
                existing_outsource_frame = read_google_sheet_url_with_service_account(active_outsource_url)
                refreshed_candidates, refreshed_count = pending_outsource_candidates(candidates, existing_outsource_frame)
                st.session_state["outsource_reflection_snapshot"] = {
                    "url": active_outsource_url,
                    "signature": candidates_signature,
                    "pending_keys": outsource_candidate_keys(refreshed_candidates),
                    "reflected_count": refreshed_count,
                    "checked_at": now_iso(),
                }
                st.session_state["outsource_sync_notice"] = "登録済みシートの反映状態を更新しました。"
                st.rerun()
            except Exception as exc:
                reflected_check_error = str(exc)
        sync_notice = st.session_state.pop("outsource_sync_notice", "")
        if sync_notice:
            st.success(sync_notice)
        if sync_blockers:
            st.warning("候補一覧を反映できない理由: " + " / ".join(sync_blockers))
        elif reflected_check_error:
            st.warning(
                "登録済みシートの反映済み確認に失敗したため、候補全件を確認対象として表示しています: "
                + reflected_check_error
            )
        elif candidates.empty:
            st.caption("反映できる候補は0件です。押すとGoogleシートに見出しだけ作ります。")
        elif not reflected_checked_at:
            st.caption(f"YouTube候補: {len(candidates)}件。登録済みシートとの差分確認は「反映状態を更新」を押した時だけ行います。")
        elif sync_candidates.empty:
            st.caption(f"新しく反映できる候補は0件です（登録済みシートに反映済み: {reflected_count}件）。")
        else:
            st.caption(f"新しく反映できる候補: {len(sync_candidates)}件（登録済みシートに反映済み: {reflected_count}件）")
        if st.button("候補一覧を登録済みシートへ反映", key="sync_outsource_sheet", width="stretch"):
            save_setting("OUTSOURCE_SPREADSHEET_URL", active_outsource_url)
            try:
                spreadsheet_url, exported_count, already_count = append_new_outsource_candidates(candidates)
                st.session_state["last_outsource_sheet_url"] = spreadsheet_url
                st.session_state["outsource_reflection_snapshot"] = {
                    "url": spreadsheet_url,
                    "signature": candidates_signature,
                    "pending_keys": [],
                    "reflected_count": len(candidates),
                    "checked_at": now_iso(),
                }
                if exported_count:
                    st.session_state["outsource_sync_notice"] = (
                        f"新規候補{exported_count}件をGoogleシートへ追加しました。"
                        f"反映済みの候補は{already_count}件スキップしました。"
                    )
                else:
                    st.session_state["outsource_sync_notice"] = (
                        f"新しく反映できる候補はありません。登録済みシートに反映済み: {already_count}件"
                    )
                st.rerun()
            except Exception as exc:
                if sync_blockers:
                    st.error("反映できませんでした: " + " / ".join(sync_blockers))
                else:
                    st.error(f"反映できませんでした: {exc}")
        st.caption("列名はアプリが用意します。外注さんにはメールアドレス欄、メールがない時の「候補から削除」チェック、必要ならメモだけ入力してもらってください。")

        with st.expander("CSV / Excelで作る場合の予備ダウンロード"):
            outsource_frame = candidates_outsource_frame(sync_candidates)
            export_name = datetime.now(APP_TIMEZONE).strftime("youtube_candidates_outsource_%Y%m%d_%H%M")
            download_csv_col, download_xlsx_col = st.columns(2)
            download_csv_col.download_button(
                "外注用CSVをダウンロード",
                data=outsource_frame.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{export_name}.csv",
                mime="text/csv",
                width="stretch",
                disabled=sync_candidates.empty,
            )
            download_xlsx_col.download_button(
                "外注用Excelをダウンロード",
                data=dataframe_to_xlsx(outsource_frame, "外注用候補"),
                file_name=f"{export_name}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
                disabled=sync_candidates.empty,
            )

        if st.button(
            "外注用GoogleスプレッドシートURLから宛先一覧へ取り込む",
            key="import_outsource_google_url",
            width="stretch",
            disabled=not active_outsource_url.startswith("http"),
        ):
            target_outsource_url = active_outsource_url.strip()
            save_setting("OUTSOURCE_SPREADSHEET_URL", target_outsource_url)
            try:
                added, skipped, mapping, source_type = import_contacts_google_url(target_outsource_url)
                history_id = save_outsource_import_history(
                    target_outsource_url,
                    source_type,
                    added,
                    skipped,
                    mapping,
                )
                st.session_state.pop("outsource_reflection_snapshot", None)
                st.success(
                    f"{source_type}から{added}件を宛先一覧へ取り込みました。"
                    f"重複や空欄は{skipped}件スキップしました。履歴No.{history_id:06d}に保存しました。"
                )
                show_candidate_import_cleanup(mapping)
                if int(mapping.get("candidate_removed") or 0):
                    refreshed_message = refresh_outsource_sheet_if_possible()
                    if refreshed_message:
                        st.caption(refreshed_message)
                st.caption(
                    f"判別した項目: email={mapping['email'] or '-'} / "
                    f"channel={mapping['channel'] or '-'} / memo={mapping['memo'] or '-'} / "
                    f"候補から削除={mapping.get('discard') or '-'} / "
                    f"候補ID={mapping.get('candidate_id') or '-'}"
                )
            except Exception as exc:
                st.error(str(exc))
        render_outsource_import_history_panel()

    show_candidates_list = st.toggle("YouTube候補一覧を表示する", value=False, key="show_youtube_candidates_list")
    if not show_candidates_list:
        st.caption(f"非表示中（{len(candidates)}件）。候補チャンネルの情報を見せたくない時はこのまま閉じておけます。")
    elif candidates.empty:
        st.write("まだ候補チャンネルがありません。")
    else:
        st.markdown("<div id='youtube-candidates-search-top'></div>", unsafe_allow_html=True)
        candidate_search = st.text_input(
            "候補一覧を検索",
            placeholder="チャンネル名、検索キーワードで検索",
        ).strip().lower()
        if st.session_state.pop("scroll_to_candidates_top", False):
            scroll_nonce = int(st.session_state.get("scroll_to_candidates_nonce", 0))
            st.iframe(
                """
                <script>
                const scrollNonce = __SCROLL_NONCE__;
                const doc = window.parent.document;

                function findCandidateSearchTarget() {
                    const anchor = doc.getElementById("youtube-candidates-search-top");
                    const inputs = Array.from(doc.querySelectorAll("input"));
                    const searchInput = inputs.find((input) => {
                        const label = input.getAttribute("aria-label") || "";
                        const placeholder = input.getAttribute("placeholder") || "";
                        return label.includes("候補一覧を検索") || placeholder.includes("チャンネル名、検索キーワード");
                    });
                    if (searchInput) {
                        return searchInput.closest('[data-testid="stTextInput"]') || searchInput;
                    }
                    return anchor;
                }

                function scrollToCandidateSearch() {
                    const target = findCandidateSearchTarget();
                    if (!target) return;
                    const top = target.getBoundingClientRect().top + window.parent.scrollY - 90;
                    window.parent.scrollTo({ top, behavior: "smooth" });
                    target.scrollIntoView({ behavior: "smooth", block: "start" });
                }

                setTimeout(scrollToCandidateSearch, 50);
                </script>
                """.replace("__SCROLL_NONCE__", str(scroll_nonce)),
                height=1,
            )
        if candidate_search:
            mask = candidates[["title", "keyword"]].fillna("").astype(str).apply(
                lambda column: column.str.lower().str.contains(candidate_search, regex=False)
            ).any(axis=1)
            candidates = candidates[mask]

        if candidates.empty:
            st.write("検索条件に合う候補はありません。")
            return

        total_candidates = len(candidates)
        candidate_page_col, candidate_size_col, candidate_info_col = st.columns([1.0, 1.0, 2.0])
        candidate_page_size = candidate_size_col.selectbox(
            "表示件数",
            [20, 30, 50, 100],
            index=0,
            key="candidates_page_size",
        )
        candidate_total_pages = max(1, (total_candidates + candidate_page_size - 1) // candidate_page_size)
        candidate_current_page = candidate_page_col.number_input(
            "ページ",
            min_value=1,
            max_value=candidate_total_pages,
            value=min(st.session_state.get("candidates_page", 1), candidate_total_pages),
            step=1,
            key="candidates_page",
        )
        candidate_start_index = (int(candidate_current_page) - 1) * candidate_page_size
        candidate_end_index = min(candidate_start_index + candidate_page_size, total_candidates)
        visible_candidates = candidates.iloc[candidate_start_index:candidate_end_index]
        candidate_info_col.caption(
            f"{total_candidates}件中 {candidate_start_index + 1}〜{candidate_end_index}件を表示 / {candidate_total_pages}ページ"
        )

        header = st.columns([2.2, 1.0, 1.0, 1.0, 1.2, 1.0, 0.9, 0.7])
        headers = ["チャンネル", "登録者数", "動画数", "総再生数", "検索キーワード", "開く", "宛先", "削除"]
        for column, label in zip(header, headers):
            column.markdown(f"**{label}**")

        for row in visible_candidates.itertuples():
            columns = st.columns([2.2, 1.0, 1.0, 1.0, 1.2, 1.0, 0.9, 0.7])
            columns[0].write(row.title or "-")
            columns[1].write(f"{int(row.subscriber_count):,}")
            columns[2].write(f"{int(row.video_count):,}")
            columns[3].write(f"{int(row.view_count):,}")
            columns[4].write(row.keyword or "-")
            columns[5].markdown(f"[YouTubeで開く]({row.channel_url})")
            if columns[6].button("宛先に登録", key=f"candidate_to_contact_{row.id}"):
                candidate_detail = rows("select * from youtube_candidates where user_id = ? and id = ?", (current_user_id(), int(row.id)))
                candidate = candidate_detail[0] if candidate_detail else None
                added = add_contact(
                    candidate["email"] if candidate else "",
                    "",
                    row.title or "",
                    True,
                    row.channel_id,
                    row.channel_url,
                    int(row.subscriber_count),
                    int(row.video_count),
                    int(row.view_count),
                    row.keyword or "",
                    candidate["description"] if candidate else "",
                )
                if added:
                    delete_candidate(int(row.id))
                    if candidate and candidate["email"]:
                        st.success(f"{row.title} を宛先一覧に追加しました。登録済みメールアドレスも引き継ぎました。")
                    else:
                        st.success(f"{row.title} を宛先一覧に追加しました。メールアドレスを入力して保存してください。")
                    st.rerun()
                else:
                    st.warning("このチャンネルはすでに宛先一覧に登録されています")
            if columns[7].button("削除", key=f"delete_candidate_{row.id}"):
                delete_candidate_and_block(int(row.id))
                st.success(f"{row.title} を削除し、今後自動で戻らないようにしました")
                st.rerun()

        st.divider()
        prev_col, page_status_col, next_col = st.columns([1.0, 2.0, 1.0])
        if prev_col.button(
            "前のページ",
            key="candidates_prev_page_bottom",
            width="stretch",
            disabled=int(candidate_current_page) <= 1,
            on_click=change_candidate_page,
            args=(-1, candidate_total_pages),
        ):
            pass
        page_status_col.markdown(
            f"<div style='text-align:center; padding-top:0.45rem;'>"
            f"{candidate_current_page} / {candidate_total_pages}ページ"
            f"</div>",
            unsafe_allow_html=True,
        )
        if next_col.button(
            "次のページ",
            key="candidates_next_page_bottom",
            width="stretch",
            disabled=int(candidate_current_page) >= candidate_total_pages,
            on_click=change_candidate_page,
            args=(1, candidate_total_pages),
        ):
            pass

    flush_app_state_if_dirty()


if __name__ == "__main__":
    main()
