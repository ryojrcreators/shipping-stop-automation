// ============================================================
// 【シート側スクリプト】スプレッドシートのメニュー／ボタンに割り当てる。
// 押すと GitHub Actions（stop_request.yml）を起動する。
//
// ★ これは「注文番号を貼り付けるスプレッドシート」に紐づけて使う。
//   （rakuten-review-automation の gas_coupon.js と同じ作り）
//
// 【設定手順】
// 1. 注文番号を貼り付けるスプレッドシートを開く
// 2. 拡張機能 → Apps Script を開く
// 3. このコードを貼り付ける
// 4. 下の GITHUB_OWNER を自分の GitHub ユーザー名に変更する
// 5. プロジェクトの設定 → スクリプトプロパティに GITHUB_TOKEN を登録する
//    （Fine-grained token / 対象リポジトリの Actions: Read and write 権限）
// 6. スプレッドシートを再読み込みすると、上部に「📦 転送依頼」メニューが出る
//    （図形描画でボタンを作り、createStopDrafts を割り当ててもよい）
// ============================================================

var GITHUB_OWNER  = "ryojrcreators";   // ← あなたのGitHubアカウント
var GITHUB_REPO   = "shipping-stop-automation";    // ← リポジトリ名（変えていなければこのまま）
var WORKFLOW_FILE = "stop_request.yml";

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("📦 転送依頼")
    .addItem("転送依頼の下書きを作成", "createStopDrafts")
    .addToUi();
}

function createStopDrafts() {
  var ui = SpreadsheetApp.getUi();

  var token = PropertiesService.getScriptProperties().getProperty("GITHUB_TOKEN");
  if (!token) {
    ui.alert("GITHUB_TOKENが設定されていません。\nApps Script → プロジェクトの設定 → スクリプトプロパティで設定してください。");
    return;
  }

  var result = ui.alert(
    "確認",
    "未処理の注文について、転送依頼メールの下書きを作成しますか？\n（完了まで数分かかります）",
    ui.ButtonSet.YES_NO
  );
  if (result !== ui.Button.YES) return;

  var url = "https://api.github.com/repos/" + GITHUB_OWNER + "/" + GITHUB_REPO +
            "/actions/workflows/" + WORKFLOW_FILE + "/dispatches";

  var response = UrlFetchApp.fetch(url, {
    method: "POST",
    headers: {
      "Authorization": "Bearer " + token,
      "Accept": "application/vnd.github.v3+json",
      "Content-Type": "application/json"
    },
    payload: JSON.stringify({ ref: "main" }),
    muteHttpExceptions: true
  });

  if (response.getResponseCode() === 204) {
    ui.alert("下書き作成を開始しました！\n数分後にGmailの下書きと、このシートのステータス欄を確認してください。");
  } else {
    ui.alert("エラーが発生しました。\nコード: " + response.getResponseCode() + "\n" + response.getContentText());
  }
}
