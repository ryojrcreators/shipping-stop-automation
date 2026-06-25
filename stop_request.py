import os
import re
import json
from datetime import datetime

import requests
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright
from urllib.parse import quote

# ============================================================
# 設定（すべて環境変数 / GitHub Secrets から読み込み）
# ============================================================
DOMAIN = os.environ["APP_DOMAIN"]
LOGIN_ID_1   = os.environ["LOGIN_ID_1"]
LOGIN_PASS_1 = os.environ["LOGIN_PASS_1"]
LOGIN_ID_2   = os.environ["LOGIN_ID_2"]
LOGIN_PASS_2 = os.environ["LOGIN_PASS_2"]

SPREADSHEET_ID = os.environ["STOP_SPREADSHEET_ID"]

# 下書き作成用ミニ・スクリプト（GAS Web App）のURLと合言葉
# ※ 配送会社のアドレス・メール文面は GAS 側に持たせており、ここ（GitHub）には載せない。
RAKUTEN_DRAFT_URL = os.environ["RAKUTEN_DRAFT_URL"]
OTHER_DRAFT_URL   = os.environ["OTHER_DRAFT_URL"]
DRAFT_SECRET      = os.environ["DRAFT_SECRET"]

# テスト用：true なら「✅ 下書き作成済み」の行も再処理する（通常運用では false）
FORCE_ALL = os.environ.get("FORCE_ALL", "").strip().lower() == "true"

# 楽天店舗の注文番号プレフィックス（頭6桁）→ 店舗名。
# ここに一致した注文 → 楽天Gmailに下書き。一致しない注文 → その他Gmailに下書き。
# 店舗コード・店舗名は Secret RAKUTEN_PREFIXES_JSON（JSON文字列）から読み込む。
# Public リポジトリに店舗情報を出さないため。店舗追加はこのSecretを編集する。
# 形式の例: {"頭6桁": "店舗A", "頭6桁": "店舗B"}
RAKUTEN_PREFIXES = json.loads(os.environ["RAKUTEN_PREFIXES_JSON"])

# スプレッドシートの列（0始まり）
COL_ORDER  = 0  # A: 注文番号
COL_DEST   = 1  # B: 送信先（楽天 / その他）
COL_TRACK  = 2  # C: 追跡番号
COL_NAME   = 3  # D: 受け取り人名
COL_STATUS = 4  # E: ステータス
COL_DATE   = 5  # F: 処理日時

HEADER = ["注文番号", "送信先", "追跡番号", "受け取り人名", "ステータス", "処理日時"]
STATUS_DONE = "✅ 下書き作成済み"

BASE_URL = f"https://{DOMAIN}"

# ------------------------------------------------------------
# 注文詳細ページ(sales/view)のラベル名（実画面で確認済み）。
# このラベルに一致したセルの「値」を取り出す。
#   Tracking Number … 追跡番号
#   Recipient Name  … 受取人名
# ------------------------------------------------------------
TRACKING_KEYWORDS = ["tracking number", "追跡番号"]
NAME_KEYWORDS     = ["recipient name", "受取人名", "受け取り人名"]


def mask(s):
    """個人情報を実行ログに出さないためのマスク。
    数字→#、英字→A、日本語→▮ に置き換え、桁数・形だけ分かるようにする。"""
    if not s:
        return "(空)"
    s = re.sub(r"[0-9]", "#", s)
    s = re.sub(r"[A-Za-z]", "A", s)
    s = re.sub(r"[一-龥ぁ-んァ-ヶ々ー]", "▮", s)
    return s


def get_sheet():
    creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    creds = Credentials.from_service_account_info(
        creds_json, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(SPREADSHEET_ID).sheet1

    # 1行目が空ならヘッダーを入れる（初回のみ）
    first = sheet.row_values(1)
    if not any(c.strip() for c in first):
        sheet.update(range_name="A1", values=[HEADER])
    return sheet


def classify(order_number):
    """注文番号から送信先（どのGmailのミニ・スクリプトに渡すか）を決める。"""
    prefix = order_number.strip()[:6]
    if prefix in RAKUTEN_PREFIXES:
        return RAKUTEN_DRAFT_URL, "楽天"
    return OTHER_DRAFT_URL, "その他"


def login(page):
    login_id_enc   = quote(LOGIN_ID_1, safe="")
    login_pass_enc = quote(LOGIN_PASS_1, safe="")
    login_url = f"https://{login_id_enc}:{login_pass_enc}@{DOMAIN}/"

    print("ログイン中...")
    page.goto(login_url, wait_until="networkidle")
    page.click('a:has-text("Login"), button:has-text("Login")')
    page.wait_for_load_state("networkidle")
    page.fill('input[name="username"]', LOGIN_ID_2)
    page.fill('input[type="password"]', LOGIN_PASS_2)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("networkidle")
    print("ログイン完了")


def open_order_detail(page, order_number):
    """注文詳細ページ（sales/view）を開く。開けたら True。

    社内システムの操作手順どおり：
      1. /sales?SoHeads[order_number]=<注文番号> で検索
      2. 検索結果に出る「注文番号のリンク」をたどると詳細ページへ
    """
    search_url = f"{BASE_URL}/sales?SoHeads[order_number]={quote(order_number, safe='')}"
    page.goto(search_url, wait_until="networkidle")
    # 検索結果（sales/view リンク）が描画されるまで待つ（取りこぼし・誤リンク防止）
    try:
        page.wait_for_function(
            "(on) => document.body && document.body.innerText.includes(on)",
            arg=order_number, timeout=12000,
        )
    except Exception:
        pass

    # 重要：検索結果の「注文番号が載っているその行(tr)」の中のリンクだけをたどる。
    # ページ内の他の場所（通知欄・最近見た注文など）にある別注文のリンクを拾わないため。
    detail_href = None
    for row in page.query_selector_all("tr"):
        if order_number not in (row.inner_text() or ""):
            continue
        # 行内で、注文番号のテキストを持つリンクを最優先
        for a in row.query_selector_all("a"):
            if order_number in (a.inner_text() or ""):
                href = a.get_attribute("href")
                if href:
                    detail_href = href
                    break
        # なければ、その行内の sales/view リンク
        if not detail_href:
            a = row.query_selector('a[href*="sales/view"]')
            if a:
                detail_href = a.get_attribute("href")
        if detail_href:
            break

    if not detail_href:
        print("  （注意）検索結果の対象行から詳細ページへのリンクが見つかりません")
        return False

    url = detail_href if detail_href.startswith("http") else f"{BASE_URL}{detail_href}"
    page.goto(url, wait_until="networkidle")
    # page.url はドメイン・内部IDを含むためログには出さない
    print("  詳細ページを開きました")
    return True


def _cell_value(cell):
    """セルの値を取り出す。中に入力欄(input/textarea/select)があればその値、
    無ければ表示テキストを返す。"""
    el = cell.query_selector("input, textarea")
    if el:
        try:
            v = el.input_value()
        except Exception:
            v = el.get_attribute("value") or ""
        return (v or "").strip()
    sel = cell.query_selector("select option:checked")
    if sel:
        return sel.inner_text().strip()
    return cell.inner_text().strip()


def _extract_after_label(cell_text, keywords):
    """同じセル内に「ラベル: 値」や「ラベル<改行>値」と入っている場合に、値だけ取り出す。"""
    low = cell_text.lower()
    for kw in keywords:
        idx = low.find(kw)
        if idx == -1:
            continue
        rest = cell_text[idx + len(kw):].lstrip(" :：\t\r\n").strip()
        if "\n" in rest:
            rest = rest.split("\n")[0].strip()
        if rest:
            return rest
    return None


def _tag(cell):
    try:
        return cell.evaluate("el => el.tagName").upper()
    except Exception:
        return ""


def find_value_by_label(page, keywords):
    """keywords を含むラベルに対応する「値」を返す。
    次の3レイアウトに対応：
      - 同じセルに「ラベル: 値」
      - 縦ラベル表（ラベルの隣のセルが値）
      - 横見出し表（ラベルがTH見出しで、値はその下のセル）
    戻り値: (値, 一致したラベル文字列)。見つからなければ (None, None)。"""
    # 1) テーブルを優先処理
    for table in page.query_selector_all("table"):
        rows = table.query_selector_all("tr")
        for r_idx, row in enumerate(rows):
            cells = row.query_selector_all("td, th")
            for i, cell in enumerate(cells):
                t = cell.inner_text().strip()
                low = t.lower()
                if not any(kw in low for kw in keywords):
                    continue
                # 同じセルに「ラベル: 値」
                after = _extract_after_label(t, keywords)
                if after:
                    return after, t
                # 縦ラベル表：隣のセルが値セル(TD)なら採用
                if i + 1 < len(cells) and _tag(cells[i + 1]) == "TD":
                    v = _cell_value(cells[i + 1])
                    if v:
                        return v, t
                # 横見出し表：同じ列・次の行のセルが値
                if r_idx + 1 < len(rows):
                    bcells = rows[r_idx + 1].query_selector_all("td, th")
                    if i < len(bcells):
                        v = _cell_value(bcells[i])
                        if v:
                            return v, t
    # 2) テーブル以外（dl・リスト等）
    for row in page.query_selector_all("dl > div, .form-group, .row, li"):
        cells = row.query_selector_all("dt, dd, td, th, label, span")
        for i, cell in enumerate(cells):
            t = cell.inner_text().strip()
            low = t.lower()
            if not any(kw in low for kw in keywords):
                continue
            after = _extract_after_label(t, keywords)
            if after:
                return after, t
            for c in cells[i + 1:]:
                v = _cell_value(c)
                if v and v.lower() != low:
                    return v, t
    return None, None


def post_draft(url, tracking, name):
    """GAS のミニ・スクリプトに「この内容で下書きを作って」と依頼する。"""
    try:
        r = requests.post(
            url,
            json={"secret": DRAFT_SECRET, "tracking": tracking, "name": name},
            timeout=30,
        )
    except Exception as e:
        return False, str(e)[:60]

    try:
        data = r.json()
    except Exception:
        return False, f"応答が不正(status={r.status_code})"

    if data.get("ok"):
        return True, "ok"
    return False, str(data.get("error", "不明なエラー"))


def set_status(sheet, row_idx, status):
    sheet.update_cell(row_idx, COL_STATUS + 1, status)


def main():
    sheet = get_sheet()
    rows = sheet.get_all_values()

    # 未処理（ステータスが空、または ❌ で始まる再試行対象）を抽出
    pending = []
    for i, row in enumerate(rows[1:], start=2):
        order = row[COL_ORDER].strip() if len(row) > COL_ORDER else ""
        if not order:
            continue
        status = row[COL_STATUS].strip() if len(row) > COL_STATUS else ""
        if status.startswith("✅") and not FORCE_ALL:
            continue
        pending.append({"row": i, "order": order})

    if not pending:
        print("処理対象なし")
        return

    print(f"処理対象: {len(pending)}件")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1800, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        login(page)

        for item in pending:
            row_idx = item["row"]
            order   = item["order"]
            dest_url, dest_label = classify(order)
            print(f"\n--- 注文 {mask(order)}（{dest_label}）---")

            try:
                open_order_detail(page, order)

                # たどり着いたページが本当に対象注文か検証（表示テキスト・入力欄の両方を含むHTMLで確認）
                content = page.content()
                # 注文詳細ページか否かは「Tracking Number / Recipient Name」の有無で判定する。
                # （注文番号は詳細ページに同一書式で表示されないことがあるため一致判定には使わない。
                #   検索→注文番号リンク経由で開いているので、対象注文であることは担保されている）
                if "Tracking Number" not in content and "Recipient Name" not in content:
                    print("  → ❌ 注文詳細ページにたどり着けていない")
                    set_status(sheet, row_idx, "❌ 注文が見つからない")
                    continue

                tracking, t_label = find_value_by_label(page, TRACKING_KEYWORDS)
                name, n_label     = find_value_by_label(page, NAME_KEYWORDS)

                # 取得状況のログ（値はマスク。個人情報はログに出さない）
                print(f"  追跡: ラベル={t_label!r} 値={mask(tracking)}")
                print(f"  氏名: ラベル={n_label!r} 値={mask(name)}")

                if not tracking:
                    set_status(sheet, row_idx, "❌ 追跡番号が取得できない（要確認）")
                    continue

                ok, msg = post_draft(dest_url, tracking, name or "")
                now = datetime.now().strftime("%Y-%m-%d %H:%M")

                if ok:
                    print("  → ✓ 下書き作成OK")
                    sheet.update_cell(row_idx, COL_DEST  + 1, dest_label)
                    sheet.update_cell(row_idx, COL_TRACK + 1, tracking)
                    sheet.update_cell(row_idx, COL_NAME  + 1, name or "")
                    sheet.update_cell(row_idx, COL_STATUS + 1, f"{STATUS_DONE}（{dest_label}）")
                    sheet.update_cell(row_idx, COL_DATE  + 1, now)
                else:
                    print(f"  → ❌ 下書き作成失敗: {msg}")
                    set_status(sheet, row_idx, f"❌ 下書き作成失敗: {msg}")

            except Exception as e:
                # エラーメッセージに注文番号が混ざることがあるためマスク
                err = str(e).replace(order, mask(order))
                print(f"  → ❌ エラー: {err}")
                set_status(sheet, row_idx, f"❌ {str(e)[:60]}")

        browser.close()

    print("\n=== 完了 ===")


if __name__ == "__main__":
    print("=== 転送依頼メール 下書き作成 ===")
    main()
