'use strict';

// ぷらチャット - 旧式携帯・CGIチャットスタイルのルーム型チャット
// クライアントJSはポップアップ用の window.open のみ(無くても動作)。
// フォーム送信とページ更新だけで動くため、iOS4 / Android 1.6 / 3DS
// などの古いブラウザでも動作する。

const crypto = require('crypto');
const dns = require('dns');
const fs = require('fs');
const path = require('path');
const express = require('express');

const app = express();
app.set('trust proxy', true);
app.use(express.urlencoded({ extended: false }));

const PORT = process.env.PORT || 3000;
const SITE_NAME = 'ぷらチャット';

// ---- 定数 ---------------------------------------------------------------

const MAX_NAME_LENGTH = 20;
const MAX_MESSAGE_LENGTH = 500;
const MAX_ROOM_NAME_LENGTH = 30;
const MAX_ROOM_DESC_LENGTH = 200;
const MAX_PASS_LENGTH = 30;
const MAX_LOG_PER_ROOM = 100;
const MAX_LOG_PER_PM = 100;
const MAX_ROOMS = 200;
const MAX_JOINED_ROOMS = 5;               // 同時に入室できる部屋数
const MIN_CAPACITY = 2;
const MAX_CAPACITY = 50;
const IDLE_TIMEOUT_MS = 10 * 60 * 1000;   // 操作がないとこの時間で自動退室
const SESSION_TTL_MS = 60 * 60 * 1000;    // 退室後セッションを保持する時間

const INFO_FILE = path.join(__dirname, 'information.txt');
const CONTACT_LOG = path.join(__dirname, 'contact.log');

// サイコロコマンド: 「2d6」「1d100+3」のような発言でダイスを振る
const DICE_PATTERN = /^(\d{1,2})[dD](\d{1,4})([+-]\d{1,4})?$/;

// 画像URL(画像投稿ONの部屋でインライン表示)
const IMAGE_URL_PATTERN = /^https?:\/\/[^\s"<>]+\.(jpe?g|gif|png)$/i;

// 名前の色プリセット16色（キー, 表示名, 色コード）
const COLORS = [
  ['black',    '黒',     '#222222'],
  ['red',      '赤',     '#cc0000'],
  ['blue',     '青',     '#0000cc'],
  ['green',    '緑',     '#007700'],
  ['orange',   '橙',     '#cc6600'],
  ['purple',   '紫',     '#770077'],
  ['brown',    '茶',     '#774411'],
  ['pink',     '桃',     '#cc0077'],
  ['teal',     '青緑',   '#007777'],
  ['gray',     '灰',     '#777777'],
  ['navy',     '紺',     '#000066'],
  ['darkgreen','深緑',   '#004422'],
  ['wine',     'えんじ', '#882222'],
  ['gold',     '金茶',   '#996600'],
  ['sky',      '空',     '#3388cc'],
  ['fuji',     '藤',     '#7766cc'],
];

function colorHex(key) {
  for (let i = 0; i < COLORS.length; i++) {
    if (COLORS[i][0] === key) return COLORS[i][2];
  }
  return COLORS[0][2];
}

function validColor(key) {
  for (let i = 0; i < COLORS.length; i++) {
    if (COLORS[i][0] === key) return key;
  }
  return COLORS[0][0];
}

// ---- 状態管理（すべてメモリ上） ----------------------------------------

let nextRoomId = 1;

// roomId(連番) -> room
const rooms = new Map();

// sid(セッショントークン) -> session
const sessions = new Map();

// 個人チャット: "pid小|pid大" -> { pids: [a, b], log: [], unread: {pid: bool} }
const pmThreads = new Map();

function createRoom(opts) {
  const room = {
    id: nextRoomId++,
    name: opts.name,
    description: opts.description || '',
    official: !!opts.official,
    adminPass: opts.adminPass || '',   // 公式部屋は管理者なし
    joinPass: opts.joinPass || '',     // '' なら誰でも入室可
    capacity: opts.capacity || MAX_CAPACITY,
    imagesAllowed: !!opts.imagesAllowed,
    banIps: new Set(),
    banIds: new Set(),
    createdAt: Date.now(),
    members: new Set(),
    log: [],
  };
  rooms.set(room.id, room);
  return room;
}

// 最初から入れる公式部屋(ID 1〜4)
createRoom({ name: 'ヒマ人の雑談部屋', description: 'とにかくヒマな人はここへ。話題はなんでもOK！', official: true });
createRoom({ name: '学生の部屋', description: '学校のこと、勉強のこと、ゆるく話そう', official: true });
createRoom({ name: '深夜のまったり部屋', description: '眠れない夜におしゃべりでもどうぞ', official: true });
createRoom({ name: 'ゲーム好き集まれ', description: 'ゲームの話専用。サイコロは「2d6」と発言！', official: true });

// ---- ユーティリティ -----------------------------------------------------

function sanitizeText(text, maxLength) {
  if (typeof text !== 'string') return '';
  return text.replace(/[\u0000-\u001F\u007F]/g, '').trim().slice(0, maxLength);
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// 日本時間の HH:MM 表記
function formatTime(ts) {
  if (!ts) return '--:--';
  const d = new Date(ts + 9 * 60 * 60 * 1000);
  const h = ('0' + d.getUTCHours()).slice(-2);
  const m = ('0' + d.getUTCMinutes()).slice(-2);
  return h + ':' + m;
}

function pushLog(room, entry) {
  entry.time = Date.now();
  room.log.push(entry);
  if (room.log.length > MAX_LOG_PER_ROOM) room.log.shift();
  return entry;
}

function rollDice(text) {
  const match = DICE_PATTERN.exec(text);
  if (!match) return null;
  const count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? parseInt(match[3], 10) : 0;
  if (count < 1 || count > 20 || sides < 2 || sides > 1000) return null;
  const values = [];
  for (let i = 0; i < count; i++) values.push(1 + Math.floor(Math.random() * sides));
  let total = modifier;
  for (let i = 0; i < values.length; i++) total += values[i];
  const detail = values.join(', ') + (modifier ? ' (' + match[3] + ')' : '');
  return text + ' → [' + detail + '] = ' + total;
}

function onlineCount() {
  let n = 0;
  const counted = new Set();
  rooms.forEach(function (room) {
    room.members.forEach(function (sid) { counted.add(sid); });
  });
  return counted.size || n;
}

// メンバー0の非公式部屋は一定時間後に削除する
function scheduleRoomCleanup(room) {
  if (room.official) return;
  setTimeout(function () {
    const current = rooms.get(room.id);
    if (current && current.members.size === 0) rooms.delete(room.id);
  }, 10 * 60 * 1000);
}

function leaveRoom(session, roomId, reasonText) {
  if (!session.rooms.has(roomId)) return;
  session.rooms.delete(roomId);
  const room = rooms.get(roomId);
  if (!room) return;
  room.members.delete(session.sid);
  pushLog(room, { type: 'system', text: session.name + ' さんが' + (reasonText || '退室しました') });
  if (room.members.size === 0) scheduleRoomCleanup(room);
}

function joinRoom(session, room) {
  if (session.rooms.has(room.id)) return;
  session.rooms.set(room.id, Date.now());
  room.members.add(session.sid);
  pushLog(room, { type: 'system', text: session.name + ' さんが入室しました' });
}

function deleteRoom(room) {
  room.members.forEach(function (sid) {
    const member = sessions.get(sid);
    if (member) member.rooms.delete(room.id);
  });
  rooms.delete(room.id);
}

// 放置ユーザーの自動退室と古いセッションの削除
setInterval(function () {
  const now = Date.now();
  sessions.forEach(function (session, sid) {
    if (now - session.lastSeen > IDLE_TIMEOUT_MS && session.rooms.size > 0) {
      const ids = [];
      session.rooms.forEach(function (joinedAt, roomId) { ids.push(roomId); });
      for (let i = 0; i < ids.length; i++) {
        leaveRoom(session, ids[i], '退室しました（一定時間操作がなかったため）');
      }
    }
    if (session.rooms.size === 0 && now - session.lastSeen > SESSION_TTL_MS) {
      sessions.delete(sid);
    }
  });
}, 60 * 1000);

// ---- 個人チャット -------------------------------------------------------

function findSessionByPublicId(publicId) {
  let found = null;
  sessions.forEach(function (session) {
    if (session.publicId === publicId) found = session;
  });
  return found;
}

function pmKey(pidA, pidB) {
  return pidA < pidB ? pidA + '|' + pidB : pidB + '|' + pidA;
}

function getPmThread(pidA, pidB, create) {
  const key = pmKey(pidA, pidB);
  let thread = pmThreads.get(key);
  if (!thread && create) {
    thread = { pids: [pidA, pidB], log: [], unread: {} };
    pmThreads.set(key, thread);
  }
  return thread || null;
}

function myPmThreads(pid) {
  const list = [];
  pmThreads.forEach(function (thread) {
    if (thread.pids[0] === pid || thread.pids[1] === pid) list.push(thread);
  });
  list.sort(function (a, b) {
    const at = a.log.length ? a.log[a.log.length - 1].time : 0;
    const bt = b.log.length ? b.log[b.log.length - 1].time : 0;
    return bt - at;
  });
  return list;
}

function unreadPmCount(pid) {
  let n = 0;
  pmThreads.forEach(function (thread) {
    if ((thread.pids[0] === pid || thread.pids[1] === pid) && thread.unread[pid]) n++;
  });
  return n;
}

function pmPartnerPid(thread, myPid) {
  return thread.pids[0] === myPid ? thread.pids[1] : thread.pids[0];
}

// 相手の表示情報(セッションが消えていたらログから推測)
function pmPartnerInfo(thread, partnerPid) {
  const session = findSessionByPublicId(partnerPid);
  if (session) return { name: session.name, color: session.color, online: true };
  for (let i = thread.log.length - 1; i >= 0; i--) {
    if (thread.log[i].fromPid === partnerPid) {
      return { name: thread.log[i].name, color: thread.log[i].color, online: false };
    }
  }
  return { name: '(不明)', color: 'gray', online: false };
}

// ---- Cookie・セッション -------------------------------------------------

function parseCookies(req) {
  const result = {};
  const header = req.headers.cookie;
  if (!header) return result;
  const parts = header.split(';');
  for (let i = 0; i < parts.length; i++) {
    const eq = parts[i].indexOf('=');
    if (eq === -1) continue;
    const key = parts[i].slice(0, eq).trim();
    const value = parts[i].slice(eq + 1).trim();
    try {
      result[key] = decodeURIComponent(value);
    } catch (e) {
      result[key] = value;
    }
  }
  return result;
}

function setCookie(res, name, value, maxAgeSec) {
  res.append('Set-Cookie', name + '=' + encodeURIComponent(value) + '; Path=/; Max-Age=' + maxAgeSec);
}

function clientIp(req) {
  let ip = req.ip || (req.socket && req.socket.remoteAddress) || '';
  if (ip.indexOf('::ffff:') === 0) ip = ip.slice(7);
  return ip;
}

function getSession(req) {
  const sid = parseCookies(req).sid;
  const session = sid ? sessions.get(sid) : null;
  if (session) session.lastSeen = Date.now();
  return session || null;
}

function ensureSession(req, res) {
  let session = getSession(req);
  if (!session) {
    const sid = crypto.randomBytes(16).toString('hex');
    const cookies = parseCookies(req);
    session = {
      sid,
      publicId: crypto.randomBytes(4).toString('hex'),
      name: sanitizeText(cookies.name, MAX_NAME_LENGTH) || '名無しさん',
      color: validColor(cookies.color || 'black'),
      rooms: new Map(),      // roomId -> 入室時刻
      blocks: new Set(),     // 無視している相手のpublicId
      userAgent: '',
      ip: '',
      host: '',
      lastSeen: Date.now(),
    };
    sessions.set(sid, session);
    setCookie(res, 'sid', sid, 60 * 60 * 24);
  }
  return session;
}

// アクセス情報(UA/IP/リモートホスト)を更新
function updateAccessInfo(req, session) {
  session.userAgent = String(req.headers['user-agent'] || '(不明)').slice(0, 400);
  const ip = clientIp(req);
  if (ip && ip !== session.ip) {
    session.ip = ip;
    session.host = '(取得中)';
    dns.reverse(ip, function (err, hostnames) {
      if (!sessions.has(session.sid)) return;
      session.host = (!err && hostnames && hostnames[0]) ? hostnames[0] : '(逆引きできませんでした)';
    });
  }
}

// ---- HTMLレンダリング ---------------------------------------------------

// ライトブルー基調の旧式デザイン
const STYLE =
  'body{background-color:#e2eef8;color:#223344;font-family:"MS PGothic",Osaka,"Hiragino Kaku Gothic ProN",Meiryo,sans-serif;font-size:14px;margin:6px;}' +
  'h1{font-size:19px;margin:4px 0;color:#225588;}' +
  'h2{font-size:15px;margin:8px 0 4px 0;color:#225588;}' +
  'hr{border:0;border-top:1px solid #88aacc;height:1px;}' +
  'a{color:#0055aa;}' +
  'table{border-collapse:collapse;background-color:#ffffff;}' +
  'th,td{border:1px solid #88aacc;padding:3px 6px;font-size:13px;text-align:left;}' +
  'th{background-color:#c4dcf0;font-weight:bold;}' +
  'input,select,textarea{font-size:14px;}' +
  '.box{border:1px solid #88aacc;background-color:#ffffff;padding:6px;margin:6px 0;}' +
  '.info{border:1px solid #88aacc;background-color:#f4faff;padding:6px;margin:6px 0;}' +
  '.sys{color:#7788aa;font-size:12px;}' +
  '.dice{color:#775500;}' +
  '.small{font-size:11px;color:#667788;}' +
  '.err{color:#cc0000;font-weight:bold;}' +
  '.ok{color:#007700;font-weight:bold;}' +
  '.ua{word-break:break-all;font-size:12px;}' +
  '.tabbar{margin:4px 0;}' +
  '.tab{border:1px solid #88aacc;background-color:#c4dcf0;padding:2px 8px;margin-right:2px;text-decoration:none;font-size:13px;}' +
  '.tabon{border:1px solid #88aacc;background-color:#ffffff;padding:2px 8px;margin-right:2px;font-weight:bold;font-size:13px;}' +
  '.tabnew{border:1px solid #cc6666;background-color:#ffe8e8;padding:2px 8px;margin-right:2px;text-decoration:none;font-size:13px;color:#cc0000;font-weight:bold;}' +
  '.chatimg{max-width:240px;max-height:240px;}';

function page(title, body) {
  return '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">\n' +
    '<html><head>' +
    '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">' +
    '<meta name="viewport" content="width=device-width">' +
    '<title>' + escapeHtml(SITE_NAME + ' - ' + title) + '</title>' +
    '<style type="text/css">' + STYLE + '</style>' +
    '</head><body bgcolor="#e2eef8">' + body + '</body></html>';
}

function nameHtml(name, color) {
  return '<font color="' + colorHex(color) + '"><b>' + escapeHtml(name) + '</b></font>';
}

function colorSelectHtml(selected) {
  let html = '<select name="color">';
  for (let i = 0; i < COLORS.length; i++) {
    const sel = COLORS[i][0] === selected ? ' selected' : '';
    html += '<option value="' + COLORS[i][0] + '"' + sel + '>' + COLORS[i][1] + '</option>';
  }
  return html + '</select>';
}

// TOPと入室中の部屋(最大5)・個人チャットを行き来するタブ
function tabsHtml(session, current) {
  let html = '<div class="tabbar">';
  html += current === 'top' ?
    '<span class="tabon">TOP</span>' :
    '<a class="tab" href="/">TOP</a>';
  if (session) {
    session.rooms.forEach(function (joinedAt, roomId) {
      const room = rooms.get(roomId);
      if (!room) return;
      let label = room.name;
      if (label.length > 8) label = label.slice(0, 8) + '…';
      label = escapeHtml(label) + '(' + room.members.size + ')';
      html += current === 'room' + roomId ?
        '<span class="tabon">' + label + '</span>' :
        '<a class="tab" href="/?room=' + roomId + '">' + label + '</a>';
    });
    const unread = unreadPmCount(session.publicId);
    const pmLabel = '個人チャット' + (unread > 0 ? '(新着' + unread + ')' : '');
    if (current === 'pm') {
      html += '<span class="tabon">' + pmLabel + '</span>';
    } else {
      html += '<a class="' + (unread > 0 ? 'tabnew' : 'tab') + '" href="/pm-list">' + pmLabel + '</a>';
    }
  }
  return html + '</div>';
}

// ポップアップで開くリンク(JS無効でも新しいタブ/ページで開ける)
function popupLink(url, label, w, h) {
  return '<a href="' + url + '" target="_blank" ' +
    'onclick="window.open(this.href,\'hcpopup\',\'width=' + w + ',height=' + h +
    ',scrollbars=yes,resizable=yes\');return false;">' + label + '</a>';
}

function messageHtml(msg, imagesAllowed) {
  const time = '<span class="small">(' + formatTime(msg.time) + ')</span>';
  if (msg.type === 'system') {
    return '<div class="sys">--- ' + escapeHtml(msg.text) + ' ' + time + ' ---</div>';
  }
  if (msg.type === 'dice') {
    return '<div class="dice">★' + nameHtml(msg.name, msg.color) + ' のサイコロ: ' +
      escapeHtml(msg.text) + ' ' + time + '</div>';
  }
  let body = escapeHtml(msg.text);
  if (imagesAllowed && IMAGE_URL_PATTERN.test(msg.text)) {
    const url = escapeHtml(msg.text);
    body = '<a href="' + url + '" target="_blank">' + url + '</a><br>' +
      '<img src="' + url + '" alt="投稿画像" class="chatimg">';
  }
  return '<div>' + nameHtml(msg.name, msg.color) + '＞ ' + body + ' ' + time + '</div>';
}

function logHtml(room) {
  const lines = [];
  for (let i = room.log.length - 1; i >= 0; i--) {
    lines.push(messageHtml(room.log[i], room.imagesAllowed));
  }
  return lines.join('\n');
}

function lockMark(room) {
  return room.joinPass ? '◆鍵' : '';
}

// information.txt から更新情報を読む
function readInfoLines() {
  try {
    const text = fs.readFileSync(INFO_FILE, 'utf8');
    const lines = text.split('\n');
    const result = [];
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (line) result.push(line);
    }
    return result;
  } catch (e) {
    return [];
  }
}

// ---- TOPページ ----------------------------------------------------------

const TOP_ERRORS = {
  noroom: 'その部屋は見つかりませんでした（削除された可能性があります）',
  deleted: '部屋を削除しました',
  contact: 'メッセージを送信しました。ありがとうございました',
  profile: '名前を保存しました',
};

function topPage(req, res) {
  const session = getSession(req);
  const cookies = parseCookies(req);
  const myName = (session && session.name) || sanitizeText(cookies.name, MAX_NAME_LENGTH) || '名無しさん';
  const myColor = validColor((session && session.color) || cookies.color || 'black');

  let noticeHtml = '';
  const e = req.query.e;
  if (e && TOP_ERRORS[e]) {
    const cls = (e === 'noroom') ? 'err' : 'ok';
    noticeHtml = '<div class="' + cls + '">' + TOP_ERRORS[e] + '</div>';
  }

  // インフォメーション(information.txt の先頭5件)
  const infoLines = readInfoLines();
  let infoHtml = '';
  if (infoLines.length > 0) {
    infoHtml = '<div class="info"><b>■インフォメーション</b><br>';
    for (let i = 0; i < Math.min(5, infoLines.length); i++) {
      infoHtml += '<span class="small">' + escapeHtml(infoLines[i]) + '</span><br>';
    }
    if (infoLines.length > 5) infoHtml += '<span class="small">[<a href="/info">過去の更新情報</a>]</span>';
    infoHtml += '</div>';
  }

  let roomRows = '';
  const sorted = [];
  rooms.forEach(function (room) { sorted.push(room); });
  sorted.sort(function (a, b) { return (b.official - a.official) || (a.id - b.id); });
  for (let i = 0; i < sorted.length; i++) {
    const room = sorted[i];
    let desc = room.description;
    if (desc.length > 40) desc = desc.slice(0, 40) + '…';
    roomRows += '<tr>' +
      '<td>' + room.id + '</td>' +
      '<td><a href="/?room=' + room.id + '">' + (room.official ? '★' : '') + escapeHtml(room.name) + '</a> ' + lockMark(room) + '</td>' +
      '<td>' + escapeHtml(desc) + '</td>' +
      '<td align="right">' + room.members.size + '/' + room.capacity + '人</td>' +
      '</tr>';
  }

  const body =
    tabsHtml(session, 'top') +
    '<h1>' + SITE_NAME + '</h1>' +
    '<div class="small">ヒマな人のためのチャット。登録不要・完全無料。</div>' +
    '<div>現在 <b>' + onlineCount() + '</b> 人がチャット中 ／ 部屋数 ' + rooms.size + ' ／ <a href="/">再読込</a></div>' +
    noticeHtml +
    infoHtml +
    '<h2>■あなたの名前(全部屋共通)</h2>' +
    '<form method="POST" action="/profile">' +
    '<div class="box">' +
    '現在: ' + nameHtml(myName, myColor) + '<br>' +
    '名前: <input type="text" name="name" size="12" maxlength="' + MAX_NAME_LENGTH + '" value="' + escapeHtml(myName) + '"> ' +
    '名前の色: ' + colorSelectHtml(myColor) + ' ' +
    '<input type="submit" value="保存">' +
    '<div class="small">※名前はここでだけ変更できます。入室中の全部屋・個人チャットに反映されます。</div>' +
    '</div>' +
    '</form>' +
    '<h2>■チャットルーム一覧</h2>' +
    '<div class="small">部屋名を押すと説明を確認してから入室できます。◆鍵 はパスワードが必要な個室です。</div>' +
    '<table width="100%">' +
    '<tr><th>No.</th><th>部屋名</th><th>説明</th><th>人数</th></tr>' +
    roomRows +
    '</table>' +
    '<form method="GET" action="/create">' +
    '<div style="margin:6px 0;"><input type="submit" value="部屋を作る"></div>' +
    '</form>' +
    '<hr>' +
    '[<a href="/pm-list">個人チャット</a>] [<a href="/info">インフォメーション</a>] [<a href="/contact">管理者に連絡</a>]' +
    '<hr>' +
    '<div class="small">※個人情報（本名・住所・連絡先など）は絶対に書き込まないでください。<br>' +
    '※同時に入室できるのは' + MAX_JOINED_ROOMS + '部屋までです。一定時間操作がないと自動退室になります。</div>';

  res.send(page('部屋一覧', body));
}

// 名前・色の保存(全部屋共通)
app.post('/profile', function (req, res) {
  const session = ensureSession(req, res);
  const name = sanitizeText(req.body.name, MAX_NAME_LENGTH) || '名無しさん';
  const color = validColor(req.body.color);
  session.name = name;
  session.color = color;
  updateAccessInfo(req, session);
  setCookie(res, 'name', name, 60 * 60 * 24 * 30);
  setCookie(res, 'color', color, 60 * 60 * 24 * 30);
  res.redirect('/?e=profile');
});

// ---- 部屋の作成ページ ---------------------------------------------------

const CREATE_ERRORS = {
  roomname: '部屋の名前を入力してください',
  roomsmax: 'これ以上部屋を作成できません',
  noadmin: '管理パスワードを入力してください',
  samepass: '入室パスワードは管理パスワードと同じにできません',
};

app.get('/create', function (req, res) {
  const session = getSession(req);
  const e = req.query.e;
  const errorHtml = (e && CREATE_ERRORS[e]) ? '<div class="err">' + CREATE_ERRORS[e] + '</div>' : '';

  let capacityOptions = '';
  for (let n = MIN_CAPACITY; n <= MAX_CAPACITY; n++) {
    capacityOptions += '<option value="' + n + '"' + (n === 20 ? ' selected' : '') + '>' + n + '人</option>';
  }

  const body =
    tabsHtml(session, null) +
    '<h1>部屋を作る</h1>' +
    errorHtml +
    '<form method="POST" action="/create">' +
    '<div class="box">' +
    '部屋名: <input type="text" name="roomName" size="16" maxlength="' + MAX_ROOM_NAME_LENGTH + '"> ' +
    '定員: <select name="capacity">' + capacityOptions + '</select><br>' +
    '説明文:<br><textarea name="roomDesc" rows="3" cols="40"></textarea><br>' +
    '管理パスワード(必須): <input type="password" name="adminPass" size="10" maxlength="' + MAX_PASS_LENGTH + '"><br>' +
    '入室パスワード(任意・鍵付き個室にする場合): <input type="password" name="joinPass" size="10" maxlength="' + MAX_PASS_LENGTH + '"><br>' +
    '<input type="checkbox" name="images" value="1">画像投稿(画像URLのインライン表示)を許可する<br>' +
    '<input type="submit" value="作成して入室"> <a href="/">[やめる(TOPへ戻る)]</a>' +
    '<div class="small">※管理パスワードで部屋の削除・アクセス禁止・画像投稿の切替ができます。<br>' +
    '※名前はTOPページで設定したものが使われます。</div>' +
    '</div>' +
    '</form>';

  res.send(page('部屋を作る', body));
});

app.post('/create', function (req, res) {
  const roomName = sanitizeText(req.body.roomName, MAX_ROOM_NAME_LENGTH);
  if (!roomName) return res.redirect('/create?e=roomname');
  if (rooms.size >= MAX_ROOMS) return res.redirect('/create?e=roomsmax');

  const adminPass = sanitizeText(req.body.adminPass, MAX_PASS_LENGTH);
  if (!adminPass) return res.redirect('/create?e=noadmin');
  const joinPass = sanitizeText(req.body.joinPass, MAX_PASS_LENGTH);
  if (joinPass && joinPass === adminPass) return res.redirect('/create?e=samepass');

  let capacity = parseInt(req.body.capacity, 10);
  if (isNaN(capacity)) capacity = 20;
  capacity = Math.max(MIN_CAPACITY, Math.min(MAX_CAPACITY, capacity));

  const session = ensureSession(req, res);
  updateAccessInfo(req, session);
  if (session.rooms.size >= MAX_JOINED_ROOMS) return res.redirect('/?room=1&e=limit');

  const room = createRoom({
    name: roomName,
    description: sanitizeText(req.body.roomDesc, MAX_ROOM_DESC_LENGTH),
    adminPass,
    joinPass,
    capacity,
    imagesAllowed: req.body.images === '1',
  });
  joinRoom(session, room);
  res.redirect('/?room=' + room.id);
});

// ---- 入室前の確認ページ -------------------------------------------------

const ENTRY_ERRORS = {
  pass: '入室パスワードが違います',
  full: '満室のため入室できません',
  ban: 'この部屋への入室は禁止されています',
  limit: '同時に入室できるのは' + MAX_JOINED_ROOMS + '部屋までです。どこかの部屋を退室してください',
};

function entryPage(req, res, room) {
  const session = getSession(req);
  const cookies = parseCookies(req);
  const myName = (session && session.name) || sanitizeText(cookies.name, MAX_NAME_LENGTH) || '名無しさん';
  const myColor = validColor((session && session.color) || cookies.color || 'black');

  const e = req.query.e;
  const errorHtml = (e && ENTRY_ERRORS[e]) ? '<div class="err">' + ENTRY_ERRORS[e] + '</div>' : '';

  const passField = room.joinPass ?
    '入室パスワード: <input type="password" name="joinPass" size="10" maxlength="' + MAX_PASS_LENGTH + '"><br>' : '';

  const body =
    tabsHtml(session, null) +
    '<h1>' + (room.official ? '★' : '') + escapeHtml(room.name) + ' ' + lockMark(room) + '</h1>' +
    errorHtml +
    '<table width="100%">' +
    '<tr><th width="90">部屋No.</th><td>' + room.id + '</td></tr>' +
    '<tr><th>説明文</th><td>' + (escapeHtml(room.description) || '(説明はありません)') + '</td></tr>' +
    '<tr><th>人数</th><td>' + room.members.size + '/' + room.capacity + '人</td></tr>' +
    '<tr><th>入室制限</th><td>' + (room.joinPass ? '◆鍵付き個室(入室パスワードが必要です)' : 'なし(誰でも入室できます)') + '</td></tr>' +
    '<tr><th>画像投稿</th><td>' + (room.imagesAllowed ? '可' : '不可') + '</td></tr>' +
    '</table>' +
    '<h2>■この部屋に入りますか？</h2>' +
    '<form method="POST" action="/join">' +
    '<div class="box">' +
    '<input type="hidden" name="room" value="' + room.id + '">' +
    'あなたの名前: ' + nameHtml(myName, myColor) + ' <span class="small">(名前は<a href="/">TOPページ</a>で変更できます)</span><br>' +
    passField +
    '<input type="submit" value="入室する"> <a href="/">[やめる(TOPへ戻る)]</a>' +
    '</div>' +
    '</form>';

  res.send(page('入室確認', body));
}

// ---- チャット画面 -------------------------------------------------------

function autoParam(value) {
  const n = parseInt(value, 10);
  return (n === 10 || n === 30) ? n : 0;
}

function chatPage(req, res, room, session) {
  const auto = autoParam(req.query.auto);
  const base = '/?room=' + room.id;
  const refreshMeta = auto ?
    '<meta http-equiv="refresh" content="' + auto + ';url=' + base + '&auto=' + auto + '">' : '';

  const autoLinks =
    '自動更新: ' +
    (auto === 0 ? '<b>[OFF]</b>' : '<a href="' + base + '&auto=0">[OFF]</a>') + ' ' +
    (auto === 10 ? '<b>[10秒]</b>' : '<a href="' + base + '&auto=10">[10秒]</a>') + ' ' +
    (auto === 30 ? '<b>[30秒]</b>' : '<a href="' + base + '&auto=30">[30秒]</a>');

  const adminLink = room.adminPass ? ' [<a href="/admin?room=' + room.id + '">管理</a>]' : '';

  const body =
    refreshMeta +
    tabsHtml(session, 'room' + room.id) +
    '<b>' + (room.official ? '★' : '') + escapeHtml(room.name) + '</b>' +
    ' (' + room.members.size + '/' + room.capacity + '人) ' + lockMark(room) +
    ' [' + popupLink('/members?room=' + room.id, '参加者一覧', 480, 420) + ']' +
    adminLink +
    ' [<a href="/leave?room=' + room.id + '">退室</a>]' +
    '<div class="small">' + escapeHtml(room.description) + '</div>' +
    '<hr>' +
    '<form method="POST" action="/say">' +
    '<input type="hidden" name="room" value="' + room.id + '">' +
    '<input type="hidden" name="auto" value="' + auto + '">' +
    nameHtml(session.name, session.color) + '＞ ' +
    '<input type="text" name="m" size="24" maxlength="' + MAX_MESSAGE_LENGTH + '"> ' +
    '<input type="submit" value="送信"> ' +
    '[<a href="' + base + '&auto=' + auto + '">更新</a>]' +
    '</form>' +
    '<div class="small">「2d6」でサイコロ' +
    (room.imagesAllowed ? ' ／ 画像URL(jpg/gif/png)を発言すると画像表示' : '') +
    ' ／ ' + autoLinks + '</div>' +
    '<hr>' +
    logHtml(room) +
    '<hr>' +
    '[<a href="' + base + '&auto=' + auto + '">更新</a>] [<a href="/leave?room=' + room.id + '">退室</a>] [<a href="/">TOPへ</a>]';

  res.send(page(room.name, body));
}

// ---- ルーティング: TOP/入室/発言 ---------------------------------------

app.get('/', function (req, res) {
  const roomId = parseInt(req.query.room, 10);
  if (!req.query.room) return topPage(req, res);

  const room = rooms.get(roomId);
  if (!room) return res.redirect('/?e=noroom');

  const session = getSession(req);
  if (session && session.rooms.has(room.id)) return chatPage(req, res, room, session);
  return entryPage(req, res, room);
});

app.post('/join', function (req, res) {
  const roomId = parseInt(req.body.room, 10);
  const room = rooms.get(roomId);
  if (!room) return res.redirect('/?e=noroom');

  const session = ensureSession(req, res);
  updateAccessInfo(req, session);
  const base = '/?room=' + room.id;

  if (session.rooms.has(room.id)) return res.redirect(base);
  if (room.banIds.has(session.publicId) || room.banIps.has(session.ip)) {
    return res.redirect(base + '&e=ban');
  }
  if (room.members.size >= room.capacity) return res.redirect(base + '&e=full');
  if (session.rooms.size >= MAX_JOINED_ROOMS) return res.redirect(base + '&e=limit');
  if (room.joinPass && sanitizeText(req.body.joinPass, MAX_PASS_LENGTH) !== room.joinPass) {
    return res.redirect(base + '&e=pass');
  }

  joinRoom(session, room);
  res.redirect(base);
});

app.post('/say', function (req, res) {
  const roomId = parseInt(req.body.room, 10);
  const room = rooms.get(roomId);
  const session = getSession(req);
  const auto = autoParam(req.body.auto);
  if (!room || !session || !session.rooms.has(roomId)) return res.redirect('/');

  const text = sanitizeText(req.body.m, MAX_MESSAGE_LENGTH);
  if (text) {
    pushLog(room, { type: 'chat', name: session.name, color: session.color, text });
    const dice = rollDice(text);
    if (dice) {
      pushLog(room, { type: 'dice', name: session.name, color: session.color, text: dice });
    }
  }
  res.redirect('/?room=' + roomId + '&auto=' + auto);
});

app.get('/leave', function (req, res) {
  const roomId = parseInt(req.query.room, 10);
  const session = getSession(req);
  if (session) leaveRoom(session, roomId, '退室しました');
  res.redirect('/');
});

// ---- 参加者一覧・ユーザー詳細(ポップアップ) -----------------------------

app.get('/members', function (req, res) {
  const roomId = parseInt(req.query.room, 10);
  const room = rooms.get(roomId);
  const session = getSession(req);
  if (!room || !session || !session.rooms.has(roomId)) {
    return res.send(page('参加者一覧', '<div class="err">この部屋には入室していません</div>'));
  }

  let memberRows = '';
  room.members.forEach(function (sid) {
    const member = sessions.get(sid);
    if (!member) return;
    const isSelf = member.sid === session.sid;
    const pmLink = isSelf ? '-' :
      '<a href="/pm?with=' + member.publicId + '" target="_top">個人チャット</a>';
    memberRows += '<tr>' +
      '<td>' + nameHtml(member.name, member.color) + (isSelf ? ' <span class="small">(自分)</span>' : '') + '</td>' +
      '<td>' + formatTime(member.rooms.get(roomId)) + '</td>' +
      '<td><a href="/user?room=' + roomId + '&id=' + member.publicId + '">詳細</a></td>' +
      '<td>' + pmLink + '</td>' +
      '</tr>';
  });

  const body =
    '<b>' + escapeHtml(room.name) + '</b> の参加者 (' + room.members.size + '/' + room.capacity + '人)' +
    '<hr>' +
    '<table width="100%">' +
    '<tr><th>名前</th><th>入室時刻</th><th>詳細</th><th>個人チャット</th></tr>' +
    memberRows +
    '</table>' +
    '<hr>' +
    '<div class="small">このウィンドウは閉じてください</div>';

  res.send(page('参加者一覧 - ' + room.name, body));
});

app.get('/user', function (req, res) {
  const roomId = parseInt(req.query.room, 10);
  const room = rooms.get(roomId);
  const session = getSession(req);
  if (!room || !session || !session.rooms.has(roomId)) {
    return res.send(page('ユーザー詳細', '<div class="err">この部屋には入室していません</div>'));
  }

  let target = null;
  room.members.forEach(function (sid) {
    const member = sessions.get(sid);
    if (member && member.publicId === req.query.id) target = member;
  });
  if (!target) {
    return res.send(page('ユーザー詳細',
      '<div class="err">そのユーザーは見つかりませんでした（退室した可能性があります）</div>' +
      '<hr>[<a href="/members?room=' + roomId + '">参加者一覧に戻る</a>]'));
  }

  const body =
    '<b>ユーザー詳細</b>' +
    '<hr>' +
    '<table width="100%">' +
    '<tr><th width="110">名前</th><td>' + nameHtml(target.name, target.color) + '</td></tr>' +
    '<tr><th>名前の色</th><td><font color="' + colorHex(target.color) + '">■</font> ' + colorHex(target.color) + '</td></tr>' +
    '<tr><th>入室時刻</th><td>' + formatTime(target.rooms.get(roomId)) + '</td></tr>' +
    '<tr><th>最終アクセス</th><td>' + formatTime(target.lastSeen) + '</td></tr>' +
    '<tr><th>IPアドレス</th><td>' + escapeHtml(target.ip || '(不明)') + '</td></tr>' +
    '<tr><th>プロバイダ<br>(リモートホスト)</th><td class="ua">' + escapeHtml(target.host || '(不明)') + '</td></tr>' +
    '<tr><th>ユーザーエージェント</th><td class="ua">' + escapeHtml(target.userAgent || '(不明)') + '</td></tr>' +
    '</table>' +
    '<hr>' +
    '[<a href="/members?room=' + roomId + '">参加者一覧に戻る</a>]' +
    (target.sid === session.sid ? '' : ' [<a href="/pm?with=' + target.publicId + '" target="_top">個人チャット</a>]');

  res.send(page('ユーザー詳細', body));
});

// ---- 個人チャット -------------------------------------------------------

const PM_ERRORS = {
  blocked: '送信できませんでした（相手に無視されています）',
  youblock: 'この相手を無視中です。解除すると送受信できます',
  gone: '相手が見つかりませんでした（退室した可能性があります）',
};

app.get('/pm-list', function (req, res) {
  const session = ensureSession(req, res);

  let rows = '';
  const threads = myPmThreads(session.publicId);
  for (let i = 0; i < threads.length; i++) {
    const thread = threads[i];
    const partnerPid = pmPartnerPid(thread, session.publicId);
    const partner = pmPartnerInfo(thread, partnerPid);
    const last = thread.log.length ? thread.log[thread.log.length - 1] : null;
    const unread = thread.unread[session.publicId] ? ' <span class="err">●新着</span>' : '';
    const blocked = session.blocks.has(partnerPid) ? ' <span class="small">(無視中)</span>' : '';
    rows += '<tr>' +
      '<td>' + nameHtml(partner.name, partner.color) +
      (partner.online ? '' : ' <span class="small">(不在)</span>') + unread + blocked + '</td>' +
      '<td>' + (last ? formatTime(last.time) : '-') + '</td>' +
      '<td><a href="/pm?with=' + partnerPid + '">開く</a></td>' +
      '</tr>';
  }
  if (!rows) rows = '<tr><td colspan="3">(個人チャットはまだありません。部屋の参加者一覧から始められます)</td></tr>';

  const body =
    tabsHtml(session, 'pm') +
    '<h1>個人チャット</h1>' +
    '<table width="100%">' +
    '<tr><th>相手</th><th>最終発言</th><th>開く</th></tr>' +
    rows +
    '</table>' +
    '<hr>' +
    '[<a href="/pm-list">更新</a>] [<a href="/">TOPへ</a>]';

  res.send(page('個人チャット', body));
});

function pmPage(req, res, session, partnerPid) {
  const thread = getPmThread(session.publicId, partnerPid, true);
  thread.unread[session.publicId] = false;

  const partner = pmPartnerInfo(thread, partnerPid);
  const e = req.query.e;
  const errorHtml = (e && PM_ERRORS[e]) ? '<div class="err">' + PM_ERRORS[e] + '</div>' : '';

  const iBlock = session.blocks.has(partnerPid);
  const blockForm =
    '<form method="POST" action="/pm/block" style="display:inline;">' +
    '<input type="hidden" name="with" value="' + escapeHtml(partnerPid) + '">' +
    '<input type="hidden" name="mode" value="' + (iBlock ? 'off' : 'on') + '">' +
    '<input type="submit" value="' + (iBlock ? '無視解除' : '無視する') + '">' +
    '</form>';

  const lines = [];
  for (let i = thread.log.length - 1; i >= 0; i--) {
    const msg = thread.log[i];
    lines.push('<div>' + nameHtml(msg.name, msg.color) + '＞ ' + escapeHtml(msg.text) +
      ' <span class="small">(' + formatTime(msg.time) + ')</span></div>');
  }

  const sendForm = iBlock ?
    '<div class="sys">この相手を無視中のため送信できません。</div>' :
    '<form method="POST" action="/pm/say">' +
    '<input type="hidden" name="with" value="' + escapeHtml(partnerPid) + '">' +
    nameHtml(session.name, session.color) + '＞ ' +
    '<input type="text" name="m" size="24" maxlength="' + MAX_MESSAGE_LENGTH + '"> ' +
    '<input type="submit" value="送信"> ' +
    '[<a href="/pm?with=' + escapeHtml(partnerPid) + '">更新</a>]' +
    '</form>';

  const body =
    tabsHtml(session, 'pm') +
    '<b>個人チャット: ' + nameHtml(partner.name, partner.color) + '</b>' +
    (partner.online ? '' : ' <span class="small">(不在)</span>') +
    ' ' + blockForm +
    errorHtml +
    '<hr>' +
    sendForm +
    '<div class="small">※このやり取りは相手とあなたにしか見えません。</div>' +
    '<hr>' +
    (lines.join('\n') || '<div class="sys">(まだ発言はありません)</div>') +
    '<hr>' +
    '[<a href="/pm?with=' + escapeHtml(partnerPid) + '">更新</a>] [<a href="/pm-list">一覧へ</a>] [<a href="/">TOPへ</a>]';

  res.send(page('個人チャット - ' + partner.name, body));
}

app.get('/pm', function (req, res) {
  const session = ensureSession(req, res);
  const partnerPid = sanitizeText(req.query.with, 16);
  if (!partnerPid || partnerPid === session.publicId) return res.redirect('/pm-list');
  pmPage(req, res, session, partnerPid);
});

app.post('/pm/say', function (req, res) {
  const session = getSession(req);
  const partnerPid = sanitizeText(req.body.with, 16);
  if (!session || !partnerPid || partnerPid === session.publicId) return res.redirect('/pm-list');
  const back = '/pm?with=' + encodeURIComponent(partnerPid);

  if (session.blocks.has(partnerPid)) return res.redirect(back + '&e=youblock');
  const partner = findSessionByPublicId(partnerPid);
  if (!partner) return res.redirect(back + '&e=gone');
  if (partner.blocks.has(session.publicId)) return res.redirect(back + '&e=blocked');

  const text = sanitizeText(req.body.m, MAX_MESSAGE_LENGTH);
  if (text) {
    const thread = getPmThread(session.publicId, partnerPid, true);
    thread.log.push({
      fromPid: session.publicId,
      name: session.name,
      color: session.color,
      text,
      time: Date.now(),
    });
    if (thread.log.length > MAX_LOG_PER_PM) thread.log.shift();
    thread.unread[partnerPid] = true;
    thread.unread[session.publicId] = false;
  }
  res.redirect(back);
});

// 無視(ブロック)の設定・解除
app.post('/pm/block', function (req, res) {
  const session = getSession(req);
  const partnerPid = sanitizeText(req.body.with, 16);
  if (!session || !partnerPid) return res.redirect('/pm-list');
  if (req.body.mode === 'on') {
    session.blocks.add(partnerPid);
  } else {
    session.blocks.delete(partnerPid);
  }
  res.redirect('/pm?with=' + encodeURIComponent(partnerPid));
});

// ---- 部屋の管理(管理パスワード) -----------------------------------------

function adminLoginPage(room, errorText) {
  return page('部屋の管理',
    '<h1>部屋の管理: ' + escapeHtml(room.name) + '</h1>' +
    (errorText ? '<div class="err">' + errorText + '</div>' : '') +
    '<form method="POST" action="/admin/panel">' +
    '<div class="box">' +
    '<input type="hidden" name="room" value="' + room.id + '">' +
    '管理パスワード: <input type="password" name="pass" size="12" maxlength="' + MAX_PASS_LENGTH + '"> ' +
    '<input type="submit" value="ログイン">' +
    '</div>' +
    '</form>' +
    '[<a href="/?room=' + room.id + '">チャットに戻る</a>]');
}

function adminHiddenFields(room, pass, act) {
  return '<input type="hidden" name="room" value="' + room.id + '">' +
    '<input type="hidden" name="pass" value="' + escapeHtml(pass) + '">' +
    '<input type="hidden" name="act" value="' + act + '">';
}

function adminPanelPage(room, pass, noticeText) {
  let memberRows = '';
  room.members.forEach(function (sid) {
    const member = sessions.get(sid);
    if (!member) return;
    memberRows += '<tr>' +
      '<td>' + nameHtml(member.name, member.color) + '</td>' +
      '<td class="ua">' + escapeHtml(member.ip || '(不明)') + '</td>' +
      '<td><form method="POST" action="/admin/action">' +
      adminHiddenFields(room, pass, 'ban') +
      '<input type="hidden" name="target" value="' + member.publicId + '">' +
      '<input type="submit" value="アクセス禁止">' +
      '</form></td>' +
      '</tr>';
  });
  if (!memberRows) memberRows = '<tr><td colspan="3">(入室者なし)</td></tr>';

  let banRows = '';
  room.banIps.forEach(function (ip) {
    banRows += '<tr><td class="ua">' + escapeHtml(ip) + '</td>' +
      '<td><form method="POST" action="/admin/action">' +
      adminHiddenFields(room, pass, 'unban') +
      '<input type="hidden" name="target" value="' + escapeHtml(ip) + '">' +
      '<input type="submit" value="解除">' +
      '</form></td></tr>';
  });
  if (!banRows) banRows = '<tr><td colspan="2">(アクセス禁止中のユーザーはいません)</td></tr>';

  const body =
    '<h1>部屋の管理: ' + escapeHtml(room.name) + '</h1>' +
    (noticeText ? '<div class="ok">' + noticeText + '</div>' : '') +
    '<h2>■画像投稿</h2>' +
    '<div class="box">現在: <b>' + (room.imagesAllowed ? '許可' : '禁止') + '</b> ' +
    '<form method="POST" action="/admin/action">' +
    adminHiddenFields(room, pass, room.imagesAllowed ? 'images_off' : 'images_on') +
    '<input type="submit" value="' + (room.imagesAllowed ? '禁止にする' : '許可にする') + '">' +
    '</form>' +
    '</div>' +
    '<h2>■入室者とアクセス禁止</h2>' +
    '<table width="100%"><tr><th>名前</th><th>IP</th><th>操作</th></tr>' + memberRows + '</table>' +
    '<div class="small">アクセス禁止にすると強制退室になり、同じIP・ユーザーからは再入室できません。</div>' +
    '<h2>■アクセス禁止リスト(IP)</h2>' +
    '<table width="100%"><tr><th>IP</th><th>操作</th></tr>' + banRows + '</table>' +
    '<h2>■部屋の削除</h2>' +
    '<div class="box">' +
    '<form method="POST" action="/admin/action">' +
    adminHiddenFields(room, pass, 'delete') +
    '<input type="submit" value="この部屋を削除する">' +
    '</form>' +
    '<span class="small">※押すと確認画面が表示されます。</span>' +
    '</div>' +
    '<hr>' +
    '[<a href="/?room=' + room.id + '">チャットに戻る</a>] [<a href="/">TOPへ</a>]';

  return page('部屋の管理', body);
}

// 部屋削除の確認ダイアログ(確認ページ)
function adminDeleteConfirmPage(room, pass) {
  const body =
    '<h1>部屋の削除確認</h1>' +
    '<div class="box">' +
    '<div class="err">本当に部屋「' + escapeHtml(room.name) + '」(No.' + room.id + ')を削除しますか？</div>' +
    '<div class="small">※入室中の' + room.members.size + '人は全員退室になり、ログも消えます。この操作は取り消せません。</div>' +
    '<form method="POST" action="/admin/action" style="display:inline;">' +
    adminHiddenFields(room, pass, 'delete_confirm') +
    '<input type="submit" value="削除する">' +
    '</form> ' +
    '<form method="POST" action="/admin/panel" style="display:inline;">' +
    '<input type="hidden" name="room" value="' + room.id + '">' +
    '<input type="hidden" name="pass" value="' + escapeHtml(pass) + '">' +
    '<input type="submit" value="やめる(管理画面へ戻る)">' +
    '</form>' +
    '</div>';
  return page('部屋の削除確認', body);
}

app.get('/admin', function (req, res) {
  const roomId = parseInt(req.query.room, 10);
  const room = rooms.get(roomId);
  if (!room) return res.redirect('/?e=noroom');
  if (!room.adminPass) return res.redirect('/?room=' + roomId);
  res.send(adminLoginPage(room, ''));
});

app.post('/admin/panel', function (req, res) {
  const roomId = parseInt(req.body.room, 10);
  const room = rooms.get(roomId);
  if (!room) return res.redirect('/?e=noroom');
  const pass = sanitizeText(req.body.pass, MAX_PASS_LENGTH);
  if (!room.adminPass || pass !== room.adminPass) {
    return res.send(adminLoginPage(room, '管理パスワードが違います'));
  }
  res.send(adminPanelPage(room, pass, ''));
});

app.post('/admin/action', function (req, res) {
  const roomId = parseInt(req.body.room, 10);
  const room = rooms.get(roomId);
  if (!room) return res.redirect('/?e=noroom');
  const pass = sanitizeText(req.body.pass, MAX_PASS_LENGTH);
  if (!room.adminPass || pass !== room.adminPass) {
    return res.send(adminLoginPage(room, '管理パスワードが違います'));
  }

  const act = req.body.act;
  let notice = '';

  if (act === 'images_on') {
    room.imagesAllowed = true;
    notice = '画像投稿を許可しました';
  } else if (act === 'images_off') {
    room.imagesAllowed = false;
    notice = '画像投稿を禁止しました';
  } else if (act === 'ban') {
    const targetId = String(req.body.target || '');
    let target = null;
    room.members.forEach(function (sid) {
      const member = sessions.get(sid);
      if (member && member.publicId === targetId) target = member;
    });
    if (target) {
      room.banIds.add(target.publicId);
      if (target.ip) room.banIps.add(target.ip);
      leaveRoom(target, room.id, '退室しました（管理者によるアクセス禁止）');
      notice = target.name + ' さんをアクセス禁止にしました';
    } else {
      notice = '対象のユーザーが見つかりませんでした';
    }
  } else if (act === 'unban') {
    room.banIps.delete(String(req.body.target || ''));
    notice = 'アクセス禁止を解除しました';
  } else if (act === 'delete') {
    // まず確認ダイアログ(確認ページ)を表示する
    return res.send(adminDeleteConfirmPage(room, pass));
  } else if (act === 'delete_confirm') {
    deleteRoom(room);
    return res.redirect('/?e=deleted');
  }

  res.send(adminPanelPage(room, pass, notice));
});

// ---- インフォメーション・連絡フォーム -----------------------------------

app.get('/info', function (req, res) {
  const session = getSession(req);
  const lines = readInfoLines();
  let listHtml = '';
  if (lines.length === 0) {
    listHtml = '<div>(更新情報はまだありません)</div>';
  } else {
    for (let i = 0; i < lines.length; i++) {
      listHtml += '<div>' + escapeHtml(lines[i]) + '</div>';
    }
  }
  const body =
    tabsHtml(session, null) +
    '<h1>インフォメーション</h1>' +
    '<div class="info">' + listHtml + '</div>' +
    '[<a href="/">TOPへ戻る</a>] [<a href="/contact">管理者に連絡</a>]';
  res.send(page('インフォメーション', body));
});

app.get('/contact', function (req, res) {
  const session = getSession(req);
  const body =
    tabsHtml(session, null) +
    '<h1>管理者に連絡</h1>' +
    '<div class="small">不具合の報告・要望・削除依頼などはこちらからどうぞ。</div>' +
    '<form method="POST" action="/contact">' +
    '<div class="box">' +
    'お名前(任意): <input type="text" name="name" size="16" maxlength="' + MAX_NAME_LENGTH + '"><br>' +
    '連絡先(任意): <input type="text" name="addr" size="30" maxlength="100"><br>' +
    '内容:<br><textarea name="body" rows="6" cols="40"></textarea><br>' +
    '<input type="submit" value="送信する"> <a href="/">[やめる]</a>' +
    '</div>' +
    '</form>';
  res.send(page('管理者に連絡', body));
});

app.post('/contact', function (req, res) {
  const text = sanitizeText(req.body.body, 1000);
  if (!text) return res.redirect('/contact');
  const entry = [
    new Date().toISOString(),
    'ip=' + clientIp(req),
    'name=' + sanitizeText(req.body.name, MAX_NAME_LENGTH),
    'addr=' + sanitizeText(req.body.addr, 100),
    'body=' + text,
  ].join('\t') + '\n';
  fs.appendFile(CONTACT_LOG, entry, function () {});
  res.redirect('/?e=contact');
});

app.listen(PORT, function () {
  console.log(SITE_NAME + 'が起動しました: http://localhost:' + PORT);
});
