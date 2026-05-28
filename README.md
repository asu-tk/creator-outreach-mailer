# Creator Outreach Mailer

YouTuber / creator outreach 用の小さなメール管理アプリです。

このアプリは、許諾済み、または法的に送信可能な宛先だけを対象にする前提で作っています。CSV取り込み、宛先管理、本文テンプレート、テスト送信、本送信、配信停止リンク、送信履歴に対応しています。

## おすすめ: Streamlit版

個人用のWebアプリとして使うなら、こちらがおすすめです。

最初にStreamlitを入れます。

```powershell
pip install -r requirements.txt
```

起動します。

```powershell
streamlit run streamlit_app.py
```

ブラウザで開きます。

```text
http://localhost:8501
```

`start-streamlit.ps1` を使う場合は、PowerShellで以下を実行します。

```powershell
.\start-streamlit.ps1
```

## ファイル取り込み

```csv
email,name,channel,consent
creator@example.com,山田さん,Sample Channel,yes
```

CSV / TSV / XLSX / XLS に対応しています。Googleスプレッドシートは「ファイル > ダウンロード > Microsoft Excel（.xlsx）」で保存して取り込めます。

列名は `email` / `メールアドレス`、`channel` / `チャンネル名`、`name` / `名前` などを自動判別します。取り込んだ宛先は自動的に送信可になります。

## SMTP設定

SMTP設定がない場合、送信ボタンを押しても実際のメールは送られず、テスト記録だけ残ります。

Streamlit版では、アプリ画面の「送信元メール設定」から保存できます。ここに設定した内容で、相手には以下のように表示されます。

```text
送信者表示名 <送信元メールアドレス>
```

例:

```text
UniVerse <yourname@gmail.com>
```

Gmailで送る場合は、通常のGoogleアカウントのパスワードではなく、Googleアカウントで発行する「アプリパスワード」を使います。

保存したくない場合や、Streamlit Cloud上でより安全に管理したい場合は、Secretsを使います。

Streamlit版では、`.streamlit/secrets.toml` を作って設定します。

```toml
SMTP_HOST = "smtp.example.com"
SMTP_PORT = "587"
SMTP_USER = "your-account@example.com"
SMTP_PASS = "your-password-or-app-password"
MAIL_FROM = "Your Service <your-account@example.com>"
SMTP_SSL = "false"
APP_BASE_URL = "http://localhost:8501"
```

サンプルは `.streamlit/secrets.example.toml` にあります。

## GitHub + Streamlit Cloudで使う場合

1. GitHubにこのフォルダをアップロードします。
2. Streamlit Community Cloudで新しいアプリを作ります。
3. Repositoryを選びます。
4. Main file path に `streamlit_app.py` を指定します。
5. SecretsにSMTP設定を入れます。

公開URLを自分だけで使いたい場合は、Streamlit Cloud側で公開範囲や共有先を絞ってください。

## 旧ローカル版

Streamlitを使わず、Codex同梱のPythonだけで起動する簡易版も残しています。

```powershell
& "C:\Users\takeyoshi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" app.py
```

ブラウザで開きます。

```text
http://127.0.0.1:8787
```

実送信する場合は、起動前に環境変数を設定します。

```powershell
$env:SMTP_HOST="smtp.example.com"
$env:SMTP_PORT="587"
$env:SMTP_USER="your-account@example.com"
$env:SMTP_PASS="your-password-or-app-password"
$env:MAIL_FROM="Your Service <your-account@example.com>"
& "C:\Users\takeyoshi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" app.py
```

SSL接続が必要なSMTPでは、追加で指定します。

```powershell
$env:SMTP_SSL="true"
```

## 本文テンプレートで使える項目

- `$name`
- `$email`
- `$channel`
- `$unsubscribe_url`

## 注意

広告・営業メールは、送信先の国や地域によって法律が変わります。日本では広告宣伝メールは原則オプトインです。米国向けでもCAN-SPAM対応が必要です。配信停止した宛先や、送信許諾が確認できない宛先には送らない運用にしてください。
