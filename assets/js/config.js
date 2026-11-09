// ホームページの設定
// スプレッドシートを作り直したときは、sheetId だけ書きかえてください。

window.PICSYS_CONFIG = {
  // Googleスプレッドシートの ID（URLの「/d/」と「/edit」の間の文字）
  // 「PiCsys ホームページ管理表（営業予定）」
  sheetId: "176fW7-hwGbIndP-CJU_c-XUltv1HxphIo0WYaVTNwiM",

  // スプレッドシートのタブの名前（スプレッドシート側と同じにする）
  tabs: {
    price: "料金",
    schedule: "営業予定",
    patterns: "時間パターン"
  },

  // スプレッドシートが読めないときに使う控えのデータ
  fallback: {
    price: "data/prices.csv",
    schedule: "data/schedule.csv",
    patterns: "data/patterns.csv"
  },

  // カレンダーで何か月先まで見られるか
  calendarMonthsAhead: 3
};
