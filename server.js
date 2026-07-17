'use strict';

// ヒマチャット風 - 旧式携帯・CGIチャットスタイルのルーム型チャット
// クライアントJS不要・フォーム送信とページ更新だけで動くため、
// iOS4 / Android 1.6 / 3DS などの古いブラウザでも動作する。

const crypto = require('crypto');
const express = require('express');

const app = express();
app.use(express.urlencoded({ extended: false }));

const PORT = process.env.PORT || 3000;

// ---- 定数 ---------------------------------------------------------------

const MAX_NAME_LENGTH = 20;
const MAX_MESSAGE_LENGTH = 500;
const MAX_ROOM_NAME_LENGTH = 30;
const MAX_ROOM_DESC_LENGTH = 60;
const MAX_LOG_PER_ROOM = 100;
const MAX_ROOMS = 200;
const IDLE_TIMEOUT_MS = 10 * 60 * 1000;   // 操作がないとこの時間で自動退室
const SESSION_TTL_MS = 60 * 60 * 1000;    // 退室後セッションを保持する時間

// サイコロコマンド: 「2d6」「1d100+3」のような発言でダイスを振る
const DICE_PATTERN = /^(\d{1,2})[dD](\d{1,4})([+-]\d{1,4})?$/;

// 名前の色（キー, 表示名, 色コード）
const COLORS = [
  ['black',  '黒',   '#222222'],
  ['red',    '赤',   '#cc0000'],
  ['blue',   '青',   '#0000cc'],
  ['green',  '緑',   '#007700'],
  ['orange', '橙',   '#cc6600'],
  ['purple', '紫',   '#770077'],
  ['brown',  '茶',   '#774411'],
  ['pink',   '桃',   '#cc0077'],
  ['teal',   '水',   '#007777'],
  ['gray',   '灰',   '#777777'],
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

// roomId -> { id, name, description, official, createdAt, members: Set(sid), log: [] }
const rooms = new Map();

// sid(セッショントークン) -> { sid, publicId, name, color, roomId, userAgent, joinedAt, lastSeen }
const sessions = new Map();

function createRoom(name, description, official) {
  const id = crypto.randomBytes(6).toString('hex');
  const room = {
    id,
    name,
    description,
    official: !!official,
    createdAt: Date.now(),
    members: new Set(),
    log: [],
  };
  rooms.set(id, room);
  return room;
}

// 最初から入れる公式部屋
createRoom('ヒマ人の雑談部屋', 'とにかくヒマな人はここへ。話題はなんでもOK！', true);
createRoom('学生の部屋', '学校のこと、勉強のこと、ゆるく話そう', true);
createRoom('深夜のまったり部屋', '眠れない夜におしゃべりでもどうぞ', true);
createRoom('ゲーム好き集まれ', 'ゲームの話専用。サイコロは「2d6」と発言！', true);

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
  rooms.forEach(function (room) { n += room.members.size; });
  return n;
}

// メンバー0の非公式部屋は一定時間後に削除する
function scheduleRoomCleanup(room) {
  if (room.official) return;
  setTimeout(function () {
    const current = rooms.get(room.id);
    if (current && current.members.size === 0) rooms.delete(room.id);
  }, 60 * 1000);
}

function leaveRoom(session, reasonText) {
  if (!session.roomId) return;
  const room = rooms.get(session.roomId);
  session.roomId = null;
  if (!room) return;
  room.members.delete(session.sid);
  pushLog(room, { type: 'system', text: session.name + ' さんが' + (reasonText || '退室しました') });
  if (room.members.size === 0) scheduleRoomCleanup(room);
}

function joinRoom(session, room) {
  if (session.roomId === room.id) return;
  if (session.roomId) leaveRoom(session, '退室しました');
  session.roomId = room.id;
  session.joinedAt = Date.now();
  room.members.add(session.sid);
  pushLog(room, { type: 'system', text: session.name + ' さんが入室しました' });
}

// 放置ユーザーの自動退室と古いセッションの削除
setInterval(function () {
  const now = Date.now();
  sessions.forEach(function (session, sid) {
    if (session.roomId && now - session.lastSeen > IDLE_TIMEOUT_MS) {
      leaveRoom(session, '退室しました（一定時間操作がなかったため）');
    }
    if (!session.roomId && now - session.lastSeen > SESSION_TTL_MS) {
      sessions.delete(sid);
    }
  });
}, 60 * 1000);

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
    session = {
      sid,
      publicId: crypto.randomBytes(4).toString('hex'),
      name: '名無しさん',
      color: 'black',
      roomId: null,
      userAgent: '',
      joinedAt: 0,
      lastSeen: Date.now(),
    };
    sessions.set(sid, session);
    setCookie(res, 'sid', sid, 60 * 60 * 24);
  }
  return session;
}

// ---- HTMLレンダリング ---------------------------------------------------

const STYLE =
  'body{background-color:#e8e8dc;color:#333333;font-family:"MS PGothic",Osaka,"Hiragino Kaku Gothic ProN",Meiryo,sans-serif;font-size:14px;margin:6px;}' +
  'h1{font-size:19px;margin:4px 0;}' +
  'h2{font-size:15px;margin:8px 0 4px 0;}' +
  'hr{border:0;border-top:1px solid #999988;height:1px;}' +
  'a{color:#0000cc;}' +
  'table{border-collapse:collapse;background-color:#ffffff;}' +
  'th,td{border:1px solid #999988;padding:3px 6px;font-size:13px;text-align:left;}' +
  'th{background-color:#ccccbb;font-weight:bold;}' +
  'input,select{font-size:14px;}' +
  '.box{border:1px solid #999988;background-color:#ffffff;padding:6px;margin:6px 0;}' +
  '.sys{color:#888877;font-size:12px;}' +
  '.dice{color:#775500;}' +
  '.small{font-size:11px;color:#777766;}' +
  '.err{color:#cc0000;font-weight:bold;}' +
  '.ua{word-break:break-all;font-size:12px;}';

function page(title, body) {
  return '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">\n' +
    '<html><head>' +
    '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">' +
    '<meta name="viewport" content="width=device-width">' +
    '<title>' + escapeHtml(title) + '</title>' +
    '<style type="text/css">' + STYLE + '</style>' +
    '</head><body bgcolor="#e8e8dc">' + body + '</body></html>';
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

function logHtml(room) {
  const lines = [];
  const log = room.log;
  for (let i = log.length - 1; i >= 0; i--) {
    const msg = log[i];
    const time = '<span class="small">(' + formatTime(msg.time) + ')</span>';
    if (msg.type === 'system') {
      lines.push('<div class="sys">--- ' + escapeHtml(msg.text) + ' ' + time + ' ---</div>');
    } else if (msg.type === 'dice') {
      lines.push('<div class="dice">★' + nameHtml(msg.name, msg.color) + ' のサイコロ: ' +
        escapeHtml(msg.text) + ' ' + time + '</div>');
    } else {
      lines.push('<div>' + nameHtml(msg.name, msg.color) + '＞ ' + escapeHtml(msg.text) + ' ' + time + '</div>');
    }
  }
  return lines.join('\n');
}

// ---- ルーティング -------------------------------------------------------

// トップ（部屋一覧）
app.get('/', function (req, res) {
  const session = getSession(req);
  const cookies = parseCookies(req);
  const myName = sanitizeText(cookies.name, MAX_NAME_LENGTH) || (session ? session.name : '');
  const myColor = validColor(cookies.color || (session ? session.color : 'black'));

  let errorHtml = '';
  if (req.query.e === 'noroom') errorHtml = '<div class="err">その部屋は見つかりませんでした（削除された可能性があります）</div>';
  if (req.query.e === 'roomname') errorHtml = '<div class="err">部屋の名前を入力してください</div>';
  if (req.query.e === 'roomsmax') errorHtml = '<div class="err">これ以上部屋を作成できません</div>';

  let roomRows = '';
  const sorted = [];
  rooms.forEach(function (room) { sorted.push(room); });
  sorted.sort(function (a, b) {
    return (b.official - a.official) || (b.members.size - a.members.size) || (b.createdAt - a.createdAt);
  });
  for (let i = 0; i < sorted.length; i++) {
    const room = sorted[i];
    roomRows += '<tr>' +
      '<td>' + (room.official ? '★' : '') + escapeHtml(room.name) + '</td>' +
      '<td>' + escapeHtml(room.description) + '</td>' +
      '<td align="right">' + room.members.size + '人</td>' +
      '<td><input type="submit" name="join_' + room.id + '" value="入室"></td>' +
      '</tr>';
  }

  const body =
    '<h1>ヒマチャット風</h1>' +
    '<div class="small">ヒマな人のためのチャット。登録不要・完全無料。</div>' +
    '<div>現在 <b>' + onlineCount() + '</b> 人がチャット中 ／ 部屋数 ' + rooms.size + ' ／ <a href="/">再読込</a></div>' +
    errorHtml +
    '<hr>' +
    '<form method="POST" action="/join">' +
    '<div class="box">' +
    '名前: <input type="text" name="name" size="12" maxlength="' + MAX_NAME_LENGTH + '" value="' + escapeHtml(myName) + '"> ' +
    '名前の色: ' + colorSelectHtml(myColor) +
    '</div>' +
    '<table width="100%">' +
    '<tr><th>部屋名</th><th>説明</th><th>人数</th><th>入室</th></tr>' +
    roomRows +
    '</table>' +
    '</form>' +
    '<hr>' +
    '<h2>■部屋を作る</h2>' +
    '<form method="POST" action="/create">' +
    '<div class="box">' +
    '部屋名: <input type="text" name="roomName" size="16" maxlength="' + MAX_ROOM_NAME_LENGTH + '"><br>' +
    '説明: <input type="text" name="roomDesc" size="24" maxlength="' + MAX_ROOM_DESC_LENGTH + '"><br>' +
    '名前: <input type="text" name="name" size="12" maxlength="' + MAX_NAME_LENGTH + '" value="' + escapeHtml(myName) + '"> ' +
    '名前の色: ' + colorSelectHtml(myColor) + ' ' +
    '<input type="submit" value="作成して入室">' +
    '</div>' +
    '</form>' +
    '<hr>' +
    '<div class="small">※個人情報（本名・住所・連絡先など）は絶対に書き込まないでください。<br>' +
    '※一定時間操作がないと自動退室になります。</div>';

  res.send(page('ヒマチャット風 - 部屋一覧', body));
});

function applyProfile(req, res, session) {
  const name = sanitizeText(req.body.name, MAX_NAME_LENGTH) || '名無しさん';
  const color = validColor(req.body.color);
  session.name = name;
  session.color = color;
  session.userAgent = String(req.headers['user-agent'] || '(不明)').slice(0, 400);
  setCookie(res, 'name', name, 60 * 60 * 24 * 30);
  setCookie(res, 'color', color, 60 * 60 * 24 * 30);
}

// 入室
app.post('/join', function (req, res) {
  let roomId = null;
  for (const key in req.body) {
    if (key.indexOf('join_') === 0) { roomId = key.slice(5); break; }
  }
  const room = roomId ? rooms.get(roomId) : null;
  if (!room) return res.redirect('/?e=noroom');

  const session = ensureSession(req, res);
  applyProfile(req, res, session);
  joinRoom(session, room);
  res.redirect('/room');
});

// 部屋の作成
app.post('/create', function (req, res) {
  const roomName = sanitizeText(req.body.roomName, MAX_ROOM_NAME_LENGTH);
  if (!roomName) return res.redirect('/?e=roomname');
  if (rooms.size >= MAX_ROOMS) return res.redirect('/?e=roomsmax');
  const roomDesc = sanitizeText(req.body.roomDesc, MAX_ROOM_DESC_LENGTH);

  const session = ensureSession(req, res);
  applyProfile(req, res, session);
  const room = createRoom(roomName, roomDesc, false);
  joinRoom(session, room);
  res.redirect('/room');
});

function autoParam(value) {
  const n = parseInt(value, 10);
  return (n === 10 || n === 30) ? n : 0;
}

// チャット画面（1ページ完結・手動更新が基本、希望者のみメタリフレッシュ）
app.get('/room', function (req, res) {
  const session = getSession(req);
  const room = session && session.roomId ? rooms.get(session.roomId) : null;
  if (!session || !room) return res.redirect('/');

  const auto = autoParam(req.query.auto);
  const refreshMeta = auto ?
    '<meta http-equiv="refresh" content="' + auto + ';url=/room?auto=' + auto + '">' : '';

  const autoLinks =
    '自動更新: ' +
    (auto === 0 ? '<b>[OFF]</b>' : '<a href="/room?auto=0">[OFF]</a>') + ' ' +
    (auto === 10 ? '<b>[10秒]</b>' : '<a href="/room?auto=10">[10秒]</a>') + ' ' +
    (auto === 30 ? '<b>[30秒]</b>' : '<a href="/room?auto=30">[30秒]</a>');

  const body =
    refreshMeta +
    '<b>' + (room.official ? '★' : '') + escapeHtml(room.name) + '</b>' +
    ' (' + room.members.size + '人)' +
    ' [<a href="/room/members">参加者一覧</a>]' +
    ' [<a href="/leave">退室</a>]' +
    '<div class="small">' + escapeHtml(room.description) + '</div>' +
    '<hr>' +
    '<form method="POST" action="/room/say">' +
    '<input type="hidden" name="auto" value="' + auto + '">' +
    nameHtml(session.name, session.color) + '＞ ' +
    '<input type="text" name="m" size="24" maxlength="' + MAX_MESSAGE_LENGTH + '"> ' +
    '<input type="submit" value="送信"> ' +
    '[<a href="/room?auto=' + auto + '">更新</a>]' +
    '</form>' +
    '<div class="small">「2d6」「1d100+3」と発言するとサイコロが振れます ／ ' + autoLinks + '</div>' +
    '<hr>' +
    logHtml(room) +
    '<hr>' +
    '[<a href="/room?auto=' + auto + '">更新</a>] [<a href="/leave">退室して部屋一覧へ</a>]';

  res.send(page('ヒマチャット風 - ' + room.name, body));
});

// 発言
app.post('/room/say', function (req, res) {
  const session = getSession(req);
  const room = session && session.roomId ? rooms.get(session.roomId) : null;
  const auto = autoParam(req.body.auto);
  if (!session || !room) return res.redirect('/');

  const text = sanitizeText(req.body.m, MAX_MESSAGE_LENGTH);
  if (text) {
    pushLog(room, { type: 'chat', name: session.name, color: session.color, text });
    const dice = rollDice(text);
    if (dice) {
      pushLog(room, { type: 'dice', name: session.name, color: session.color, text: dice });
    }
  }
  res.redirect('/room?auto=' + auto);
});

// 参加者一覧
app.get('/room/members', function (req, res) {
  const session = getSession(req);
  const room = session && session.roomId ? rooms.get(session.roomId) : null;
  if (!session || !room) return res.redirect('/');

  let memberRows = '';
  room.members.forEach(function (sid) {
    const member = sessions.get(sid);
    if (!member) return;
    memberRows += '<tr>' +
      '<td>' + nameHtml(member.name, member.color) + (member.sid === session.sid ? ' <span class="small">(自分)</span>' : '') + '</td>' +
      '<td>' + formatTime(member.joinedAt) + '</td>' +
      '<td><a href="/room/user?id=' + member.publicId + '">詳細</a></td>' +
      '</tr>';
  });

  const body =
    '<b>' + escapeHtml(room.name) + '</b> の参加者 (' + room.members.size + '人)' +
    '<hr>' +
    '<table width="100%">' +
    '<tr><th>名前</th><th>入室時刻</th><th>詳細</th></tr>' +
    memberRows +
    '</table>' +
    '<hr>' +
    '[<a href="/room">チャットに戻る</a>]';

  res.send(page('ヒマチャット風 - 参加者一覧', body));
});

// ユーザー詳細（ユーザーエージェント表示）
app.get('/room/user', function (req, res) {
  const session = getSession(req);
  const room = session && session.roomId ? rooms.get(session.roomId) : null;
  if (!session || !room) return res.redirect('/');

  let target = null;
  room.members.forEach(function (sid) {
    const member = sessions.get(sid);
    if (member && member.publicId === req.query.id) target = member;
  });
  if (!target) {
    return res.send(page('ヒマチャット風 - ユーザー詳細',
      '<div class="err">そのユーザーは見つかりませんでした（退室した可能性があります）</div>' +
      '<hr>[<a href="/room/members">参加者一覧に戻る</a>]'));
  }

  const body =
    '<b>ユーザー詳細</b>' +
    '<hr>' +
    '<table width="100%">' +
    '<tr><th width="90">名前</th><td>' + nameHtml(target.name, target.color) + '</td></tr>' +
    '<tr><th>名前の色</th><td><font color="' + colorHex(target.color) + '">■</font> ' + colorHex(target.color) + '</td></tr>' +
    '<tr><th>入室時刻</th><td>' + formatTime(target.joinedAt) + '</td></tr>' +
    '<tr><th>最終アクセス</th><td>' + formatTime(target.lastSeen) + '</td></tr>' +
    '<tr><th>ユーザーエージェント</th><td class="ua">' + escapeHtml(target.userAgent || '(不明)') + '</td></tr>' +
    '</table>' +
    '<hr>' +
    '[<a href="/room/members">参加者一覧に戻る</a>] [<a href="/room">チャットに戻る</a>]';

  res.send(page('ヒマチャット風 - ユーザー詳細', body));
});

// 退室
app.get('/leave', function (req, res) {
  const session = getSession(req);
  if (session) leaveRoom(session, '退室しました');
  res.redirect('/');
});

app.listen(PORT, function () {
  console.log('ヒマチャット風サイトが起動しました: http://localhost:' + PORT);
});
