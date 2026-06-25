# shipping-stop-automation

配送遅延などでお客様からキャンセル希望があったとき、配送会社（SGH Global / 佐川グローバル）あての
**「転送依頼（配送停止）メールの下書き」を自動作成する**半自動ツール。

スプレッドシートに注文番号を貼ってボタンを押すと、社内システムから追跡番号・受け取り人名を取得し、
注文に応じた **Gmail アカウント（楽天用／その他用）** に下書きを作る。送信は最終確認のうえ手動で行う。

## 処理の流れ

```
スプレッドシートの左タブ（注文番号）に注文番号を貼り付け
   ↓
メニュー「📦 転送依頼」→「転送依頼の下書きを作成」を押す（gas_button.js）
   ↓
GitHub Actions（stop_request.yml）が起動
   ↓
stop_request.py が Playwright で送信先サイト（APP_DOMAIN）にログイン
   → 注文詳細(sales/view)から「追跡番号」「受け取り人名」を取得
   ↓
注文番号の頭6桁で振り分け
   ├─ 楽天（店舗コード6桁で判定） → 楽天用Gmailのミニ・スクリプトに依頼
   └─ その他                    → その他用Gmailのミニ・スクリプトに依頼
   ↓
各 Gmail アカウント内に下書きが作成される（gas_draft_maker.js / GmailApp）
   ↓
スプレッドシートに結果（追跡番号・氏名・ステータス）を書き戻す
   ↓
利用者が下書きを確認し、署名を足して送信
```

## 仕組み

| 役割 | 使用技術 |
|---|---|
| 起動ボタン | Google Apps Script（`gas_button.js`）→ GitHub API で workflow_dispatch |
| 実行基盤 | GitHub Actions（`ubuntu-22.04`、手動起動のみ） |
| 情報取得 | Python + Playwright（`stop_request.py`） |
| 下書き作成 | 各 Gmail の GAS ミニ・スクリプト（`gas_draft_maker.js` / `GmailApp`） |
| データ管理 | Google スプレッドシート（gspread） |

### なぜ Gmail の下書きをミニ・スクリプトで作るのか
社内システムのメール機能は「その注文のお客様あて」専用で、配送会社など自由な宛先に送れない。
また 1 つの認証では他アカウントに下書きを作れないため、**楽天用／その他用の各 Gmail アカウントに
小さな GAS ウェブアプリ（doPost）を置き**、Python から呼び出して各アカウント内に下書きを作る。
この方式なら Gmail のトークン/パスワードを GitHub に保存せずに済む。

## 店舗（送信先）判定

注文番号の頭6桁で、どちらの Gmail に下書きを作るかを決める。
店舗コード→店舗名の対応表は、コードに直接書かず Secret `RAKUTEN_PREFIXES_JSON` から読み込む。

| 頭6桁 | 店舗 | 下書き先 |
|---|---|---|
| 登録済みの店舗コード6桁 | 楽天店舗 | 楽天用Gmail |
| 上記以外 | その他 | その他用Gmail |

`RAKUTEN_PREFIXES_JSON` の形式（例）：`{"店舗コード6桁": "店舗A", "店舗コード6桁": "店舗B"}`
楽天店舗が増えたら、この Secret を編集する。

## スプレッドシート構成（左タブ＝注文番号タブ）

| 列 | 内容 | 記入者 |
|---|---|---|
| A | 注文番号 | 人（貼り付け） |
| B | 送信先（楽天 / その他） | スクリプト |
| C | 追跡番号 | スクリプト |
| D | 受け取り人名 | スクリプト |
| E | ステータス | スクリプト |
| F | 処理日時 | スクリプト |

### ステータス
| 表示 | 意味 |
|---|---|
| ✅ 下書き作成済み（楽天／その他） | 正常。該当 Gmail に下書きあり |
| ❌ 注文が見つからない | 社内システムで注文番号が見つからない |
| ❌ 追跡番号が取得できない（要確認） | 詳細ページから追跡番号を拾えなかった |
| ❌ 下書き作成失敗 / ❌（その他） | ミニ・スクリプト呼び出しや処理中のエラー |

## セットアップ

### GitHub Secrets
| Secret名 | 内容 |
|---|---|
| `APP_DOMAIN` | 送信先サイトのドメイン（例: `app.example.com`） |
| `RAKUTEN_PREFIXES_JSON` | 店舗コード→店舗名の対応表（上記「店舗判定」の形式） |
| `LOGIN_ID_1` / `LOGIN_PASS_1` | 送信先サイトの Basic 認証 |
| `LOGIN_ID_2` / `LOGIN_PASS_2` | 送信先サイトのフォームログイン |
| `GOOGLE_CREDENTIALS_JSON` | GCP サービスアカウントの JSON キー |
| `STOP_SPREADSHEET_ID` | 注文番号タブがあるスプレッドシートのID |
| `RAKUTEN_DRAFT_URL` | 楽天用Gmail のミニ・スクリプト ウェブアプリURL |
| `OTHER_DRAFT_URL` | その他用Gmail のミニ・スクリプト ウェブアプリURL |
| `DRAFT_SECRET` | ミニ・スクリプトと共有する合言葉 |

> サービスアカウントには対象スプレッドシートの編集権限を付与しておくこと。

### GAS ミニ・スクリプト（`gas_draft_maker.js`）
楽天用Gmail・その他用Gmail の**各アカウント**で、`gas_draft_maker.js` 冒頭の手順に従って
ウェブアプリとしてデプロイし、発行 URL を上記 Secrets に登録する。

### GAS ボタン（`gas_button.js`）
スプレッドシートの Apps Script に貼り付け、`GITHUB_OWNER` を設定、
スクリプトプロパティに `GITHUB_TOKEN`（Actions: Read and write）を登録する。

## ⚠️ 初回テストでの調整ポイント
注文詳細ページ（sales/view）のどの項目が「追跡番号」「受け取り人名」かは、実画面を見て確定する。
`stop_request.py` の `TRACKING_KEYWORDS` / `NAME_KEYWORDS` と `open_order_detail()` を、
初回実行ログ（値はマスク表示）を見ながら調整する。

## ローカル実行
```bash
pip install -r requirements.txt
playwright install chromium
# 環境変数を設定してから実行
python stop_request.py
```
