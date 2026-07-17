'use strict';

const socket = io();

// ---- 画面要素 -----------------------------------------------------------

const lobbyScreen = document.getElementById('lobby-screen');
const chatScreen = document.getElementById('chat-screen');

const onlineCountEl = document.getElementById('online-count');
const nicknameInput = document.getElementById('nickname-input');
const roomListEl = document.getElementById('room-list');

const showCreateRoomBtn = document.getElementById('show-create-room');
const createRoomForm = document.getElementById('create-room-form');
const roomNameInput = document.getElementById('room-name-input');
const roomDescInput = document.getElementById('room-desc-input');
const cancelCreateRoomBtn = document.getElementById('cancel-create-room');

const roomTitleEl = document.getElementById('room-title');
const roomDescEl = document.getElementById('room-desc');
const leaveRoomBtn = document.getElementById('leave-room');
const toggleMembersBtn = document.getElementById('toggle-members');
const memberCountEl = document.getElementById('member-count');
const memberPanel = document.getElementById('member-panel');
const memberListEl = document.getElementById('member-list');

const messagesEl = document.getElementById('messages');
const messageForm = document.getElementById('message-form');
const messageInput = document.getElementById('message-input');
const toastEl = document.getElementById('toast');

let selfId = null;
let inRoom = false;

// 前回のニックネームを復元
nicknameInput.value = localStorage.getItem('himachat-name') || '';

// ---- ユーティリティ -----------------------------------------------------

function showScreen(screen) {
  lobbyScreen.classList.remove('active');
  chatScreen.classList.remove('active');
  screen.classList.add('active');
}

function getName() {
  const name = nicknameInput.value.trim();
  if (!name) {
    showToast('先にニックネームを入力してください');
    nicknameInput.focus();
    return null;
  }
  localStorage.setItem('himachat-name', name);
  return name;
}

let toastTimer = null;
function showToast(text) {
  toastEl.textContent = text;
  toastEl.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.add('hidden'), 2500);
}

function formatTime(ts) {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

// ---- 部屋一覧 -----------------------------------------------------------

function renderRoomList(roomsData) {
  roomListEl.innerHTML = '';
  if (roomsData.length === 0) {
    const li = document.createElement('li');
    li.className = 'room-empty';
    li.textContent = 'まだ部屋がありません。最初の部屋を作ってみよう！';
    roomListEl.appendChild(li);
    return;
  }
  for (const room of roomsData) {
    const li = document.createElement('li');
    li.className = 'room-item';

    const info = document.createElement('div');
    info.className = 'room-item-info';

    const nameEl = document.createElement('div');
    nameEl.className = 'room-item-name';
    nameEl.textContent = (room.official ? '⭐ ' : '') + room.name;

    const descEl = document.createElement('div');
    descEl.className = 'room-item-desc';
    descEl.textContent = room.description || '';

    info.appendChild(nameEl);
    if (room.description) info.appendChild(descEl);

    const meta = document.createElement('div');
    meta.className = 'room-item-meta';

    const count = document.createElement('span');
    count.className = 'room-item-count';
    count.textContent = `👥 ${room.memberCount}人`;

    const joinBtn = document.createElement('button');
    joinBtn.className = 'btn btn-primary btn-small-pad';
    joinBtn.textContent = '入室';
    joinBtn.addEventListener('click', () => {
      const name = getName();
      if (!name) return;
      socket.emit('join room', { roomId: room.id, userName: name });
    });

    meta.appendChild(count);
    meta.appendChild(joinBtn);
    li.appendChild(info);
    li.appendChild(meta);
    roomListEl.appendChild(li);
  }
}

// ---- 部屋作成 -----------------------------------------------------------

showCreateRoomBtn.addEventListener('click', () => {
  createRoomForm.classList.toggle('hidden');
  if (!createRoomForm.classList.contains('hidden')) roomNameInput.focus();
});

cancelCreateRoomBtn.addEventListener('click', () => {
  createRoomForm.classList.add('hidden');
});

createRoomForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const name = getName();
  if (!name) return;
  const roomName = roomNameInput.value.trim();
  if (!roomName) return;
  socket.emit('create room', {
    roomName,
    description: roomDescInput.value.trim(),
    userName: name,
  });
});

// ---- メッセージ描画 -----------------------------------------------------

function appendMessage(msg) {
  const div = document.createElement('div');

  if (msg.type === 'system') {
    div.className = 'message system';
    div.textContent = msg.text;
  } else if (msg.type === 'dice') {
    div.className = 'message dice';
    div.textContent = msg.text;
  } else {
    const isMe = msg.senderId && msg.senderId === selfId;
    div.className = `message ${isMe ? 'me' : 'other'}`;

    const meta = document.createElement('div');
    meta.className = 'message-meta';
    meta.textContent = `${msg.name} ・ ${formatTime(msg.time)}`;

    const body = document.createElement('div');
    body.className = 'message-body';
    body.textContent = msg.text;

    div.appendChild(meta);
    div.appendChild(body);
  }

  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function renderMembers(members) {
  memberCountEl.textContent = members.length;
  memberListEl.innerHTML = '';
  for (const name of members) {
    const li = document.createElement('li');
    li.textContent = `🙂 ${name}`;
    memberListEl.appendChild(li);
  }
}

// ---- チャット画面の操作 -------------------------------------------------

messageForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = messageInput.value.trim();
  if (!text) return;
  socket.emit('chat message', { text });
  messageInput.value = '';
  messageInput.focus();
});

leaveRoomBtn.addEventListener('click', () => {
  socket.emit('leave room');
  inRoom = false;
  showScreen(lobbyScreen);
});

toggleMembersBtn.addEventListener('click', () => {
  memberPanel.classList.toggle('hidden');
});

// ---- Socket.IO イベント -------------------------------------------------

socket.on('room list', (roomsData) => {
  renderRoomList(roomsData);
});

socket.on('online count', (count) => {
  onlineCountEl.textContent = count;
});

socket.on('joined room', ({ room, members, log, selfId: id }) => {
  selfId = id;
  inRoom = true;
  roomTitleEl.textContent = (room.official ? '⭐ ' : '') + room.name;
  roomDescEl.textContent = room.description || '';
  messagesEl.innerHTML = '';
  for (const msg of log) appendMessage(msg);
  renderMembers(members);
  memberPanel.classList.add('hidden');
  createRoomForm.classList.add('hidden');
  roomNameInput.value = '';
  roomDescInput.value = '';
  showScreen(chatScreen);
  messageInput.focus();
});

socket.on('room message', (msg) => {
  if (!inRoom) return;
  appendMessage(msg);
});

socket.on('member list', (members) => {
  renderMembers(members);
});

socket.on('error message', (text) => {
  showToast(text);
});

socket.on('disconnect', () => {
  if (inRoom) {
    inRoom = false;
    showScreen(lobbyScreen);
    showToast('サーバーとの接続が切れました。再接続します…');
  }
});
