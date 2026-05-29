from __future__ import annotations

import os
import re
import secrets
import smtplib
import sqlite3
import time
import json
import hashlib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time as datetime_time, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from string import Template
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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


def today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


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
        "scope": "openid email profile",
        "prompt": "select_account",
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
        col1, col2 = st.columns([3, 1])
        col1.caption(f"ログイン中: {manual_user.get('email', 'unknown')}")
        if col2.button("ログアウト"):
            st.session_state.pop("google_user", None)
            st.rerun()
        return True
    if st.user.is_logged_in:
        col1, col2 = st.columns([3, 1])
        col1.caption(f"ログイン中: {st.user.get('email', 'unknown')}")
        if col2.button("ログアウト"):
            st.logout()
        return True
    st.title("Creator Outreach Mailer")
    st.write("このアプリを使うにはGoogleログインが必要です。")
    st.link_button("Googleでログイン", build_google_login_url())
    st.stop()


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
                token text not null unique,
                created_at text not null
            );

            create table if not exists sends (
                id integer primary key autoincrement,
                user_id text not null default 'local-user',
                contact_id integer not null,
                campaign_key text not null default '',
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
        }
        for column, statement in migrations.items():
            if column not in columns:
                db.execute(statement)
        for table in ["sends", "settings", "youtube_candidates", "youtube_api_usage", "blocked_targets", "campaign_templates", "smtp_accounts"]:
            table_columns = [row[1] for row in db.execute(f"pragma table_info({table})").fetchall()]
            if "user_id" not in table_columns:
                db.execute(f"alter table {table} add column user_id text not null default 'local-user'")
        candidate_columns = [row[1] for row in db.execute("pragma table_info(youtube_candidates)").fetchall()]
        if "email" not in candidate_columns:
            db.execute("alter table youtube_candidates add column email text not null default ''")
        sends_columns = [row[1] for row in db.execute("pragma table_info(sends)").fetchall()]
        if "campaign_key" not in sends_columns:
            db.execute("alter table sends add column campaign_key text not null default ''")
        campaign_columns = [row[1] for row in db.execute("pragma table_info(campaign_templates)").fetchall()]
        if "sort_order" not in campaign_columns:
            db.execute("alter table campaign_templates add column sort_order integer not null default 0")
            db.execute("update campaign_templates set sort_order = id where sort_order = 0")
        db.commit()


def fetch_contacts() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as db:
        return pd.read_sql_query(
            """
            select
                c.id,
                c.email,
                c.name,
                c.channel,
                c.consent,
                c.unsubscribed,
                c.created_at,
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


def execute(query: str, params: tuple = ()) -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute(query, params)
        db.commit()


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
        sort_order = int(existing["sort_order"])
    else:
        max_order = rows(
            "select coalesce(max(sort_order), 0) as max_order from campaign_templates where user_id = ?",
            (current_user_id(),),
        )[0]["max_order"]
        sort_order = int(max_order) + 10
    execute(
        "delete from campaign_templates where user_id = ? and name = ?",
        (current_user_id(), clean_name),
    )
    execute(
        """
        insert into campaign_templates(user_id, name, sort_order, subject, body, updated_at)
        values(?, ?, ?, ?, ?, ?)
        """,
        (current_user_id(), clean_name, sort_order, subject, body, now_iso()),
    )


def delete_campaign_template(name: str) -> None:
    execute(
        "delete from campaign_templates where user_id = ? and name = ?",
        (current_user_id(), name.strip()),
    )


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


def change_candidate_page(delta: int, total_pages: int) -> None:
    current_page = int(st.session_state.get("candidates_page", 1))
    st.session_state["candidates_page"] = max(1, min(int(total_pages), current_page + int(delta)))
    st.session_state["scroll_to_candidates_top"] = True
    st.session_state["scroll_to_candidates_nonce"] = int(st.session_state.get("scroll_to_candidates_nonce", 0)) + 1


def ensure_default_campaign_template() -> None:
    execute("delete from campaign_templates where user_id = ? and name = ?", (current_user_id(), "2通目"))
    existing_names = {template["name"] for template in fetch_campaign_templates()}
    for name, subject, body in DEFAULT_CAMPAIGN_TEMPLATES:
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
    execute(
        """
        delete from blocked_targets
        where user_id = ? and ((email != '' and email = ?) or (youtube_channel_id != '' and youtube_channel_id = ?))
        """,
        (current_user_id(), normalized_email, channel_id),
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


def update_contact(contact_id: int, email: str, name: str, channel: str, consent: bool) -> tuple[bool, str]:
    normalized_email = email.strip().lower()
    duplicate = rows(
        "select id from contacts where user_id = ? and email = ? and id != ?",
        (current_user_id(), normalized_email, contact_id),
    ) if normalized_email else []
    if duplicate:
        return False, "このメールアドレスはすでに登録されています"
    execute(
        """
        update contacts
        set email = ?, name = ?, channel = ?, consent = ?
        where user_id = ? and id = ?
        """,
        (normalized_email, name.strip(), channel.strip(), 1 if consent else 0, current_user_id(), contact_id),
    )
    return True, "宛先を更新しました"


def youtube_api_get(path: str, params: dict[str, str | int]) -> dict:
    api_key = get_secret("YOUTUBE_API_KEY", "")
    if not api_key:
        raise RuntimeError("YouTube APIキーが未設定です")
    query = urllib.parse.urlencode({**params, "key": api_key})
    url = f"https://www.googleapis.com/youtube/v3/{path}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            import json

            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"YouTube APIエラー: {exc.code} {detail[:300]}") from exc


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
            search_data = youtube_api_get(
                "search",
                search_params,
            )
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
        channel_data = youtube_api_get(
            "channels",
            {
                "part": "snippet,statistics",
                "id": ",".join(channel_ids),
                "maxResults": 50,
            },
        )

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


def render_template(text: str, contact: sqlite3.Row, unsubscribe_url: str) -> str:
    values = {
        "name": contact["name"] or "ご担当者",
        "email": contact["email"],
        "channel": contact["channel"] or "貴チャンネル",
        "unsubscribe_url": unsubscribe_url,
    }
    return Template(text).safe_substitute(values)


def ensure_unsubscribe_link_template(body_template: str) -> str:
    if "${unsubscribe_url}" in body_template:
        return body_template
    return body_template.rstrip() + "\n\n不要な場合はこちらから配信停止できます。\n${unsubscribe_url}"


def build_unsubscribe_mailto(contact: sqlite3.Row) -> str:
    account = active_smtp_account()
    reply_to = get_secret("UNSUBSCRIBE_EMAIL", "") or str(account.get("sender_email") or "")
    subject = "配信停止希望"
    body = (
        "配信停止を希望します。\n\n"
        f"対象メールアドレス: {contact['email']}\n"
        f"チャンネル名: {contact['channel'] or '-'}\n"
    )
    return f"mailto:{reply_to}?subject={quote(subject)}&body={quote(body)}"


def build_unsubscribe_url(contact: sqlite3.Row) -> str:
    if supabase_configured():
        base_url = supabase_config()["url"].rstrip("/")
        return f"{base_url}/functions/v1/unsubscribe?token={quote(str(contact['token']))}"
    return build_unsubscribe_mailto(contact)


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


def next_window_start(moment: datetime, window_start: datetime_time) -> datetime:
    return datetime.combine(moment.date() + timedelta(days=1), window_start, APP_TIMEZONE)


def build_send_schedule(
    send_count: int,
    delay_seconds: int,
    window_start: datetime_time,
    window_end: datetime_time,
) -> list[datetime]:
    if send_count <= 0 or window_end <= window_start:
        return []

    scheduled_times = []
    cursor = datetime.now(APP_TIMEZONE)
    today_start = datetime.combine(cursor.date(), window_start, APP_TIMEZONE)
    today_end = datetime.combine(cursor.date(), window_end, APP_TIMEZONE)

    if cursor < today_start:
        cursor = today_start
    elif cursor >= today_end:
        cursor = next_window_start(cursor, window_start)

    for _ in range(send_count):
        day_end = datetime.combine(cursor.date(), window_end, APP_TIMEZONE)
        if cursor >= day_end:
            cursor = next_window_start(cursor, window_start)
        scheduled_times.append(cursor.astimezone(timezone.utc))
        cursor = cursor + timedelta(seconds=int(delay_seconds))

    return scheduled_times


def format_local_datetime(value: datetime) -> str:
    return value.astimezone(APP_TIMEZONE).strftime("%Y-%m-%d %H:%M")


def send_email(to_email: str, subject: str, body: str) -> tuple[bool, str]:
    if not smtp_configured():
        return True, "DRY_RUN: SMTP設定がないため実送信はしていません"

    account = active_smtp_account()
    message = EmailMessage()
    message["From"] = smtp_mail_from(account)
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    host = str(account.get("smtp_host") or "")
    port = int(str(account.get("smtp_port") or "587"))
    use_ssl = int(account.get("smtp_ssl") or 0) == 1
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


def create_send_job(
    campaign_name: str,
    campaign_key_value: str,
    subject_template: str,
    body_template: str,
    contacts: list[sqlite3.Row],
    delay_seconds: int,
    window_start: datetime_time,
    window_end: datetime_time,
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
        "status": "queued",
        "updated_at": now_iso(),
    }
    created_job = supabase_request("POST", "send_jobs", job_payload, prefer="return=representation")
    if not isinstance(created_job, list) or not created_job:
        return False, "送信予約の作成に失敗しました"
    job_id = created_job[0]["id"]
    queue_rows = []
    for index, contact in enumerate(contacts):
        register_unsubscribe_token(contact, user_email)
        unsubscribe_url = build_unsubscribe_url(contact)
        subject = render_template(subject_template, contact, unsubscribe_url)
        body = render_template(ensure_unsubscribe_link_template(body_template), contact, unsubscribe_url)
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
    if queue_rows:
        supabase_request("POST", "send_queue", queue_rows, prefer="return=representation")
    for row in queue_rows:
        execute(
            "insert into sends(user_id, contact_id, campaign_key, subject, status, error, sent_at) values (?, ?, ?, ?, ?, ?, ?)",
            (current_user_id(), row["contact_local_id"], campaign_key_value, row["subject"], "queued", "", now_iso()),
        )
    return True, f"{len(queue_rows)}件の送信予約を作成しました"


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
            f"send_queue?user_email=eq.{query_email}&status=in.(sent,failed)&select=contact_local_id,campaign_key,status,error,sent_at,subject",
        )
        if not isinstance(results, list):
            return
        for item in results:
            contact_id = item.get("contact_local_id")
            campaign_key_value = item.get("campaign_key", "")
            if not contact_id or not campaign_key_value:
                continue
            sent_at = item.get("sent_at") or now_iso()
            status = item.get("status", "")
            error = item.get("error", "")
            execute(
                """
                update sends
                set status = ?, error = ?, sent_at = ?
                where user_id = ?
                  and contact_id = ?
                  and campaign_key = ?
                  and status = 'queued'
                """,
                (status, error, sent_at, current_user_id(), int(contact_id), campaign_key_value),
            )
    except Exception:
        return


def sync_unsubscribes_from_supabase() -> None:
    if not supabase_configured():
        return
    user_email = current_user_profile()["email"].strip().lower()
    if not user_email:
        return
    try:
        query_email = urllib.parse.quote(user_email, safe="")
        results = supabase_request(
            "GET",
            f"unsubscribe_tokens?user_email=eq.{query_email}&unsubscribed_at=not.is.null&select=contact_local_id,contact_email,youtube_channel_id,channel",
        )
        if not isinstance(results, list):
            return
        for item in results:
            contact_id = int(item.get("contact_local_id") or 0)
            contact_email = str(item.get("contact_email") or "").strip().lower()
            youtube_channel_id = str(item.get("youtube_channel_id") or "").strip()
            channel = str(item.get("channel") or "").strip()
            block_target(contact_email, youtube_channel_id, channel, "配信停止URL")
            if contact_id:
                delete_contact(contact_id)
            elif contact_email:
                matched = rows("select id from contacts where user_id = ? and email = ?", (current_user_id(), contact_email))
                for row in matched:
                    delete_contact(int(row["id"]))
            elif youtube_channel_id:
                matched = rows("select id from contacts where user_id = ? and youtube_channel_id = ?", (current_user_id(), youtube_channel_id))
                for row in matched:
                    delete_contact(int(row["id"]))
    except Exception:
        return


def fetch_recent_send_jobs() -> list[dict]:
    if not supabase_configured():
        return []
    user_email = current_user_profile()["email"].strip().lower()
    if not user_email:
        return []
    try:
        query_email = urllib.parse.quote(user_email, safe="")
        result = supabase_request(
            "GET",
            f"send_jobs?user_email=eq.{query_email}&select=campaign_name,total_count,sent_count,failed_count,status,created_at&order=created_at.desc&limit=5",
        )
        return result if isinstance(result, list) else []
    except Exception:
        return []


def add_contact(
    email: str,
    name: str,
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
            user_id, email, name, channel, youtube_channel_id, youtube_channel_url,
            youtube_subscriber_count, youtube_video_count, youtube_view_count,
            youtube_keyword, youtube_description, source, consent, unsubscribed, token, created_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, 0, ?, ?)
        """,
        (
            current_user_id(),
            normalized_email,
            name.strip(),
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
    st.caption("複数の送信元メールを登録し、送信時に使うアカウントを選べます。相手には「送信者表示名 <送信元メールアドレス>」の形で見えます。")

    accounts = fetch_smtp_accounts()
    account_labels = [f"{account['label']} / {account['sender_email']}" for account in accounts]
    account_ids = [int(account["id"]) for account in accounts]
    active_account = active_smtp_account()
    active_account_id = int(active_account.get("id") or 0)
    current_youtube_api_key = get_setting("YOUTUBE_API_KEY")
    current_youtube_daily_limit = get_youtube_daily_limit()

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
    if load_col.button("読み込む", key="load_smtp_account", use_container_width=True, disabled=selected_account_id == 0):
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

    if save_col.button("保存 / 更新", key="save_smtp_account", use_container_width=True):
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

    if delete_col.button("削除", key="delete_smtp_account", use_container_width=True, disabled=selected_account_id == 0):
        delete_smtp_account(selected_account_id)
        st.success("送信元設定を削除しました")
        st.rerun()

    display_account = active_smtp_account()
    if display_account.get("sender_email"):
        st.write(f"現在の送信元: `{smtp_mail_from(display_account)}`")
    if has_password:
        st.caption("パスワードは保存済みです。変更したい時だけ新しいパスワードを入力してください。")

    st.divider()
    st.caption("YouTube API設定")
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


def read_contacts_file(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file).fillna("")
    if name.endswith(".tsv"):
        return pd.read_csv(uploaded_file, sep="\t").fillna("")
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded_file).fillna("")
    raise ValueError("対応している形式は CSV / TSV / XLSX / XLS です")


def import_contacts_file(uploaded_file) -> tuple[int, int, dict[str, str | None]]:
    frame = read_contacts_file(uploaded_file)
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
    name_column = find_column(frame, {"name", "名前", "担当者", "担当者名", "contact", "contactname"})
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

    if not email_column:
        raise ValueError("メールアドレスの列を見つけられませんでした。列名に email または メールアドレス を入れてください。")

    added = 0
    skipped = 0
    seen_in_file: set[str] = set()
    for _, row in frame.iterrows():
        email = str(row.get(email_column, "")).strip().lower()
        if not email:
            continue
        if email in seen_in_file:
            skipped += 1
            continue
        seen_in_file.add(email)
        was_added = add_contact(
            email=email,
            name=str(row.get(name_column, "")) if name_column else "",
            channel=str(row.get(channel_column, "")) if channel_column else "",
            consent=True,
        )
        if was_added:
            added += 1
        else:
            skipped += 1
    return added, skipped, {"email": email_column, "name": name_column, "channel": channel_column}


def main() -> None:
    st.set_page_config(page_title="Creator Outreach Mailer", layout="wide")
    init_db()

    if not require_login():
        return

    require_active_subscription()
    ensure_default_campaign_template()
    sync_send_queue_results()
    sync_unsubscribes_from_supabase()

    st.title("Creator Outreach Mailer")
    st.caption("許諾済みの宛先だけに、1件ずつ送信する個人用Webアプリ")

    if smtp_configured():
        st.success("SMTP設定あり: 実送信できます")
    else:
        st.warning("SMTP未設定: 送信操作は記録のみのテストモードです")

    st.info(
        "営業メールは、送信先の国や地域のルールに従ってください。"
        "日本では広告宣伝メールは原則オプトインです。"
    )

    left, right = st.columns([0.9, 1.4], gap="large")

    with left:
        settings_panel()
        st.divider()

        st.subheader("宛先を追加")
        with st.form("add_contact"):
            email = st.text_input("メールアドレス")
            name = st.text_input("名前", placeholder="例: 山田さん")
            channel = st.text_input("チャンネル名", placeholder="例: Sample Channel")
            consent = st.checkbox("営業メール送信の許諾がある")
            submitted = st.form_submit_button("追加")
        if submitted:
            if email:
                normalized_email = email.strip().lower()
                blocked_reason = blocked_target_reason(normalized_email)
                if "restore_blocked_email" not in st.session_state:
                    st.session_state["restore_blocked_email"] = ""
                    st.session_state["restore_blocked_name"] = ""
                    st.session_state["restore_blocked_channel"] = ""
                    st.session_state["restore_blocked_consent"] = False
                was_added = add_contact(email, name, channel, consent)
                if was_added:
                    st.success("宛先を追加しました")
                elif blocked_reason:
                    st.session_state["restore_blocked_email"] = normalized_email
                    st.session_state["restore_blocked_name"] = name
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
            if restore_yes_col.button("はい、再登録する", key="confirm_restore_blocked_email", use_container_width=True):
                unblock_target(restore_email)
                restored = add_contact(
                    restore_email,
                    st.session_state.get("restore_blocked_name", ""),
                    st.session_state.get("restore_blocked_channel", ""),
                    bool(st.session_state.get("restore_blocked_consent", False)),
                )
                st.session_state["restore_blocked_email"] = ""
                if restored:
                    st.success("宛先一覧に戻しました")
                    st.rerun()
                else:
                    st.error("再登録できませんでした。すでに宛先一覧にある可能性があります。")
            if restore_no_col.button("いいえ、戻さない", key="cancel_restore_blocked_email", use_container_width=True):
                st.session_state["restore_blocked_email"] = ""
                st.rerun()

        st.subheader("ファイル取り込み")
        uploaded = st.file_uploader("CSV / Excelファイル", type=["csv", "tsv", "xlsx", "xls"])
        st.caption("email / メールアドレス、channel / チャンネル名、name / 名前 などの列名を自動判別します。取り込んだ宛先は自動的に送信可になります。")
        if uploaded and st.button("取り込む"):
            try:
                added, skipped, mapping = import_contacts_file(uploaded)
                st.success(f"{added}件を取り込みました。重複や空欄は{skipped}件スキップしました。")
                st.caption(
                    f"判別した列: email={mapping['email'] or '-'} / "
                    f"channel={mapping['channel'] or '-'} / name={mapping['name'] or '-'}"
                )
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
        template_options = ["新しく作る"] + template_names
        selected_index = template_options.index(current_campaign_name) if current_campaign_name in template_options else 0
        selected_template = st.selectbox("保存済み配信", template_options, index=selected_index)
        load_col, save_col, delete_col = st.columns(3)
        if load_col.button("読み込む", key="load_campaign_template", use_container_width=True, disabled=selected_template == "新しく作る"):
            if load_campaign_template_into_session(selected_template):
                save_setting("CURRENT_CAMPAIGN_NAME", selected_template)
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
                        key="campaign_template_sort",
                        custom_style=vertical_sort_style,
                    )
                    if sorted_template_names != template_names:
                        if st.button("この順番で保存", use_container_width=True):
                            save_campaign_template_order(sorted_template_names)
                            st.success("並び順を保存しました")
                            st.rerun()
                else:
                    st.caption("ドラッグで並び替えるには、依存パッケージの反映後にアプリを再起動してください。")
        campaign_name = st.text_input("配信名", key="campaign_name_input")
        st.caption("同じ配信名の間は、本文を少し直しても同じ配信として進捗を引き継ぎます。新しい別メールを送る時だけ配信名を変えてください。")
        subject_template = st.text_input("件名", key="subject_template_input")
        body_template = st.text_area("本文", height=260, key="body_template_input")
        if save_col.button("保存 / 更新", key="save_campaign_template", use_container_width=True):
            if campaign_name.strip():
                save_campaign_template(campaign_name, subject_template, body_template)
                save_setting("CURRENT_CAMPAIGN_NAME", campaign_name.strip())
                st.success(f"{campaign_name} を保存しました")
                st.rerun()
            else:
                st.error("配信名を入力してください")
        if delete_col.button("削除", key="delete_campaign_template", use_container_width=True, disabled=selected_template == "新しく作る"):
            delete_campaign_template(selected_template)
            st.success(f"{selected_template} を削除しました")
            st.rerun()
        delay = st.number_input("送信間隔（秒）", min_value=30, max_value=300, value=90, step=10)
        st.caption("送信間隔は90秒を初期値にしています。短すぎる間隔は迷惑メール判定やサーバー制限の原因になるため、実運用では60〜120秒以上を目安にしてください。")
        send_limit = st.number_input("今回送信する件数", min_value=1, max_value=500, value=50)
        st.caption("大量送信はメールサーバー側で制限される場合があります。営業メールの実運用では、まず1日50〜100件程度から始め、送信エラーや迷惑メール判定が増えないことを確認しながら、必要に応じて100〜300件程度まで増やしてください。1日500件以上を継続して送る場合は、専用のメール配信サービスの利用を推奨します。")
        window_col_start, window_col_end = st.columns(2)
        send_window_start = window_col_start.time_input(
            "メールを送ってよい時間（この時間から）",
            value=datetime_time(8, 0),
            step=1800,
        )
        send_window_end = window_col_end.time_input(
            "メールを送ってよい時間（この時間まで）",
            value=datetime_time(20, 0),
            step=1800,
        )
        if send_window_end <= send_window_start:
            st.warning("メールを送ってよい時間は、「この時間まで」を「この時間から」より後にしてください。")
        st.caption("この時間帯の外では送信しません。時間を超えた分は、翌日の「この時間から」に自動で持ち越します。")
        if int(send_limit) > 300:
            st.warning("今回の送信件数が多めです。送信先の反応、迷惑メール判定、サーバー制限を確認しながら少しずつ増やしてください。")
        confirmed = st.checkbox("送信対象が許諾済み、または法的に送信可能な宛先であることを確認しました")

        current_campaign_key = campaign_key(campaign_name)
        target_count = rows(
            "select count(*) as count from contacts where user_id = ? and consent = 1 and unsubscribed = 0 and email != ''",
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
        remaining_count = rows(
            """
            select count(*) as count
            from contacts c
            where c.user_id = ?
              and c.consent = 1
              and c.unsubscribed = 0
              and c.email != ''
              and not exists (
                  select 1
                  from sends s
                  where s.user_id = c.user_id
                    and s.contact_id = c.id
                    and s.campaign_key = ?
                    and s.status in ('sent', 'queued')
              )
            """,
            (current_user_id(), current_campaign_key),
        )[0]["count"]
        metric_cols = st.columns(4)
        metric_cols[0].metric("送信対象", f"{target_count}件")
        metric_cols[1].metric("この配信を送信済み", f"{already_sent_count}件")
        metric_cols[2].metric("送信待ち", f"{queued_count}件")
        metric_cols[3].metric("この配信の未送信", f"{remaining_count}件")
        planned_count = min(int(send_limit), int(remaining_count))
        preview_schedule = build_send_schedule(
            planned_count,
            int(delay),
            send_window_start,
            send_window_end,
        )
        if planned_count > 0 and preview_schedule:
            first_time = format_local_datetime(preview_schedule[0])
            last_time = format_local_datetime(preview_schedule[-1])
            total_minutes = max(1, int((preview_schedule[-1] - preview_schedule[0]).total_seconds() // 60) + 1)
            st.info(
                f"送信予定: {planned_count}件 / 開始予定 {first_time} / 完了予定 {last_time} / "
                f"所要目安 約{total_minutes:,}分"
            )
        elif planned_count > 0:
            st.warning("送信可能時間帯の設定を確認してください。終了時刻は開始時刻より後にしてください。")
        if remaining_count == 0 and target_count > 0:
            st.success("この配信名では、現在の送信対象すべてが送信済み、または送信待ちです。")
        st.caption("同じ配信名ですでに送った宛先、または送信待ちの宛先は自動で除外します。送信対象は、未送信の宛先を優先し、その後は最終送信日時が古い順に選ばれます。")
        recent_jobs = fetch_recent_send_jobs()
        if recent_jobs:
            with st.expander("最近の送信予約"):
                refresh_col, note_col = st.columns([1.0, 2.4])
                if refresh_col.button("状態を更新", use_container_width=True):
                    sync_send_queue_results()
                    st.rerun()
                note_col.caption("送信予約の進捗は30秒ごとに自動更新されます。")
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
                st.dataframe(
                    pd.DataFrame(recent_jobs).rename(
                        columns={
                            "campaign_name": "配信名",
                            "total_count": "予約数",
                            "sent_count": "送信済み",
                            "failed_count": "失敗",
                            "status": "状態",
                            "created_at": "作成日時",
                        }
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        test_button, send_button = st.columns(2)
        with test_button:
            run_test = st.button("最初の1件でテスト", use_container_width=True)
        with send_button:
            run_all = st.button("指定件数を送信予約", type="primary", use_container_width=True)
        st.info("送信予約を作成すると、送信処理はサーバー側で進みます。予約後はこのタブを閉じても、パソコンの電源を切っても、設定した間隔で送信が続きます。進捗は「最近の送信予約」で確認できます。すべて完了すると、ログイン中のGoogleメールアドレスに完了メールが届きます。")

        if run_test or run_all:
            preflight_errors = []
            if not campaign_name.strip():
                preflight_errors.append("配信名を入力してください。")
            if not smtp_configured():
                preflight_errors.append("送信元メール設定が未完了です。SMTPサーバー、ポート、送信元メールアドレス、SMTPパスワードを確認してください。")
            if send_window_end <= send_window_start:
                preflight_errors.append("メールを送ってよい時間は、「この時間まで」を「この時間から」より後にしてください。")
            if not confirmed:
                preflight_errors.append("送信前の確認にチェックしてください。これは、送信対象が許諾済み、または法的に送信可能な宛先であることを確認するためのチェックです。")
            if preflight_errors:
                st.error("送信前に直す項目があります。\n\n" + "\n".join(f"- {error}" for error in preflight_errors))
            else:
                save_setting("CURRENT_CAMPAIGN_NAME", campaign_name.strip())
                contacts = rows(
                    """
                    select
                        c.*,
                        max(s.sent_at) as last_sent
                    from contacts c
                    left join sends s on s.contact_id = c.id and s.status = 'sent'
                    where c.user_id = ? and c.consent = 1 and c.unsubscribed = 0 and c.email != ''
                      and not exists (
                          select 1
                          from sends sent_campaign
                          where sent_campaign.user_id = c.user_id
                            and sent_campaign.contact_id = c.id
                            and sent_campaign.campaign_key = ?
                            and sent_campaign.status in ('sent', 'queued')
                      )
                    group by c.id
                    order by
                        case when max(s.sent_at) is null then 0 else 1 end,
                        max(s.sent_at) asc,
                        c.id asc
                    """
                    ,
                    (current_user_id(), current_campaign_key),
                )
                if run_test:
                    contacts = contacts[:1]
                else:
                    contacts = contacts[: int(send_limit)]

                if not contacts:
                    st.error("送信できる宛先がありません。宛先一覧、送信済み状況、配信名を確認してください。")
                elif run_all:
                    ok, message = create_send_job(
                        campaign_name,
                        current_campaign_key,
                        subject_template,
                        body_template,
                        contacts,
                        int(delay),
                        send_window_start,
                        send_window_end,
                    )
                    if ok:
                        st.success(message)
                        st.caption("送信予約はサーバー側で処理されます。タブやPCを閉じても、定期実行が有効なら送信が続きます。")
                    else:
                        st.error(message)
                else:
                    progress = st.progress(0)
                    log = st.empty()
                    sent = failed = 0
                    failed_contacts = []
                    user_email = current_user_profile()["email"].strip().lower() or current_user_id()
                    for index, contact in enumerate(contacts):
                        register_unsubscribe_token(contact, user_email)
                        unsubscribe_url = build_unsubscribe_url(contact)
                        subject = render_template(subject_template, contact, unsubscribe_url)
                        body = render_template(ensure_unsubscribe_link_template(body_template), contact, unsubscribe_url)
                        ok, result = send_email(contact["email"], subject, body)
                        execute(
                            "insert into sends(user_id, contact_id, campaign_key, subject, status, error, sent_at) values (?, ?, ?, ?, ?, ?, ?)",
                            (current_user_id(), contact["id"], current_campaign_key, subject, "sent" if ok else "failed", "" if ok else result, now_iso()),
                        )
                        sent += 1 if ok else 0
                        failed += 0 if ok else 1
                        if not ok:
                            failed_contacts.append(
                                {
                                    "id": int(contact["id"]),
                                    "email": contact["email"],
                                    "channel": contact["channel"],
                                    "error": result,
                                }
                            )
                        progress.progress((index + 1) / max(len(contacts), 1))
                        log.write(f"{index + 1}/{len(contacts)}: {contact['email']} - {result}")

                    st.success(f"処理完了: 成功 {sent} 件 / 失敗 {failed} 件")
                    if failed_contacts:
                        st.error("以下のメールアドレスに送信できませんでした。")
                        for item in failed_contacts:
                            columns = st.columns([2.0, 1.6, 3.0, 1.2])
                            columns[0].write(item["email"])
                            columns[1].write(item["channel"] or "-")
                            columns[2].write(item["error"])
                            if columns[3].button("削除して今後取り込まない", key=f"block_failed_{item['id']}"):
                                delete_contact(item["id"], block=True, reason="送信失敗")
                                st.success(f"{item['email']} を削除し、再取り込みしないようにしました")
                                st.rerun()

    query = st.query_params
    token = query.get("unsubscribe_token")
    if token:
        contact = rows("select id from contacts where token = ?", (token,))
        if contact:
            delete_contact(int(contact[0]["id"]))
        st.success("配信停止を受け付けました。宛先一覧からも削除しました。")

    st.divider()
    st.subheader("宛先一覧")
    contacts = fetch_contacts()
    if contacts.empty:
        st.write("まだ宛先がありません。")
    else:
        search_col, sort_col, direction_col = st.columns([2.4, 1.2, 1.0])
        search_text = search_col.text_input(
            "宛先一覧を検索",
            placeholder="メールアドレス、名前、チャンネル名で検索",
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
            lambda row: "停止" if row["unsubscribed"] else ("送信可" if row["consent"] else "要確認"),
            axis=1,
        )

        if search_text:
            search_columns = ["email", "name", "channel"]
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

        header = st.columns([2.0, 2.4, 1.4, 0.9, 1.5, 0.9, 0.7, 0.7])
        headers = ["チャンネル", "email", "name", "状態", "last_sent", "候補へ戻す", "保存", "削除"]
        for column, label in zip(header, headers):
            column.markdown(f"**{label}**")

        for row in visible_contacts.itertuples():
            columns = st.columns([2.0, 2.4, 1.4, 0.9, 1.5, 0.9, 0.7, 0.7])
            edited_channel = columns[0].text_input("channel", value=row.channel or "", key=f"contact_channel_{row.id}", label_visibility="collapsed")
            edited_email = columns[1].text_input("email", value=row.email or "", key=f"contact_email_{row.id}", label_visibility="collapsed")
            edited_name = columns[2].text_input("name", value=row.name or "", key=f"contact_name_{row.id}", label_visibility="collapsed")
            columns[3].write(row.状態)
            columns[4].write(row.last_sent or "-")
            if columns[5].button("戻す", key=f"restore_candidate_{row.id}"):
                ok, message = save_candidate_from_contact(int(row.id))
                if ok:
                    st.success(message)
                    st.rerun()
                else:
                    st.warning(message)
            if columns[6].button("保存", key=f"save_contact_{row.id}"):
                ok, message = update_contact(int(row.id), edited_email, edited_name, edited_channel, True)
                if ok:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)
            if columns[7].button("削除", key=f"delete_contact_{row.id}"):
                delete_contact(int(row.id), block=True, reason="手動削除")
                st.success(f"{row.email} を削除しました")
                st.rerun()

    st.divider()
    st.subheader("YouTube候補一覧")
    candidates = fetch_candidates()
    if candidates.empty:
        st.write("まだ候補チャンネルがありません。")
    else:
        st.markdown("<div id='youtube-candidates-search-top'></div>", unsafe_allow_html=True)
        candidate_search = st.text_input(
            "候補一覧を検索",
            placeholder="チャンネル名、検索キーワードで検索",
        ).strip().lower()
        if st.session_state.pop("scroll_to_candidates_top", False):
            scroll_nonce = int(st.session_state.get("scroll_to_candidates_nonce", 0))
            components.html(
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
                delete_candidate(int(row.id))
                st.success(f"{row.title} を削除しました")
                st.rerun()

        st.divider()
        prev_col, page_status_col, next_col = st.columns([1.0, 2.0, 1.0])
        if prev_col.button(
            "前のページ",
            key="candidates_prev_page_bottom",
            use_container_width=True,
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
            use_container_width=True,
            disabled=int(candidate_current_page) >= candidate_total_pages,
            on_click=change_candidate_page,
            args=(1, candidate_total_pages),
        ):
            pass


if __name__ == "__main__":
    main()
