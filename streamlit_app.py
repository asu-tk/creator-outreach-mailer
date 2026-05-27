        smtp_host = st.text_input("SMTPサーバー", value=current_host)
        smtp_port = st.text_input("SMTPポート", value=current_port)
        smtp_ssl = st.checkbox("SSL接続を使う", value=current_ssl)
        smtp_pass = st.text_input(
            "SMTPパスワード / アプリパスワード",
            type="password",
            placeholder="保存済み" if has_password else "Gmailの場合はアプリパスワード",
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
        st.success(f"保存しました。相手には {mail_from} から届きます。")

    if current_from:
        st.write(f"現在の表示: `{current_from}`")
    if has_password:
        st.caption("パスワードは保存済みです。変更したい時だけ新しいパスワードを入力してください。")

    if st.button("送信元設定を削除"):
        for key in ["SENDER_NAME", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "MAIL_FROM", "SMTP_SSL"]:
            delete_setting(key)
        st.success("送信元設定を削除しました")
        st.rerun()


def import_csv(uploaded_file) -> int:
    frame = pd.read_csv(uploaded_file).fillna("")
    count = 0
    for _, row in frame.iterrows():
        email = str(row.get("email", "")).strip().lower()
        if not email:
            continue
        consent = str(row.get("consent", "")).strip().lower() in {"1", "yes", "true", "y"}
        add_contact(
            email=email,
            name=str(row.get("name", "")),
            channel=str(row.get("channel", "")),
            source=str(row.get("source", "")),
            consent=consent,
        )
        count += 1
    return count


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
            source = st.text_input("取得元・許諾メモ", placeholder="例: 資料請求フォーム 2026-05-28")
            consent = st.checkbox("営業メール送信の許諾がある")
            submitted = st.form_submit_button("追加")
        if submitted:
            if email:
                add_contact(email, name, channel, source, consent)
                st.success("宛先を追加しました")
            else:
                st.error("メールアドレスを入力してください")

        st.subheader("CSV取り込み")
        uploaded = st.file_uploader("CSVファイル", type=["csv"])
        st.caption("列: email, name, channel, source, consent")
        if uploaded and st.button("取り込む"):
            count = import_csv(uploaded)
            st.success(f"{count}件を取り込みました")

    with right:
        st.subheader("メール作成")
        subject_template = st.text_input("件名", value="${channel}の海外視聴者向け翻訳について")
        body_template = st.text_area(
            "本文",
            value="""${name}へ

${channel}を拝見しました。
海外視聴者向けの字幕・翻訳と説明文の多言語化で、お役に立てそうだと思いご連絡しました。

もしご興味があれば、1本だけ無料で翻訳サンプルを作れます。

不要な場合はこちらから配信停止できます。
${unsubscribe_url}""",
            height=260,
        )
        delay = st.number_input("送信間隔（秒）", min_value=1, max_value=60, value=3)
        confirmed = st.checkbox("送信対象が許諾済み、または法的に送信可能な宛先であることを確認しました")

        target_count = rows("select count(*) as count from contacts where consent = 1 and unsubscribed = 0")[0]["count"]
        st.metric("送信対象", f"{target_count}件")

        test_button, send_button = st.columns(2)
        with test_button:
            run_test = st.button("最初の1件でテスト", use_container_width=True)
        with send_button:
            run_all = st.button("送信対象全員へ送信", type="primary", use_container_width=True)

        if run_test or run_all:
            if not confirmed:
                st.error("送信前の確認にチェックしてください")
            else:
                contacts = rows("select * from contacts where consent = 1 and unsubscribed = 0 order by id")
                if run_test:
                    contacts = contacts[:1]

                progress = st.progress(0)
                log = st.empty()
                sent = failed = 0
                base_url = get_secret("APP_BASE_URL", "http://127.0.0.1:8501")

                for index, contact in enumerate(contacts):
                    unsubscribe_url = f"{base_url}/?unsubscribe_token={contact['token']}"
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
        execute("update contacts set unsubscribed = 1 where token = ?", (token,))
        st.success("配信停止を受け付けました")

    st.divider()
    st.subheader("宛先一覧")
    contacts = fetch_contacts()
    if contacts.empty:
        st.write("まだ宛先がありません。")
    else:
        contacts["状態"] = contacts.apply(
            lambda row: "停止" if row["unsubscribed"] else ("送信可" if row["consent"] else "要確認"),
            axis=1,
        )
        st.dataframe(
            contacts[["email", "name", "channel", "source", "状態", "last_sent"]],
            use_container_width=True,
            hide_index=True,
        )


if __name__ == "__main__":
    main()
