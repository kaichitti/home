// ホームページの設定
// スプレッドシートを作り直したときは、sheetId だけ書きかえてください。

window.PICSYS_CONFIG = {
  // Googleスプレッドシートの ID（URLの「/d/」と「/edit」の間の文字）
  // 「PiCsys ホームページ管理表」
  sheetId: "1_tFgkhR2Ji7QfavvWUrngClReZophB8ZK7iRgy-YXOo",

  // スプレッドシートのタブの名前（スプレッドシート側と同じにする）
  tabs: {
    price: "料金",
    hours: "営業時間",
    special: "お休み・時間変更"
  },

  // スプレッドシートが読めないときに使う控えのデータ
  fallback: {
    price: "data/prices.csv",
    hours: "data/hours.csv",
    special: "data/special-days.csv"
  },

  // カレンダーで何か月先まで見られるか
  calendarMonthsAhead: 3
};
