'use strict';

const path = require('path');
const express = require('express');
const http = require('http');
const crypto = require('crypto');
const { Server } = require('socket.io');

const app = express();
const server = http.createServer(app);
const io = new Server(server);

const PORT = process.env.PORT || 3000;

app.use(express.static(path.join(__dirname, 'public')));

// ---- 定数 ---------------------------------------------------------------

const MAX_NAME_LENGTH = 20;
const MAX_MESSAGE_LENGTH = 500;
const MAX_ROOM_NAME_LENGTH = 30;
const MAX_ROOM_DESC_LENGTH = 60;
const MAX_LOG_PER_ROOM = 100;
const MAX_ROOMS = 200;

// サイコロコマンド: 「2d6」「1d100+3」のような発言でダイスを振る
const DICE_PATTERN = /^(\d{1,2})[dD](\d{1,4})([+-]\d{1,4})?$/;

// ---- 状態管理 -----------------------------------------------------------

// roomId -> { id, name, description, official, createdAt, members: Map(socketId -> name), log: [] }
const rooms = new Map();

// socket.id -> { name, roomId }
const users = new Map();

function createRoom(name, description, { official = false } = {}) {
  const id = crypto.randomBytes(6).toString('hex');
  const room = {
    id,
    name,
    description,
    official,
    createdAt: Date.now(),
    members: new Map(),
    log: [],
  };
  rooms.set(id, room);
  return room;
}

// 最初から入れる公式部屋
createRoom('ヒマ人の雑談部屋', 'とにかくヒマな人はここへ。話題はなんでもOK！', { official: true });
createRoom('学生の部屋', '学校のこと、勉強のこと、ゆるく話そう', { official: true });
createRoom('深夜のまったり部屋', '眠れない夜におしゃべりでもどうぞ', { official: true });
createRoom('ゲーム好き集まれ', 'ゲームの話専用。サイコロは「2d6」と発言！', { official: true });

// ---- ユーティリティ -----------------------------------------------------

function sanitizeText(text, maxLength) {
  if (typeof text !== 'string') return '';
  return text.replace(/[\u0000-\u001F\u007F]/g, '').trim().slice(0, maxLength);
}

function roomSummary(room) {
  return {
    id: room.id,
    name: room.name,
    description: room.description,
    official: room.official,
    memberCount: room.members.size,
  };
}

function roomListPayload() {
  // 公式部屋を先頭に、あとは人数が多い順
  return [...rooms.values()]
    .sort((a, b) => (b.official - a.official) || (b.members.size - a.members.size) || (b.createdAt - a.createdAt))
    .map(roomSummary);
}

function broadcastRoomList() {
  io.emit('room list', roomListPayload());
}

function broadcastOnlineCount() {
  io.emit('online count', io.sockets.sockets.size);
}

function pushLog(room, entry) {
  const message = { ...entry, time: Date.now() };
  room.log.push(message);
  if (room.log.length > MAX_LOG_PER_ROOM) room.log.shift();
  return message;
}

// メンバー0の非公式部屋は一定時間後に削除する
function scheduleRoomCleanup(room) {
  if (room.official) return;
  setTimeout(() => {
    const current = rooms.get(room.id);
    if (current && current.members.size === 0) {
      rooms.delete(room.id);
      broadcastRoomList();
    }
  }, 60 * 1000);
}

// サイコロ発言なら結果文字列を返す（違えば null）
function rollDice(text) {
  const match = DICE_PATTERN.exec(text);
  if (!match) return null;
  const count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? parseInt(match[3], 10) : 0;
  if (count < 1 || count > 20 || sides < 2 || sides > 1000) return null;
  const roll = () => 1 + Math.floor(Math.random() * sides);
  const values = Array.from({ length: count }, roll);
  const total = values.reduce((a, b) => a + b, 0) + modifier;
  const detail = values.join(', ') + (modifier ? ` (${match[3]})` : '');
  return `🎲 ${text} → [${detail}] = ${total}`;
}

function leaveRoom(socket) {
  const user = users.get(socket.id);
  if (!user || !user.roomId) return;
  const room = rooms.get(user.roomId);
  user.roomId = null;
  if (!room) return;

  room.members.delete(socket.id);
  socket.leave(room.id);

  const message = pushLog(room, { type: 'system', text: `${user.name} さんが退室しました` });
  io.to(room.id).emit('room message', message);
  io.to(room.id).emit('member list', [...room.members.values()]);

  if (room.members.size === 0) scheduleRoomCleanup(room);
  broadcastRoomList();
}

// ---- Socket.IO ハンドラ -------------------------------------------------

io.on('connection', (socket) => {
  users.set(socket.id, { name: '', roomId: null });

  // 接続直後に部屋一覧とオンライン人数を送る
  socket.emit('room list', roomListPayload());
  broadcastOnlineCount();

  // 部屋を作成してそのまま入室する
  socket.on('create room', (payload) => {
    const name = sanitizeText(payload && payload.roomName, MAX_ROOM_NAME_LENGTH);
    const description = sanitizeText(payload && payload.description, MAX_ROOM_DESC_LENGTH);
    const userName = sanitizeText(payload && payload.userName, MAX_NAME_LENGTH) || '名無しさん';
    if (!name) {
      socket.emit('error message', '部屋の名前を入力してください');
      return;
    }
    if (rooms.size >= MAX_ROOMS) {
      socket.emit('error message', 'これ以上部屋を作成できません');
      return;
    }
    const room = createRoom(name, description);
    joinRoom(socket, room, userName);
  });

  socket.on('join room', (payload) => {
    const roomId = payload && payload.roomId;
    const userName = sanitizeText(payload && payload.userName, MAX_NAME_LENGTH) || '名無しさん';
    const room = rooms.get(roomId);
    if (!room) {
      socket.emit('error message', 'その部屋は見つかりませんでした（削除された可能性があります）');
      socket.emit('room list', roomListPayload());
      return;
    }
    joinRoom(socket, room, userName);
  });

  socket.on('chat message', (payload) => {
    const user = users.get(socket.id);
    if (!user || !user.roomId) return;
    const room = rooms.get(user.roomId);
    if (!room) return;
    const text = sanitizeText(payload && payload.text, MAX_MESSAGE_LENGTH);
    if (!text) return;

    const message = pushLog(room, { type: 'chat', name: user.name, text, senderId: socket.id });
    io.to(room.id).emit('room message', message);

    // サイコロコマンドなら結果も流す
    const dice = rollDice(text);
    if (dice) {
      const diceMessage = pushLog(room, { type: 'dice', name: user.name, text: dice });
      io.to(room.id).emit('room message', diceMessage);
    }
  });

  socket.on('leave room', () => {
    leaveRoom(socket);
  });

  socket.on('disconnect', () => {
    leaveRoom(socket);
    users.delete(socket.id);
    broadcastOnlineCount();
  });
});

function joinRoom(socket, room, userName) {
  const user = users.get(socket.id);
  if (!user) return;

  // 別の部屋にいたら先に退室
  if (user.roomId) leaveRoom(socket);

  user.name = userName;
  user.roomId = room.id;
  room.members.set(socket.id, userName);
  socket.join(room.id);

  // 入室者には部屋情報と直近ログを送る
  socket.emit('joined room', {
    room: roomSummary(room),
    members: [...room.members.values()],
    log: room.log,
    selfId: socket.id,
  });

  const message = pushLog(room, { type: 'system', text: `${userName} さんが入室しました` });
  io.to(room.id).emit('room message', message);
  io.to(room.id).emit('member list', [...room.members.values()]);
  broadcastRoomList();
}

server.listen(PORT, () => {
  console.log(`ヒマチャット風サイトが起動しました: http://localhost:${PORT}`);
});
