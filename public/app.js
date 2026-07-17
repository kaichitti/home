'use strict';

const socket = io();

// ---- 画面要素 -----------------------------------------------------------

const screens = {
  top: document.getElementById('top-screen'),
  waiting: document.getElementById('waiting-screen'),
  chat: document.getElementById('chat-screen'),
};

const joinForm = document.getElementById('join-form');
const nicknameInput = document.getElementById('nickname-input');
const topOnlineCount = document.getElementById('top-online-count');
const chatOnlineCount = document.getElementById('chat-online-count');
const cancelWaitingBtn = document.getElementById('cancel-waiting');

const partnerNameEl = document.getElementById('partner-name');
const typingIndicator = document.getElementById('typing-indicator');
const messagesEl = document.getElementById('messages');
const messageForm = document.getElementById('message-form');
const messageInput = document.getElementById('message-input');
const nextPartnerBtn = document.getElementById('next-partner');
const leaveChatBtn = document.getElementById('leave-chat');
const randomQuestionBtn = document.getElementById('random-question');

let myName = '';
let typingTimer = null;
let isTypingSent = false;

// ---- 画面切り替え -------------------------------------------------------

function showScreen(name) {
  Object.values(screens).forEach((el) => el.classList.remove('active'));
  screens[name].classList.add('active');
}

// ---- メッセージ描画 -----------------------------------------------------

function appendMessage(text, type) {
  const div = document.createElement('div');
  div.className = `message ${type}`;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function clearMessages() {
  messagesEl.innerHTML = '';
}

// ---- トップ画面 ---------------------------------------------------------

joinForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const name = nicknameInput.value.trim();
  if (!name) return;
  myName = name;
  socket.emit('join', { name: myName });
  showScreen('waiting');
});

cancelWaitingBtn.addEventListener('click', () => {
  socket.emit('leave');
  showScreen('top');
});

// ---- チャット画面 -------------------------------------------------------

messageForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = messageInput.value.trim();
  if (!text) return;
  socket.emit('chat message', { text });
  appendMessage(text, 'me');
  messageInput.value = '';
  stopTyping();
  messageInput.focus();
});

messageInput.addEventListener('input', () => {
  if (!isTypingSent) {
    socket.emit('typing', true);
    isTypingSent = true;
  }
  clearTimeout(typingTimer);
  typingTimer = setTimeout(stopTyping, 1500);
});

function stopTyping() {
  clearTimeout(typingTimer);
  if (isTypingSent) {
    socket.emit('typing', false);
    isTypingSent = false;
  }
}

nextPartnerBtn.addEventListener('click', () => {
  socket.emit('next partner');
  showScreen('waiting');
});

leaveChatBtn.addEventListener('click', () => {
  socket.emit('leave');
  showScreen('top');
});

randomQuestionBtn.addEventListener('click', () => {
  socket.emit('random question');
});

// ---- Socket.IO イベント -------------------------------------------------

socket.on('waiting', () => {
  showScreen('waiting');
});

socket.on('matched', ({ partnerName }) => {
  clearMessages();
  partnerNameEl.textContent = partnerName;
  typingIndicator.textContent = '';
  showScreen('chat');
  appendMessage(`${partnerName} さんとつながりました！あいさつしてみよう 👋`, 'system');
  messageInput.focus();
});

socket.on('chat message', ({ text }) => {
  appendMessage(text, 'partner');
  typingIndicator.textContent = '';
});

socket.on('typing', (isTyping) => {
  typingIndicator.textContent = isTyping ? '入力中…' : '';
});

socket.on('random question', ({ question }) => {
  appendMessage(`🎲 ランダム質問: ${question}`, 'question');
});

socket.on('partner left', () => {
  appendMessage('相手が退出しました。「次の相手へ」で新しい相手を探せます。', 'system');
  typingIndicator.textContent = '';
});

socket.on('online count', (count) => {
  topOnlineCount.textContent = count;
  chatOnlineCount.textContent = count;
});

socket.on('disconnect', () => {
  if (screens.chat.classList.contains('active') || screens.waiting.classList.contains('active')) {
    showScreen('top');
  }
});
