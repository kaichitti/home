// スプレッドシートから料金表と営業日カレンダーを作る

(function () {
  'use strict';

  var CONFIG = window.PICSYS_CONFIG || {};
  var TABS = CONFIG.tabs || {};
  var WEEK = ['日', '月', '火', '水', '木', '金', '土'];
  var WEEK_ORDER = [1, 2, 3, 4, 5, 6, 0]; // 月曜はじまりで並べるとき

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

  function range(open, close) {
    if (open && close) return open + '〜' + close;
    if (open) return open + '〜';
    if (close) return '〜' + close;
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

  /* ---------- 営業日 ---------- */

  function buildSchedule(hourRows, specialRows, today) {
    var weekly = {};
    hourRows.forEach(function (r) {
      var day = WEEK.indexOf((r['曜日'] || '').charAt(0));
      if (day < 0) return;
      var closed = /休/.test(r['営業']);
      weekly[day] = {
        type: closed ? 'closed' : 'open',
        open: closed ? '' : parseTime(r['開店']),
        close: closed ? '' : parseTime(r['閉店']),
        note: r['ひとこと'] || ''
      };
    });

    var specials = [];
    specialRows.forEach(function (r) {
      var start = parseDate(r['日付'], today);
      if (!start) return;
      var end = parseDate(r['終了日'], today) || start;
      if (end < start) { var t = start; start = end; end = t; }
      var kind = r['種類'] || '休み';
      specials.push({
        start: start, end: end,
        type: /休/.test(kind) ? 'closed' : (/臨時/.test(kind) ? 'extra' : 'changed'),
        label: kind,
        open: parseTime(r['開店']),
        close: parseTime(r['閉店']),
        note: r['ひとこと'] || ''
      });
    });

    function dayInfo(date) {
      var base = weekly[date.getDay()] || { type: 'unknown', open: '', close: '', note: '' };
      var info = { type: base.type, open: base.open, close: base.close, note: base.note, special: null };
      specials.forEach(function (s) {
        if (date >= s.start && date <= s.end) {
          info.special = s;
          info.type = s.type;
          info.note = s.note;
          if (s.type === 'closed') { info.open = ''; info.close = ''; }
          else {
            info.open = s.open || base.open;
            info.close = s.close || base.close;
          }
        }
      });
      return info;
    }

    return { weekly: weekly, specials: specials, dayInfo: dayInfo };
  }

  // 「月〜土 10:00〜19:00」のように同じ時間の曜日をまとめる
  function weeklyGroups(weekly) {
    var groups = [];
    WEEK_ORDER.forEach(function (d) {
      var w = weekly[d];
      if (!w) return;
      var key = w.type + '|' + w.open + '|' + w.close + '|' + w.note;
      var last = groups[groups.length - 1];
      if (last && last.key === key && last.days[last.days.length - 1] === WEEK_ORDER[WEEK_ORDER.indexOf(d) - 1]) {
        last.days.push(d);
      } else {
        groups.push({ key: key, days: [d], info: w });
      }
    });
    return groups.map(function (g) {
      var label = g.days.length > 2
        ? WEEK[g.days[0]] + '〜' + WEEK[g.days[g.days.length - 1]]
        : g.days.map(function (d) { return WEEK[d]; }).join('・');
      return { label: label, info: g.info };
    });
  }

  function hoursText(info) {
    if (info.type === 'closed') return 'お休み';
    if (info.type === 'unknown') return '—';
    return range(info.open, info.close) || '営業';
  }

  function renderWeekly(schedule) {
    var groups = weeklyGroups(schedule.weekly);

    var dl = document.getElementById('week-hours');
    if (dl) {
      dl.innerHTML = '';
      groups.forEach(function (g) {
        var row = el('div', g.info.type === 'closed' ? 'is-closed' : '');
        row.appendChild(el('dt', null, g.label));
        var dd = el('dd', null, hoursText(g.info));
        if (g.info.note) dd.appendChild(el('small', null, g.info.note));
        row.appendChild(dd);
        dl.appendChild(row);
      });
    }

    var inline = document.querySelector('[data-week-hours-inline]');
    if (inline) {
      inline.innerHTML = '';
      groups.filter(function (g) { return g.info.type !== 'closed'; }).forEach(function (g) {
        inline.appendChild(el('span', 'hours-line', g.label + '　' + hoursText(g.info)));
      });
      if (!inline.childNodes.length) inline.textContent = 'カレンダーをご覧ください';
    }

    var closedBox = document.querySelector('[data-closed-days]');
    if (closedBox) {
      var closed = WEEK_ORDER.filter(function (d) {
        return schedule.weekly[d] && schedule.weekly[d].type === 'closed';
      }).map(function (d) { return WEEK[d] + '曜日'; });
      closedBox.textContent = (closed.length ? closed.join('・') : 'なし') + '（臨時のお休みはカレンダーでお知らせします）';
    }
  }

  function renderNotices(schedule, today) {
    var ul = document.getElementById('notice-list');
    if (!ul) return;
    var upcoming = schedule.specials.filter(function (s) { return s.end >= today; })
      .sort(function (a, b) { return a.start - b.start; })
      .slice(0, 6);

    ul.innerHTML = '';
    if (!upcoming.length) {
      ul.appendChild(el('li', 'notice-none', '今のところ、臨時のお休みや時間の変更はありません。'));
      return;
    }
    upcoming.forEach(function (s) {
      var li = el('li', 'notice-' + s.type);
      var when = sameDay(s.start, s.end) ? md(s.start) : md(s.start) + '〜' + md(s.end);
      li.appendChild(el('span', 'notice-date', when));
      var what = s.type === 'closed' ? 'お休み' : s.label + '　' + range(s.open, s.close);
      li.appendChild(el('span', 'notice-what', what));
      if (s.note) li.appendChild(el('span', 'notice-note', s.note));
      ul.appendChild(li);
    });
  }

  function renderToday(schedule, now) {
    var box = document.getElementById('today-status');
    if (!box) return;
    var info = schedule.dayInfo(now.date);
    var text, state, sub = '';

    if (info.type === 'closed') {
      text = '本日はお休みです'; state = 'closed';
      // 次に開く日
      for (var i = 1; i <= 14; i++) {
        var d = addDays(now.date, i), di = schedule.dayInfo(d);
        if (di.type !== 'closed' && di.type !== 'unknown') {
          sub = '次の営業は ' + md(d) + (di.open ? ' ' + di.open + '〜' : '');
          break;
        }
      }
    } else if (info.type === 'unknown') {
      box.hidden = true; return;
    } else if (info.open && info.close) {
      var t = now.minutes;
      if (t < minutes(info.open)) { text = '本日は ' + info.open + ' から営業します'; state = 'before'; }
      else if (t < minutes(info.close)) { text = 'ただいま営業中（' + info.close + ' まで）'; state = 'open'; }
      else {
        text = '本日の営業は終了しました'; state = 'after';
        var tomorrow = schedule.dayInfo(addDays(now.date, 1));
        if (tomorrow.type !== 'closed' && tomorrow.type !== 'unknown' && tomorrow.open) sub = '明日は ' + tomorrow.open + ' から営業します';
      }
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
      var txt;
      if (info.type === 'closed') txt = 'お休み';
      else if (info.type === 'unknown') txt = 'お問い合わせください';
      else txt = (info.special ? info.special.label + '　' : '') + (range(info.open, info.close) || '営業');
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

      var days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
      for (var n = 1; n <= days; n++) {
        (function (date) {
          var info = schedule.dayInfo(date);
          var btn = el('button', 'cal-day is-' + info.type);
          btn.type = 'button';
          if (date < today) btn.classList.add('is-past');
          if (sameDay(date, today)) btn.classList.add('is-today');
          if (sameDay(date, selected)) btn.classList.add('is-selected');
          btn.appendChild(el('span', 'cal-num', String(date.getDate())));
          var mark = info.type === 'closed' ? '休' : (info.type === 'changed' || info.type === 'extra') ? (info.close ? '〜' + info.close.replace(':00', '') : '変更') : '';
          btn.appendChild(el('span', 'cal-mark', mark));
          btn.setAttribute('aria-label', (date.getMonth() + 1) + '月' + date.getDate() + '日 ' +
            (info.type === 'closed' ? 'お休み' : hoursText(info)));
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
    var inline = document.querySelector('[data-week-hours-inline]');
    if (inline) inline.textContent = 'お電話でご確認ください';
  }

  /* ---------- はじめる ---------- */

  loadTab('price').then(renderPrices).catch(priceError);

  Promise.all([loadTab('hours'), loadTab('special').catch(function () { return []; })])
    .then(function (res) {
      var now = tokyoNow();
      var schedule = buildSchedule(res[0], res[1], now.date);
      renderWeekly(schedule);
      renderNotices(schedule, now.date);
      renderToday(schedule, now);
      setupCalendar(schedule, now.date);
    })
    .catch(scheduleError);
})();
