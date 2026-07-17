'use strict';

const path = require('path');
const express = require('express');
const http = require('http');
const { Server } = require('socket.io');

const app = express();
const server = http.createServer(app);
const io = new Server(server);

const PORT = process.env.PORT || 3000;

app.use(express.static(path.join(__dirname, 'public')));

// ---- マッチング管理 ----------------------------------------------------

// 相手を待っているソケットのキュー
const waitingQueue = [];

// socket.id -> { name, partnerId }
const users = new Map();

const MAX_NAME_LENGTH = 20;
const MAX_MESSAGE_LENGTH = 500;

// 会話のきっかけになるランダム質問
const RANDOM_QUESTIONS = [
  '最近ハマっていることは何ですか？',
  '好きな食べ物は何ですか？',
  '休みの日は何をして過ごしますか？',
  'もし宝くじで1億円当たったら何に使いますか？',
  '最近観た映画やドラマでおすすめはありますか？',
  '朝型ですか？夜型ですか？',
  '行ってみたい場所はどこですか？',
  '子どもの頃の夢は何でしたか？',
  '犬派ですか？猫派ですか？',
  '最近うれしかったことは何ですか？',
  '好きな音楽やアーティストはいますか？',
  '得意料理はありますか？',
  'タイムマシンがあったら過去と未来どちらに行きますか？',
  '無人島に一つだけ持っていくなら何にしますか？',
  '最近買ってよかったものは何ですか？',
  '今いちばん食べたいものは何ですか？',
  '学生時代の部活やサークルは何でしたか？',
  '超能力が一つ使えるなら何がいいですか？',
  '座右の銘や好きな言葉はありますか？',
  '明日から連休だったら何をしますか？',
];

function sanitizeText(text, maxLength) {
  if (typeof text !== 'string') return '';
  return text.replace(/[\u0000-\u001F\u007F]/g, '').trim().slice(0, maxLength);
}

function broadcastOnlineCount() {
  io.emit('online count', users.size);
}

function removeFromQueue(socketId) {
  const index = waitingQueue.indexOf(socketId);
  if (index !== -1) waitingQueue.splice(index, 1);
}

function findPartner(socket) {
  // キューの先頭から生きている待機者を探す
  while (waitingQueue.length > 0) {
    const candidateId = waitingQueue.shift();
    if (candidateId === socket.id) continue;
    const candidateSocket = io.sockets.sockets.get(candidateId);
    const candidate = users.get(candidateId);
    if (!candidateSocket || !candidate || candidate.partnerId) continue;

    const me = users.get(socket.id);
    me.partnerId = candidateId;
    candidate.partnerId = socket.id;

    socket.emit('matched', { partnerName: candidate.name });
    candidateSocket.emit('matched', { partnerName: me.name });
    return;
  }

  // 相手がいなければ自分がキューに入る
  waitingQueue.push(socket.id);
  socket.emit('waiting');
}

function leaveChat(socket, { notifyPartner = true } = {}) {
  const me = users.get(socket.id);
  if (!me) return;

  removeFromQueue(socket.id);

  if (me.partnerId) {
    const partner = users.get(me.partnerId);
    const partnerSocket = io.sockets.sockets.get(me.partnerId);
    if (partner) partner.partnerId = null;
    if (notifyPartner && partnerSocket) {
      partnerSocket.emit('partner left');
    }
    me.partnerId = null;
  }
}

// ---- Socket.IO ハンドラ -------------------------------------------------

io.on('connection', (socket) => {
  // 接続直後に現在のオンライン人数を通知する
  socket.emit('online count', users.size);

  socket.on('join', (payload) => {
    const name = sanitizeText(payload && payload.name, MAX_NAME_LENGTH) || '名無しさん';
    if (users.has(socket.id)) return;
    users.set(socket.id, { name, partnerId: null });
    broadcastOnlineCount();
    findPartner(socket);
  });

  socket.on('chat message', (payload) => {
    const me = users.get(socket.id);
    if (!me || !me.partnerId) return;
    const text = sanitizeText(payload && payload.text, MAX_MESSAGE_LENGTH);
    if (!text) return;
    const partnerSocket = io.sockets.sockets.get(me.partnerId);
    if (partnerSocket) {
      partnerSocket.emit('chat message', { text, name: me.name });
    }
  });

  socket.on('typing', (isTyping) => {
    const me = users.get(socket.id);
    if (!me || !me.partnerId) return;
    const partnerSocket = io.sockets.sockets.get(me.partnerId);
    if (partnerSocket) {
      partnerSocket.emit('typing', Boolean(isTyping));
    }
  });

  socket.on('random question', () => {
    const me = users.get(socket.id);
    if (!me || !me.partnerId) return;
    const question = RANDOM_QUESTIONS[Math.floor(Math.random() * RANDOM_QUESTIONS.length)];
    const partnerSocket = io.sockets.sockets.get(me.partnerId);
    socket.emit('random question', { question });
    if (partnerSocket) {
      partnerSocket.emit('random question', { question });
    }
  });

  // 「次の相手を探す」: 今の会話を抜けて再マッチング
  socket.on('next partner', () => {
    const me = users.get(socket.id);
    if (!me) return;
    leaveChat(socket);
    findPartner(socket);
  });

  // トップページに戻る
  socket.on('leave', () => {
    leaveChat(socket);
    users.delete(socket.id);
    broadcastOnlineCount();
  });

  socket.on('disconnect', () => {
    leaveChat(socket);
    users.delete(socket.id);
    broadcastOnlineCount();
  });
});

server.listen(PORT, () => {
  console.log(`ヒマチャット風サイトが起動しました: http://localhost:${PORT}`);
});
