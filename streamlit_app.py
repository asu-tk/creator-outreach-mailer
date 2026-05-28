from __future__ import annotations

import os
import secrets
import smtplib
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from string import Template
from urllib.parse import quote

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "mailer.sqlite3"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
                email text not null unique,
                name text not null default '',
                channel text not null default '',
                youtube_channel_id text not null default '',
                source text not null default '',
                consent integer not null default 0,
                unsubscribed integer not null default 0,
                token text not null unique,
                created_at text not null
            );

            create table if not exists sends (
                id integer primary key autoincrement,
                contact_id integer not null,
                subject text not null,
                status text not null,
                error text not null default '',
                sent_at text not null,
                foreign key(contact_id) references contacts(id)
            );

            create table if not exists settings (
                key text primary key,
                value text not null
            );

            create table if not exists youtube_candidates (
                id integer primary key autoincrement,
                channel_id text not null unique,
                title text not null default '',
                channel_url text not null default '',
                subscriber_count integer not null default 0,
                video_count integer not null default 0,
                view_count integer not null default 0,
                description text not null default '',
                keyword text not null default '',
                created_at text not null
            );
            """
        )
        columns = [row[1] for row in db.execute("pragma table_info(contacts)").fetchall()]
        if "youtube_channel_id" not in columns:
            db.execute("alter table contacts add column youtube_channel_id text not null default ''")
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
                coalesce(max(s.sent_at), '') as last_sent
            from contacts c
            left join sends s on s.contact_id = c.id
            group by c.id
            order by c.id desc
            """,
            db,
        )


def fetch_candidates() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as db:
        return pd.read_sql_query(
            """
            select
                id,
                channel_id,
                title,
                channel_url,
                subscriber_count,
                video_count,
                view_count,
                keyword,
                created_at
            from youtube_candidates
            order by id desc
            """,
            db,
        )


def execute(query: str, params: tuple = ()) -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute(query, params)
        db.commit()


def get_setting(key: str, default: str = "") -> str:
    if not DB_PATH.exists():
        return default
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute("select value from settings where key = ?", (key,)).fetchone()
        return str(row[0]) if row else default


def save_setting(key: str, value: str) -> None:
    execute(
        "insert into settings(key, value) values(?, ?) on conflict(key) do update set value = excluded.value",
        (key, value),
    )


def delete_setting(key: str) -> None:
    execute("delete from settings where key = ?", (key,))


def delete_contact(contact_id: int) -> None:
    execute("delete from sends where contact_id = ?", (contact_id,))
    execute("delete from contacts where id = ?", (contact_id,))


def delete_candidate(candidate_id: int) -> None:
    execute("delete from youtube_candidates where id = ?", (candidate_id,))


def save_candidate_from_contact(contact_id: int) -> tuple[bool, str]:
    contact = rows("select * from contacts where id = ?", (contact_id,))
    if not contact:
        return False, "宛先が見つかりません"
    item = contact[0]
    channel_id = item["youtube_channel_id"]
    if not channel_id:
        return False, "この宛先はYouTube候補から登録されたものではありません"
    if youtube_channel_in_candidates(channel_id):
        delete_contact(contact_id)
        return True, "すでに候補一覧にあるため、宛先一覧からだけ削除しました"

    execute(
        """
        insert into youtube_candidates
        (channel_id, title, channel_url, subscriber_count, video_count, view_count, description, keyword, created_at)
        values (?, ?, ?, 0, 0, 0, '', '宛先から戻す', ?)
        """,
        (
            channel_id,
            item["channel"],
            f"https://www.youtube.com/channel/{channel_id}",
            now_iso(),
        ),
    )
    delete_contact(contact_id)
    return True, "YouTube候補一覧に戻しました"


def contact_exists(email: str) -> bool:
    normalized_email = email.strip().lower()
    if not normalized_email:
        return False
    return bool(rows("select id from contacts where email = ?", (normalized_email,)))


def candidate_contact_exists(channel: str) -> bool:
    normalized_channel = channel.strip()
    if not normalized_channel:
        return False
    return bool(rows("select id from contacts where email = '' and channel = ?", (normalized_channel,)))


def youtube_channel_in_contacts(channel_id: str) -> bool:
    if not channel_id:
        return False
    return bool(rows("select id from contacts where youtube_channel_id = ?", (channel_id,)))


def youtube_channel_in_candidates(channel_id: str) -> bool:
    if not channel_id:
        return False
    return bool(rows("select id from youtube_candidates where channel_id = ?", (channel_id,)))


def update_contact(contact_id: int, email: str, name: str, channel: str, consent: bool) -> tuple[bool, str]:
    normalized_email = email.strip().lower()
    duplicate = rows(
        "select id from contacts where email = ? and id != ?",
        (normalized_email, contact_id),
    ) if normalized_email else []
    if duplicate:
        return False, "このメールアドレスはすでに登録されています"
    execute(
        """
        update contacts
        set email = ?, name = ?, channel = ?, consent = ?
        where id = ?
        """,
        (normalized_email, name.strip(), channel.strip(), 1 if consent else 0, contact_id),
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
    if youtube_channel_in_contacts(channel_id) or youtube_channel_in_candidates(channel_id):
        return False
    execute(
        """
        insert or ignore into youtube_candidates
        (channel_id, title, channel_url, subscriber_count, video_count, view_count, description, keyword, created_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            channel_id,
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


def search_youtube_channels(keyword: str, min_subs: int, max_subs: int, max_results: int) -> tuple[int, int]:
    found = 0
    saved = 0
    page_token = ""
    max_results = max(1, min(max_results, 200))

    while found < max_results:
        search_data = youtube_api_get(
            "search",
            {
                "part": "snippet",
                "type": "channel",
                "q": keyword,
                "maxResults": min(50, max_results - found),
                "pageToken": page_token,
            },
        )
        channel_ids = [
            item["snippet"]["channelId"]
            for item in search_data.get("items", [])
            if item.get("snippet", {}).get("channelId")
        ]
        if not channel_ids:
            break

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
                keyword,
            )
            if was_saved:
                saved += 1

        found += len(channel_ids)
        page_token = search_data.get("nextPageToken", "")
        if not page_token:
            break

    return found, saved


def rows(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        return list(db.execute(query, params))


def smtp_configured() -> bool:
    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "MAIL_FROM"]
    return all(get_secret(key) for key in required)


def render_template(text: str, contact: sqlite3.Row, unsubscribe_url: str) -> str:
    values = {
        "name": contact["name"] or "ご担当者",
        "email": contact["email"],
        "channel": contact["channel"] or "貴チャンネル",
        "unsubscribe_url": unsubscribe_url,
    }
    return Template(text).safe_substitute(values)


def build_unsubscribe_mailto(contact: sqlite3.Row) -> str:
    reply_to = get_secret("UNSUBSCRIBE_EMAIL", "") or get_secret("SMTP_USER", "")
    subject = "配信停止希望"
    body = (
        "配信停止を希望します。\n\n"
        f"対象メールアドレス: {contact['email']}\n"
        f"チャンネル名: {contact['channel'] or '-'}\n"
    )
    return f"mailto:{reply_to}?subject={quote(subject)}&body={quote(body)}"


def send_email(to_email: str, subject: str, body: str) -> tuple[bool, str]:
    if not smtp_configured():
        return True, "DRY_RUN: SMTP設定がないため実送信はしていません"

    message = EmailMessage()
    message["From"] = get_secret("MAIL_FROM")
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    host = get_secret("SMTP_HOST")
    port = int(get_secret("SMTP_PORT", "587"))
    use_ssl = get_secret("SMTP_SSL").lower() in {"1", "true", "yes"}

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                smtp.login(get_secret("SMTP_USER"), get_secret("SMTP_PASS"))
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(get_secret("SMTP_USER"), get_secret("SMTP_PASS"))
                smtp.send_message(message)
        return True, "送信しました"
    except Exception as exc:
        return False, str(exc)


def add_contact(email: str, name: str, channel: str, consent: bool, youtube_channel_id: str = "") -> bool:
    normalized_email = email.strip().lower()
    if normalized_email and contact_exists(normalized_email):
        return False
    if youtube_channel_id and youtube_channel_in_contacts(youtube_channel_id):
        return False
    if not normalized_email and candidate_contact_exists(channel):
        return False
    execute(
        """
        insert into contacts
        (email, name, channel, youtube_channel_id, source, consent, unsubscribed, token, created_at)
        values (?, ?, ?, ?, '', ?, 0, ?, ?)
        """,
        (
            normalized_email,
            name.strip(),
            channel.strip(),
            youtube_channel_id.strip(),
            1 if consent else 0,
            secrets.token_urlsafe(24),
            now_iso(),
        ),
    )
    return True


def settings_panel() -> None:
    st.subheader("送信元メール設定")
    st.caption("ここで登録したメールアカウントから送信されます。相手には「送信者表示名 <送信元メールアドレス>」の形で見えます。")

    current_from = get_setting("MAIL_FROM")
    current_user = get_setting("SMTP_USER")
    current_host = get_setting("SMTP_HOST", "smtp.gmail.com")
    current_port = get_setting("SMTP_PORT", "587")
    current_ssl = get_setting("SMTP_SSL", "false").lower() in {"1", "true", "yes"}
    current_youtube_api_key = get_setting("YOUTUBE_API_KEY")
    has_password = bool(get_setting("SMTP_PASS"))

    with st.form("mail_settings"):
        sender_name = st.text_input("送信者表示名", value=get_setting("SENDER_NAME", "UniVerse"))
        sender_email = st.text_input("送信元メールアドレス", value=current_user)
        smtp_host = st.text_input("SMTPサーバー", value=current_host)
        smtp_port = st.text_input("SMTPポート", value=current_port)
        smtp_ssl = st.checkbox("SSL接続を使う", value=current_ssl)
        smtp_pass = st.text_input(
            "SMTPパスワード / アプリパスワード",
            type="password",
            placeholder="保存済み" if has_password else "Gmailの場合はアプリパスワード",
        )
        youtube_api_key = st.text_input(
            "YouTube APIキー",
            type="password",
            placeholder="保存済み" if current_youtube_api_key else "Google Cloud ConsoleのAPIキー",
        )
        submitted = st.form_submit_button("送信元設定を保存")

    if submitted:
        mail_from = f"{sender_name.strip()} <{sender_email.strip()}>" if sender_name.strip() else sender_email.strip()
        save_setting("SENDER_NAME", sender_name.strip())
        save_setting("SMTP_HOST", smtp_host.strip())
        save_setting("SMTP_PORT", smtp_port.strip())
        save_setting("SMTP_USER", sender_email.strip())
        save_setting("MAIL_FROM", mail_from)
        save_setting("SMTP_SSL", "true" if smtp_ssl else "false")
        if smtp_pass:
            save_setting("SMTP_PASS", smtp_pass)
        if youtube_api_key:
            save_setting("YOUTUBE_API_KEY", youtube_api_key.strip())
        st.success(f"保存しました。相手には {mail_from} から届きます。")

    if current_from:
        st.write(f"現在の表示: `{current_from}`")
    if has_password:
        st.caption("パスワードは保存済みです。変更したい時だけ新しいパスワードを入力してください。")
    if current_youtube_api_key:
        st.caption("YouTube APIキーは保存済みです。変更したい時だけ新しいキーを入力してください。")

    if st.button("送信元設定を削除"):
        for key in ["SENDER_NAME", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "MAIL_FROM", "SMTP_SSL", "APP_BASE_URL", "UNSUBSCRIBE_EMAIL", "YOUTUBE_API_KEY"]:
            delete_setting(key)
        st.success("送信元設定を削除しました")
        st.rerun()


def import_csv(uploaded_file) -> tuple[int, int]:
    frame = pd.read_csv(uploaded_file).fillna("")
    added = 0
    skipped = 0
    seen_in_file: set[str] = set()
    for _, row in frame.iterrows():
        email = str(row.get("email", "")).strip().lower()
        if not email:
            continue
        if email in seen_in_file:
            skipped += 1
            continue
        seen_in_file.add(email)
        was_added = add_contact(
            email=email,
            name=str(row.get("name", "")),
            channel=str(row.get("channel", "")),
            consent=True,
        )
        if was_added:
            added += 1
        else:
            skipped += 1
    return added, skipped


def main() -> None:
    st.set_page_config(page_title="Creator Outreach Mailer", layout="wide")
    init_db()

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
                was_added = add_contact(email, name, channel, consent)
                if was_added:
                    st.success("宛先を追加しました")
                else:
                    st.warning("このメールアドレスはすでに登録されています")
            else:
                st.error("メールアドレスを入力してください")

        st.subheader("CSV取り込み")
        uploaded = st.file_uploader("CSVファイル", type=["csv"])
        st.caption("列: email, name, channel。CSVで取り込んだ宛先は自動的に送信可になります。")
        if uploaded and st.button("取り込む"):
            added, skipped = import_csv(uploaded)
            st.success(f"{added}件を取り込みました。重複は{skipped}件スキップしました。")

        st.subheader("YouTube候補検索")
        st.caption("メールアドレスは取得しません。条件に合うチャンネル候補だけを保存します。")
        with st.form("youtube_search"):
            yt_keyword = st.text_input("検索キーワード", placeholder="例: 料理 レシピ / ゲーム実況 / 英会話")
            yt_min_subs = st.number_input("登録者数 最小", min_value=0, value=1000, step=1000)
            yt_max_subs = st.number_input("登録者数 最大（0なら上限なし）", min_value=0, value=100000, step=1000)
            yt_max_results = st.number_input("最大取得件数", min_value=1, max_value=200, value=50)
            yt_submitted = st.form_submit_button("候補を検索して保存")
        if yt_submitted:
            if not yt_keyword.strip():
                st.error("検索キーワードを入力してください")
            else:
                try:
                    checked, saved = search_youtube_channels(
                        yt_keyword.strip(),
                        int(yt_min_subs),
                        int(yt_max_subs),
                        int(yt_max_results),
                    )
                    st.success(f"{checked}件を確認し、新規候補を{saved}件保存しました。")
                except Exception as exc:
                    st.error(str(exc))

    with right:
        st.subheader("メール作成")
        subject_template = st.text_input("件名", value="御社YouTubeチャンネルの海外視聴者向け翻訳について")
        body_template = st.text_area(
            "本文",
            value="""突然のご連絡失礼いたします。
YouTube多言語化アプリ「UniVerse」開発元チームの綾瀬と申します。

貴社様のYouTube動画を拝見させて頂きました。

動画の雰囲気や企画がとても魅力的で「海外視聴者にも届く可能性があるチャンネル」だと感じ、ご連絡させて頂きました。


YouTubeアルゴリズムでは
・タイトル
・説明文
・字幕

を多言語化することで、海外からの再生やおすすめ表示が伸びる傾向があります。


ただ実際は
・翻訳作業に時間がかかる
・複数言語対応が難しい
・各言語ごとの登録が面倒

などの理由から、海外対応を継続できないor全くやらないというチャンネル運営者様も少なくありません。


UniVerseではYouTubeのタイトル・説明文を主要28言語へ自動翻訳し、海外視聴者向けのローカライズ作業を大幅に効率化できます。

これまで何時間もかかっていた作業を、数分レベルまで短縮できるのが特徴です。


「海外の視聴者にも動画を届けたい」
そう考えている方には、非常に相性の良いアプリとなっております。

もしご興味がありましたら、ぜひ一度ご覧ください。


YouTubeサブスク型翻訳アプリ｜UniVerse
https://universeapp.jp/

不要な場合は、お手数ですが「配信停止希望」とご返信ください。""",
            height=560,
        )
        delay = st.number_input("送信間隔（秒）", min_value=1, max_value=60, value=3)
        send_limit = st.number_input("今回送信する件数", min_value=1, max_value=500, value=50)
        confirmed = st.checkbox("送信対象が許諾済み、または法的に送信可能な宛先であることを確認しました")

        target_count = rows("select count(*) as count from contacts where consent = 1 and unsubscribed = 0 and email != ''")[0]["count"]
        st.metric("送信対象", f"{target_count}件")
        st.caption("送信対象は、未送信の宛先を優先し、その後は最終送信日時が古い順に選ばれます。")

        test_button, send_button = st.columns(2)
        with test_button:
            run_test = st.button("最初の1件でテスト", use_container_width=True)
        with send_button:
            run_all = st.button("指定件数を送信", type="primary", use_container_width=True)

        if run_test or run_all:
            if not confirmed:
                st.error("送信前の確認にチェックしてください")
            else:
                contacts = rows(
                    """
                    select
                        c.*,
                        max(s.sent_at) as last_sent
                    from contacts c
                    left join sends s on s.contact_id = c.id and s.status = 'sent'
                    where c.consent = 1 and c.unsubscribed = 0 and c.email != ''
                    group by c.id
                    order by
                        case when max(s.sent_at) is null then 0 else 1 end,
                        max(s.sent_at) asc,
                        c.id asc
                    """
                )
                if run_test:
                    contacts = contacts[:1]
                else:
                    contacts = contacts[: int(send_limit)]

                progress = st.progress(0)
                log = st.empty()
                sent = failed = 0
                for index, contact in enumerate(contacts):
                    unsubscribe_url = build_unsubscribe_mailto(contact)
                    subject = render_template(subject_template, contact, unsubscribe_url)
                    body = render_template(body_template, contact, unsubscribe_url)
                    ok, result = send_email(contact["email"], subject, body)
                    execute(
                        "insert into sends(contact_id, subject, status, error, sent_at) values (?, ?, ?, ?, ?)",
                        (contact["id"], subject, "sent" if ok else "failed", "" if ok else result, now_iso()),
                    )
                    sent += 1 if ok else 0
                    failed += 0 if ok else 1
                    progress.progress((index + 1) / max(len(contacts), 1))
                    log.write(f"{index + 1}/{len(contacts)}: {contact['email']} - {result}")
                    if index < len(contacts) - 1:
                        time.sleep(int(delay))

                st.success(f"処理完了: 成功 {sent} 件 / 失敗 {failed} 件")

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
        search_text = st.text_input(
            "宛先一覧を検索",
            placeholder="メールアドレス、名前、チャンネル名で検索",
        ).strip().lower()
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

        st.caption(f"{len(contacts)}件表示中")

        if contacts.empty:
            st.write("検索条件に合う宛先はありません。")
            return

        header = st.columns([2.0, 2.4, 1.4, 0.9, 1.5, 0.9, 0.7, 0.7])
        headers = ["チャンネル", "email", "name", "状態", "last_sent", "候補へ戻す", "保存", "削除"]
        for column, label in zip(header, headers):
            column.markdown(f"**{label}**")

        for row in contacts.itertuples():
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
                delete_contact(int(row.id))
                st.success(f"{row.email} を削除しました")
                st.rerun()

    st.divider()
    st.subheader("YouTube候補一覧")
    candidates = fetch_candidates()
    if candidates.empty:
        st.write("まだ候補チャンネルがありません。")
    else:
        candidate_search = st.text_input(
            "候補一覧を検索",
            placeholder="チャンネル名、検索キーワードで検索",
        ).strip().lower()
        if candidate_search:
            mask = candidates[["title", "keyword"]].fillna("").astype(str).apply(
                lambda column: column.str.lower().str.contains(candidate_search, regex=False)
            ).any(axis=1)
            candidates = candidates[mask]

        st.caption(f"{len(candidates)}件表示中")
        if candidates.empty:
            st.write("検索条件に合う候補はありません。")
            return

        header = st.columns([2.2, 1.0, 1.0, 1.0, 1.2, 1.0, 0.9, 0.7])
        headers = ["チャンネル", "登録者数", "動画数", "総再生数", "検索キーワード", "開く", "宛先", "削除"]
        for column, label in zip(header, headers):
            column.markdown(f"**{label}**")

        for row in candidates.itertuples():
            columns = st.columns([2.2, 1.0, 1.0, 1.0, 1.2, 1.0, 0.9, 0.7])
            columns[0].write(row.title or "-")
            columns[1].write(f"{int(row.subscriber_count):,}")
            columns[2].write(f"{int(row.video_count):,}")
            columns[3].write(f"{int(row.view_count):,}")
            columns[4].write(row.keyword or "-")
            columns[5].markdown(f"[YouTubeで開く]({row.channel_url})")
            if columns[6].button("宛先に登録", key=f"candidate_to_contact_{row.id}"):
                added = add_contact("", "", row.title or "", True, row.channel_id)
                if added:
                    delete_candidate(int(row.id))
                    st.success(f"{row.title} を宛先一覧に追加しました。メールアドレスを入力して保存してください。")
                    st.rerun()
                else:
                    st.warning("このチャンネルはすでに宛先一覧に登録されています")
            if columns[7].button("削除", key=f"delete_candidate_{row.id}"):
                delete_candidate(int(row.id))
                st.success(f"{row.title} を削除しました")
                st.rerun()


if __name__ == "__main__":
    main()
