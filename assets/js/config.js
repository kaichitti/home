// ホームページの設定
// スプレッドシートを作り直したときは、sheetId だけ書きかえてください。

window.PICSYS_CONFIG = {
  // Googleスプレッドシートの ID（URLの「/d/」と「/edit」の間の文字）
  // 「PiCsys ホームページ管理表（日付ごと）」
  sheetId: "1peK8EUJIxmUFhEwhXOke_twD9QMolYKZg6bC8Y7wl58",

  // スプレッドシートのタブの名前（スプレッドシート側と同じにする）
  tabs: {
    price: "料金",
    days: "営業日",
    patterns: "時間パターン"
  },

  // スプレッドシートが読めないときに使う控えのデータ
  fallback: {
    price: "data/prices.csv",
    days: "data/days.csv",
    patterns: "data/patterns.csv"
  },

  // カレンダーで何か月先まで見られるか
  calendarMonthsAhead: 3
};
