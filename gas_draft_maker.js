// ============================================================
// 【ミニ・スクリプト】配送停止（転送依頼）メールの下書きを、
// このスクリプトを置いた Gmail アカウントの中に作成する。
//
// ★ 楽天用Gmail と その他用Gmail の「2つのアカウント」それぞれに、
//    このコードを貼り付けて、別々にデプロイする。
//    （配送会社のアドレス・文面はここに書くので GitHub には載らない＝公開されない）
//
// 【設置手順（各アカウントで1回ずつ）】
// 1. そのGmailアカウントでログインした状態で https://script.google.com を開く
// 2. 「新しいプロジェクト」→ このコードを全部貼り付け
// 3. 下の DRAFT_SECRET を、GitHub の Secret「DRAFT_SECRET」と同じ文字列にする
//    あわせて MAIL_TO / MAIL_CC / MAIL_GREETING に実際の値を入れる（公開リポジトリには載せない）
// 4. 関数 authorize を1回手動実行 → Gmailへのアクセスを「許可」する
// 5. 右上「デプロイ」→「新しいデプロイ」→ 種類「ウェブアプリ」
//      - 次のユーザーとして実行: 自分
//      - アクセスできるユーザー: 全員
// 6. 発行された「ウェブアプリのURL」を控える
//      → 楽天用は GitHub Secret「RAKUTEN_DRAFT_URL」、
//        その他用は「OTHER_DRAFT_URL」に登録する
// ※ コードを直したら「デプロイを管理」→ 鉛筆 →「バージョン: 新バージョン」で更新
// ============================================================

// 合言葉（GitHub 側の DRAFT_SECRET と必ず同じ文字列にする）
var DRAFT_SECRET = "ここに合言葉を入れる";

// 配送会社あての宛先・宛名（楽天用・その他用とも同じでOK）
// ★GASに貼り付けたあと、ここに実際の値を入れる（公開リポジトリには載せない）
var MAIL_TO   = "（配送会社のTOアドレスをここに入れる）";
var MAIL_CC   = "（配送会社のCCアドレスをここに入れる）";
var MAIL_GREETING = "（宛名・担当者名をここに入れる）";  // 例：「○○」を入れると本文冒頭が「○○ 様」になる

function buildSubject(tracking) {
  return "転送依頼（" + tracking + "）";
}

function trackingUrl(tracking) {
  return "https://tracking.sagawa-sgx.com/sgx/trackeng.asp?CAT=awb&AWB=" + tracking;
}

// プレーンテキスト版（HTML非対応メーラー用のフォールバック）
function buildBody(tracking, name) {
  return [
    MAIL_GREETING + " 様",
    "",
    "いつも大変お世話になっております。",
    "下記の貨物につきまして、弊社日本事務所への転送をお願いできますでしょうか。",
    "",
    tracking + "    " + name + " 様",
    trackingUrl(tracking),
    "",
    "転送費用が発生する場合は当店負担で結構です。",
    "",
    "よろしくお願いいたします。"
  ].join("\n");
}

// HTML版（追跡URLをクリックできるリンクにする）
function buildHtmlBody(tracking, name) {
  var url = trackingUrl(tracking);
  var urlAttr = url.replace(/&/g, "&amp;");  // href属性用に&をエスケープ
  return [
    MAIL_GREETING + " 様",
    "",
    "いつも大変お世話になっております。",
    "下記の貨物につきまして、弊社日本事務所への転送をお願いできますでしょうか。",
    "",
    tracking + "&nbsp;&nbsp;&nbsp;&nbsp;" + name + " 様",
    '<a href="' + urlAttr + '">' + url + "</a>",
    "",
    "転送費用が発生する場合は当店負担で結構です。",
    "",
    "よろしくお願いいたします。"
  ].join("<br>\n");
}

// GitHub の Python から呼ばれる入口
function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);

    if (!DRAFT_SECRET || body.secret !== DRAFT_SECRET) {
      return jsonOutput({ ok: false, error: "認証エラー" });
    }

    var tracking = (body.tracking || "").toString().trim();
    var name     = (body.name || "").toString().trim();

    if (!tracking) {
      return jsonOutput({ ok: false, error: "追跡番号が空です" });
    }

    GmailApp.createDraft(
      MAIL_TO,
      buildSubject(tracking),
      buildBody(tracking, name),
      { cc: MAIL_CC, htmlBody: buildHtmlBody(tracking, name) }
    );

    return jsonOutput({ ok: true, status: "draft_created" });
  } catch (err) {
    return jsonOutput({ ok: false, error: String(err) });
  }
}

// 動作確認用（ブラウザでURLを開くと表示される）
function doGet(e) {
  return jsonOutput({ ok: true, message: "転送依頼 下書き作成用Webアプリは稼働中です" });
}

// 【最初に1回だけ手動実行】Gmailへのアクセス許可を出すための関数
function authorize() {
  var drafts = GmailApp.getDrafts();
  Logger.log("認証OK: 既存の下書き " + drafts.length + " 件");
}

function jsonOutput(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
