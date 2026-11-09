// スプレッドシートから料金表と営業日カレンダーを作る

(function () {
  'use strict';

  var CONFIG = window.PICSYS_CONFIG || {};
  var TABS = CONFIG.tabs || {};
  var WEEK = ['日', '月', '火', '水', '木', '金', '土'];

  /* ---------- 読み込み ---------- */

  function sheetUrl(tabName) {
    return 'https://docs.google.com/spreadsheets/d/' + encodeURIComponent(CONFIG.sheetId) +
      '/gviz/tq?tqx=out:csv&headers=1&sheet=' + encodeURIComponent(tabName);
  }

  function fetchText(url) {
    return fetch(url, { cache: 'no-store' }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.text();
    }).then(function (text) {
      // 共有されていないと、CSVではなくログイン画面（HTML）が返ってくる
      if (/^\s*</.test(text)) throw new Error('CSVではありません');
      return text;
    });
  }

  function loadTab(key) {
    var urls = [];
    if (CONFIG.sheetId && TABS[key]) urls.push(sheetUrl(TABS[key]));
    if (CONFIG.fallback && CONFIG.fallback[key]) urls.push(CONFIG.fallback[key]);

    var attempt = function (i) {
      if (i >= urls.length) return Promise.reject(new Error(key + ' を読み込めませんでした'));
      return fetchText(urls[i]).then(function (text) {
        return toObjects(parseCsv(text));
      }).catch(function () { return attempt(i + 1); });
    };
    return attempt(0);
  }

  // CSV を2次元配列に（"…" の中のカンマや改行にも対応）
  function parseCsv(text) {
    var rows = [], row = [], cell = '', inQuotes = false;
    text = text.replace(/^﻿/, '');
    for (var i = 0; i < text.length; i++) {
      var c = text[i];
      if (inQuotes) {
        if (c === '"') {
          if (text[i + 1] === '"') { cell += '"'; i++; }
          else inQuotes = false;
        } else cell += c;
      } else if (c === '"') inQuotes = true;
      else if (c === ',') { row.push(cell); cell = ''; }
      else if (c === '\n' || c === '\r') {
        if (c === '\r' && text[i + 1] === '\n') i++;
        row.push(cell); rows.push(row); row = []; cell = '';
      } else cell += c;
    }
    if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
    return rows;
  }

  // 1行目の見出しをキーにしたオブジェクトの配列に
  function toObjects(rows) {
    if (!rows.length) return [];
    var head = rows[0].map(function (h) { return h.trim(); });
    return rows.slice(1).map(function (r) {
      var o = {};
      head.forEach(function (h, i) { o[h] = (r[i] || '').trim(); });
      return o;
    }).filter(function (o) {
      return Object.keys(o).some(function (k) { return o[k] !== ''; });
    });
  }

  /* ---------- 小さな道具 ---------- */

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  // 全角の数字や記号を半角に
  function half(s) {
    return String(s || '').replace(/[０-９：／－]/g, function (c) {
      return String.fromCharCode(c.charCodeAt(0) - 0xFEE0);
    });
  }

  // "10:00" "10時" "9：30" → "10:00" / "9:30"
  function parseTime(s) {
    s = half(s).trim();
    var m = s.match(/^(\d{1,2})(?:[:時](\d{1,2}))?/);
    if (!m) return '';
    var h = +m[1], min = m[2] ? +m[2] : 0;
    if (h > 29 || min > 59) return '';
    return h + ':' + (min < 10 ? '0' : '') + min;
  }

  function minutes(t) {
    var p = t.split(':');
    return (+p[0]) * 60 + (+p[1]);
  }

  // いまの日本時間
  function tokyoNow() {
    var parts = {};
    try {
      new Intl.DateTimeFormat('en-US', {
        timeZone: 'Asia/Tokyo', year: 'numeric', month: 'numeric', day: 'numeric',
        hour: 'numeric', minute: 'numeric', hour12: false
      }).formatToParts(new Date()).forEach(function (p) { parts[p.type] = p.value; });
    } catch (e) {
      var d = new Date();
      parts = { year: d.getFullYear(), month: d.getMonth() + 1, day: d.getDate(), hour: d.getHours(), minute: d.getMinutes() };
    }
    return {
      date: new Date(+parts.year, +parts.month - 1, +parts.day),
      minutes: (+parts.hour % 24) * 60 + (+parts.minute)
    };
  }

  // "2026/12/31" "2026-12-31" "2026年12月31日" "12/31" → Date
  function parseDate(s, today) {
    s = half(s).trim();
    // 表示形式がはずれて日付が数字（シリアル値）で届いたとき
    if (/^\d{5}(\.\d+)?$/.test(s)) {
      var base = new Date(1899, 11, 30);
      return addDays(base, Math.floor(+s));
    }
    var m = s.match(/^(\d{4})[\/\-.年](\d{1,2})[\/\-.月](\d{1,2})/);
    if (m) return new Date(+m[1], +m[2] - 1, +m[3]);
    m = s.match(/^(\d{1,2})[\/\-.月](\d{1,2})/);
    if (m) {
      var d = new Date(today.getFullYear(), +m[1] - 1, +m[2]);
      // 年が書いていなくて2か月以上前なら、来年のこととみなす
      if (d < addDays(today, -60)) d.setFullYear(d.getFullYear() + 1);
      return d;
    }
    return null;
  }

  function addDays(d, n) {
    return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  }

  function sameDay(a, b) {
    return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }

  function md(d) {
    return (d.getMonth() + 1) + '/' + d.getDate() + '（' + WEEK[d.getDay()] + '）';
  }

  // 表示用の時刻（26:00 → 翌2:00）
  function clock(t) {
    if (!t) return '';
    var p = t.split(':'), h = +p[0];
    return h >= 24 ? '翌' + (h - 24) + ':' + p[1] : t;
  }

  function range(open, close) {
    if (open && close) return clock(open) + '〜' + clock(close);
    if (open) return clock(open) + '〜';
    if (close) return '〜' + clock(close);
    return '';
  }

  /* ---------- 料金表 ---------- */

  function renderPrices(rows) {
    var boxes = document.querySelectorAll('[data-price-tab]');
    Array.prototype.forEach.call(boxes, function (box) {
      var tab = box.getAttribute('data-price-tab');
      var list = rows.filter(function (r) {
        return r['タブ'] === tab && r['メニュー'] && r['表示'] !== '隠す';
      });

      box.innerHTML = '';
      if (!list.length) {
        box.appendChild(el('p', 'menu-empty', 'メニューは準備中です。お気軽にお問い合わせください。'));
        return;
      }

      // 「見出し」ごとにまとめる（並びはスプレッドシートの順）
      var groups = [];
      list.forEach(function (r) {
        var name = r['見出し'] || 'メニュー';
        var g = groups.filter(function (x) { return x.name === name; })[0];
        if (!g) { g = { name: name, items: [] }; groups.push(g); }
        g.items.push(r);
      });

      groups.forEach(function (g) {
        var wrap = el('div', 'menu-group');
        wrap.appendChild(el('h3', 'menu-title', g.name));
        var ul = el('ul', 'menu-list');
        g.items.forEach(function (r) {
          var li = el('li');
          li.appendChild(el('span', null, r['メニュー']));
          var price = r['料金'];
          if (/^\d+$/.test(half(price).replace(/,/g, ''))) {
            price = Number(half(price).replace(/,/g, '')).toLocaleString('ja-JP') + '円';
          }
          var b = el('b', null, price || 'お問い合わせください');
          if (r['補足']) b.appendChild(el('small', null, r['補足']));
          li.appendChild(b);
          ul.appendChild(li);
        });
        wrap.appendChild(ul);
        box.appendChild(wrap);
      });
    });
  }

  function priceError() {
    var boxes = document.querySelectorAll('[data-price-tab]');
    Array.prototype.forEach.call(boxes, function (box) {
      box.innerHTML = '';
      box.appendChild(el('p', 'menu-empty', '料金表を読み込めませんでした。お手数ですが、お電話でお問い合わせください。'));
    });
  }

  /* ---------- 営業予定（日付・期間ごと） ---------- */

  // 「時間パターン」タブと「営業予定」タブから、日ごとの営業時間を引けるようにする
  function buildSchedule(rows, patternRows, today) {
    var patterns = {};
    patternRows.forEach(function (r) {
      var name = (r['名前'] || '').trim();
      if (!name) return;
      patterns[name] = { open: parseTime(r['開店']), close: parseTime(r['閉店']) };
    });

    var entries = [];
    rows.forEach(function (r, i) {
      var start = parseDate(r['日付'], today);
      if (!start) return;
      var end = parseDate(r['終了日'], today) || start;
      if (end < start) { var t = start; start = end; end = t; }

      var kind = (r['営業'] || '').trim();
      var open = parseTime(r['開店']);
      var close = parseTime(r['閉店']);
      var note = r['ひとこと'] || '';
      var info;
      if (/休/.test(kind)) {
        info = { type: 'closed', open: '', close: '', label: 'お休み' };
      } else if (kind || open || close) {
        var p = patterns[kind] || { open: '', close: '' };
        info = { type: 'open', open: open || p.open, close: close || p.close, label: kind };
      } else if (note) {
        info = { type: 'unknown', open: '', close: '', label: '' };
      } else {
        return;
      }
      info.note = note;
      entries.push({ start: start, end: end, span: Math.round((end - start) / 864e5), row: i, info: info });
    });

    // 1日だけの指定は期間の指定より優先。同じ長さなら下の行が優先
    function entryFor(date) {
      var best = null;
      entries.forEach(function (e) {
        if (date < e.start || date > e.end) return;
        if (!best || e.span < best.span || (e.span === best.span && e.row > best.row)) best = e;
      });
      return best;
    }

    function dayInfo(date) {
      var e = entryFor(date);
      return e ? e.info : { type: 'unknown', open: '', close: '', label: '', note: '' };
    }

    return { entries: entries, dayInfo: dayInfo };
  }

  function hoursText(info) {
    if (info.type === 'closed') return 'お休み';
    if (info.type === 'unknown') return '未定';
    return range(info.open, info.close) || '営業';
  }

  // カレンダーのマス用の短い時間（11:00〜19:00 → 11-19、20:00〜26:00 → 20-翌2）
  function shortRange(info) {
    var s = function (t) {
      if (!t) return '';
      var p = t.split(':'), h = +p[0];
      var txt = (h >= 24 ? h - 24 : h) + (p[1] === '00' ? '' : ':' + p[1]);
      return (h >= 24 ? '翌' : '') + txt;
    };
    if (!info.open && !info.close) return '営業';
    return s(info.open) + '-' + s(info.close);
  }

  // この先1週間の営業
  function renderWeekAhead(schedule, today) {
    var list = document.getElementById('week-ahead');
    if (!list) return;
    list.innerHTML = '';
    for (var i = 0; i < 7; i++) {
      var d = addDays(today, i), info = schedule.dayInfo(d);
      var row = el('div', 'is-' + info.type + (i === 0 ? ' is-today' : ''));
      row.appendChild(el('dt', null, i === 0 ? '今日 ' + md(d) : md(d)));
      var dd = el('dd', null, hoursText(info));
      if (info.note) dd.appendChild(el('small', null, info.note));
      row.appendChild(dd);
      list.appendChild(row);
    }
  }

  // 「ひとこと」が入っている予定をお知らせに（期間はまとめて1行）
  function renderNotices(schedule, today) {
    var ul = document.getElementById('notice-list');
    if (!ul) return;
    ul.innerHTML = '';
    var list = schedule.entries.filter(function (e) { return e.info.note && e.end >= today; })
      .sort(function (a, b) { return a.start - b.start || a.row - b.row; })
      .slice(0, 6);
    if (!list.length) {
      ul.appendChild(el('li', 'notice-none', '今のところ、お知らせはありません。'));
      return;
    }
    list.forEach(function (e) {
      var li = el('li', 'notice-' + e.info.type);
      li.appendChild(el('span', 'notice-date', sameDay(e.start, e.end) ? md(e.start) : md(e.start) + '〜' + md(e.end)));
      li.appendChild(el('span', 'notice-what', hoursText(e.info)));
      li.appendChild(el('span', 'notice-note', e.info.note));
      ul.appendChild(li);
    });
  }

  // アクセス欄の「営業時間」
  function renderAccess(schedule, today) {
    var box = document.querySelector('[data-hours-today]');
    if (!box) return;
    box.textContent = '本日 ' + hoursText(schedule.dayInfo(today));
  }

  function renderToday(schedule, now) {
    var box = document.getElementById('today-status');
    if (!box) return;
    var info = schedule.dayInfo(now.date);
    var prev = schedule.dayInfo(addDays(now.date, -1));
    var t = now.minutes;
    var text, state, sub = '';

    var nextOpen = function () {
      for (var i = 1; i <= 21; i++) {
        var d = addDays(now.date, i), di = schedule.dayInfo(d);
        if (di.type === 'open') return '次の営業は ' + md(d) + (di.open ? ' ' + clock(di.open) + '〜' : '');
      }
      return '';
    };

    if (prev.type === 'open' && prev.close && minutes(prev.close) > 1440 && t < minutes(prev.close) - 1440) {
      // 前の日の夜の営業が、日付をまたいで続いているとき
      text = 'ただいま営業中（' + clock(prev.close).replace('翌', '') + ' まで）'; state = 'open';
    } else if (info.type === 'closed') {
      text = '本日はお休みです'; state = 'closed'; sub = nextOpen();
    } else if (info.type === 'unknown') {
      box.hidden = true; return;
    } else if (info.open && info.close) {
      if (t < minutes(info.open)) { text = '本日は ' + range(info.open, info.close) + ' 営業'; state = 'before'; }
      else if (t < minutes(info.close)) { text = 'ただいま営業中（' + clock(info.close) + ' まで）'; state = 'open'; }
      else { text = '本日の営業は終了しました'; state = 'after'; sub = nextOpen(); }
    } else {
      text = '本日は営業日です'; state = 'open';
    }

    box.textContent = '';
    box.appendChild(el('span', 'today-dot'));
    var body = el('span', 'today-text', text);
    if (sub) body.appendChild(el('small', null, sub));
    box.appendChild(body);
    box.setAttribute('data-state', state);
    box.hidden = false;
  }

  /* ---------- カレンダー ---------- */

  function setupCalendar(schedule, today) {
    var grid = document.getElementById('cal-grid');
    var title = document.getElementById('cal-title');
    var detail = document.getElementById('cal-detail');
    var prev = document.querySelector('[data-cal-prev]');
    var next = document.querySelector('[data-cal-next]');
    if (!grid || !title) return;

    var first = new Date(today.getFullYear(), today.getMonth(), 1);
    var maxAhead = CONFIG.calendarMonthsAhead || 3;
    var offset = 0;
    var selected = today;

    function showDetail(date) {
      if (!detail) return;
      var info = schedule.dayInfo(date);
      detail.textContent = '';
      detail.appendChild(el('b', null, (date.getMonth() + 1) + '月' + date.getDate() + '日（' + WEEK[date.getDay()] + '）'));
      var txt = info.type === 'unknown' ? '未定（お問い合わせください）' : hoursText(info);
      detail.appendChild(document.createTextNode('　' + txt));
      if (info.note) detail.appendChild(el('span', 'cal-detail-note', info.note));
      detail.setAttribute('data-type', info.type);
    }

    function draw() {
      var month = new Date(first.getFullYear(), first.getMonth() + offset, 1);
      title.textContent = month.getFullYear() + '年' + (month.getMonth() + 1) + '月';
      if (prev) prev.disabled = offset <= 0;
      if (next) next.disabled = offset >= maxAhead;

      grid.innerHTML = '';
      WEEK.forEach(function (w, i) {
        grid.appendChild(el('span', 'cal-week' + (i === 0 ? ' is-sun' : i === 6 ? ' is-sat' : ''), w));
      });
      for (var b = 0; b < month.getDay(); b++) grid.appendChild(el('span', 'cal-blank'));

      var count = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
      for (var n = 1; n <= count; n++) {
        (function (date) {
          var info = schedule.dayInfo(date);
          var btn = el('button', 'cal-day is-' + info.type);
          btn.type = 'button';
          if (date < today) btn.classList.add('is-past');
          if (sameDay(date, today)) btn.classList.add('is-today');
          if (sameDay(date, selected)) btn.classList.add('is-selected');
          if (info.note) btn.classList.add('has-note');
          btn.appendChild(el('span', 'cal-num', String(date.getDate())));
          var mark = info.type === 'closed' ? '休' : info.type === 'open' ? shortRange(info) : '';
          btn.appendChild(el('span', 'cal-mark', mark));
          btn.setAttribute('aria-label', (date.getMonth() + 1) + '月' + date.getDate() + '日 ' + hoursText(info));
          btn.addEventListener('click', function () {
            selected = date;
            Array.prototype.forEach.call(grid.querySelectorAll('.is-selected'), function (x) { x.classList.remove('is-selected'); });
            btn.classList.add('is-selected');
            showDetail(date);
          });
          grid.appendChild(btn);
        })(new Date(month.getFullYear(), month.getMonth(), n));
      }
    }

    if (prev) prev.addEventListener('click', function () { if (offset > 0) { offset--; draw(); } });
    if (next) next.addEventListener('click', function () { if (offset < maxAhead) { offset++; draw(); } });

    draw();
    showDetail(today);
  }

  function scheduleError() {
    var grid = document.getElementById('cal-grid');
    if (grid) {
      grid.innerHTML = '';
      grid.appendChild(el('p', 'cal-error', '営業日を読み込めませんでした。お手数ですが、お電話でご確認ください。'));
    }
    var box = document.querySelector('[data-hours-today]');
    if (box) box.textContent = 'お電話でご確認ください';
  }

  /* ---------- はじめる ---------- */

  loadTab('price').then(renderPrices).catch(priceError);

  Promise.all([loadTab('schedule'), loadTab('patterns').catch(function () { return []; })])
    .then(function (res) {
      var now = tokyoNow();
      var schedule = buildSchedule(res[0], res[1], now.date);
      renderWeekAhead(schedule, now.date);
      renderNotices(schedule, now.date);
      renderAccess(schedule, now.date);
      renderToday(schedule, now);
      setupCalendar(schedule, now.date);
    })
    .catch(scheduleError);
})();
