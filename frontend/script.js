/* ============================================================
   My AI - Frontend behaviour (Phase 8: SQLite-backed conversations)

   Conversations live on the server. This file only displays them and
   sends requests. No API key is ever present here.
   ============================================================ */

"use strict";

document.addEventListener("DOMContentLoaded", init);

const els = {
  sidebar: document.getElementById("sidebar"),
  sidebarOverlay: document.getElementById("sidebar-overlay"),
  menuBtn: document.getElementById("menu-btn"),
  sidebarClose: document.getElementById("sidebar-close"),
  newChatBtn: document.getElementById("new-chat-btn"),
  clearBtn: document.getElementById("clear-chat-btn"),
  conversationList: document.getElementById("conversation-list"),
  conversationTitle: document.getElementById("conversation-title"),
  statusText: document.getElementById("status-text"),
  chatArea: document.getElementById("chat-area"),
  messages: document.getElementById("messages"),
  emptyState: document.getElementById("empty-state"),
  suggestions: document.getElementById("suggestions"),
  form: document.getElementById("chat-form"),
  input: document.getElementById("message-input"),
  sendBtn: document.getElementById("send-btn"),
  themeToggle: document.getElementById("theme-toggle"),
  themeIcon: document.getElementById("theme-icon"),
  themeLabel: document.getElementById("theme-label"),
  toast: document.getElementById("toast"),
};

const THEME_KEY = "my-ai-theme";
const HISTORY_LIMIT = 20;

let toastTimer = null;
let isSending = false;
let currentConversationId = null;
let conversationMessages = []; // mirror of the currently displayed messages

/* -------------------- Theme (dark / light) -------------------- */

const MOON_ICON = `
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
       stroke-linecap="round" stroke-linejoin="round">
    <path d="M21 12.8A8.5 8.5 0 1111.2 3a6.6 6.6 0 009.8 9.8z" />
  </svg>`;

const SUN_ICON = `
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
       stroke-linecap="round" stroke-linejoin="round">
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>`;

function preferredTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch (error) {
    // Some browsers block storage. Falling back is fine.
  }
  const systemDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  return systemDark ? "dark" : "light";
}

function applyTheme(theme) {
  const isDark = theme === "dark";
  document.documentElement.dataset.theme = theme;
  els.themeIcon.innerHTML = isDark ? SUN_ICON : MOON_ICON;
  els.themeLabel.textContent = isDark ? "Light mode" : "Dark mode";
  els.themeToggle.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch (error) {
    // Ignore: the theme still works for this visit.
  }
}

/* -------------------- Small helpers -------------------- */

function showToast(message) {
  els.toast.textContent = message;
  els.toast.hidden = false;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    els.toast.hidden = true;
  }, 1800);
}

function scrollToBottom() {
  window.requestAnimationFrame(() => {
    els.chatArea.scrollTop = els.chatArea.scrollHeight;
  });
}

function updateSendButton() {
  els.sendBtn.disabled = isSending || els.input.value.trim().length === 0;
}

function autoResizeInput() {
  els.input.style.height = "auto";
  els.input.style.height = Math.min(els.input.scrollHeight, 160) + "px";
}

function hideEmptyState() {
  els.emptyState.hidden = true;
}

function showEmptyState() {
  els.emptyState.hidden = false;
}

function removeMessages() {
  els.messages.querySelectorAll(".message").forEach((node) => node.remove());
}

function setStatus(text) {
  els.statusText.textContent = text;
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch (error) {
    return "";
  }
}

async function checkBackend() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) return;
    const data = await response.json();
    setStatus(data.configured ? "Connected - My AI is ready" : "Backend ready - add your API key to .env");
  } catch (error) {
    setStatus("Open this page from the Python server (port 8000)");
  }
}

/* -------------------- Conversation sidebar -------------------- */

function renderConversationList(conversations) {
  els.conversationList.innerHTML = "";

  if (!conversations.length) {
    const empty = document.createElement("p");
    empty.className = "empty-history";
    empty.textContent = "No conversations yet. Start a new chat above.";
    els.conversationList.appendChild(empty);
    return;
  }

  conversations.forEach((conversation) => {
    const item = document.createElement("div");
    item.className = "conversation-item";
    if (conversation.id === currentConversationId) item.classList.add("active");

    const open = document.createElement("button");
    open.type = "button";
    open.className = "conversation-open";

    const title = document.createElement("span");
    title.textContent = conversation.title;
    const date = document.createElement("small");
    date.textContent = formatDate(conversation.updated_at);
    open.append(title, date);
    open.addEventListener("click", () => openConversation(conversation.id));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "conversation-delete";
    remove.setAttribute("aria-label", "Delete " + conversation.title);
    remove.title = "Delete conversation";
    remove.textContent = "\u00d7";
    remove.addEventListener("click", () => deleteConversation(conversation.id));

    item.append(open, remove);
    els.conversationList.appendChild(item);
  });
}

async function loadConversations() {
  try {
    const response = await fetch("/api/conversations");
    if (!response.ok) return;
    renderConversationList(await response.json());
  } catch (error) {
    // Keep whatever list is already on screen.
  }
}

async function ensureConversation() {
  if (currentConversationId) return currentConversationId;
  const response = await fetch("/api/conversations", { method: "POST" });
  if (!response.ok) throw new Error("Could not create a conversation.");
  const conversation = await response.json();
  currentConversationId = conversation.id;
  els.conversationTitle.textContent = conversation.title;
  await loadConversations();
  return conversation.id;
}

async function openConversation(id) {
  if (isSending) return;
  try {
    const response = await fetch("/api/conversations/" + id);
    if (!response.ok) {
      showToast("Could not open that conversation");
      return;
    }
    const data = await response.json();
    removeMessages();
    conversationMessages = [];
    currentConversationId = id;
    els.conversationTitle.textContent = data.conversation.title;

    const messages = data.messages || [];
    messages.forEach((message) => {
      addMessage(message.role, message.content);
      conversationMessages.push({ role: message.role, content: message.content });
    });
    if (!messages.length) showEmptyState();

    setStatus(messages.length ? `Loaded ${messages.length} saved messages` : "Empty conversation");
    await loadConversations();
    closeSidebar();
  } catch (error) {
    showToast("Could not open conversation");
  }
}

async function deleteConversation(id) {
  if (isSending) return;
  if (!window.confirm("Delete this conversation permanently?")) return;
  try {
    const response = await fetch("/api/conversations/" + id, { method: "DELETE" });
    if (!response.ok) throw new Error("delete failed");
    showToast("Conversation deleted");
    if (id === currentConversationId) {
      await startNewChat();
    } else {
      await loadConversations();
    }
  } catch (error) {
    showToast("Could not delete conversation");
  }
}

/* -------------------- Creating message bubbles -------------------- */

function makeCopyButton(getText) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "copy-btn";
  button.innerHTML = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
         stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 012-2h8" />
    </svg>
    <span>Copy</span>`;

  button.addEventListener("click", async () => {
    const text = getText();
    if (!text) return;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const helper = document.createElement("textarea");
        helper.value = text;
        helper.style.position = "fixed";
        helper.style.opacity = "0";
        document.body.appendChild(helper);
        helper.select();
        document.execCommand("copy");
        helper.remove();
      }
      button.querySelector("span").textContent = "Copied";
      showToast("Response copied");
      window.setTimeout(() => {
        button.querySelector("span").textContent = "Copy";
      }, 1500);
    } catch (error) {
      showToast("Could not copy. Select the text instead.");
    }
  });

  return button;
}

function addMessage(role, text) {
  hideEmptyState();

  const row = document.createElement("div");
  row.className = "message " + role;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = role === "user" ? "U" : "AI";

  const body = document.createElement("div");
  body.className = "message-body";

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const state = { text: text };
  bubble.textContent = state.text;
  body.appendChild(bubble);

  if (role === "assistant") {
    body.appendChild(makeCopyButton(() => state.text));
  }

  row.append(avatar, body);

  row.setText = (next) => {
    state.text = next;
    bubble.textContent = next;
  };
  row.showTyping = () => {
    bubble.innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';
  };

  els.messages.appendChild(row);
  scrollToBottom();
  return row;
}

function showTypingIndicator() {
  const row = addMessage("assistant", "");
  row.showTyping();
  row.setAttribute("aria-label", "My AI is thinking");
  return row;
}

/* -------------------- Reading streamed replies -------------------- */

function parseSSE(block) {
  const event = { event: "message", data: "" };
  block.split("\n").forEach((line) => {
    if (line.startsWith("event:")) {
      event.event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      event.data += (event.data ? "\n" : "") + line.slice(5).trim();
    }
  });
  return event;
}

async function readStream(response, row) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let full = "";
  let conversationId = null;
  let firstDelta = true;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";

    for (const block of blocks) {
      if (!block.trim()) continue;
      const event = parseSSE(block);
      if (!event.data) continue;

      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        continue;
      }

      if (event.event === "error") {
        throw new Error(payload.message || "The AI service had a problem.");
      }
      if (event.event === "delta" || payload.type === "delta") {
        if (firstDelta) {
          firstDelta = false;
          row.setText("");
        }
        full += payload.text || "";
        row.setText(full);
        scrollToBottom();
      }
      if (event.event === "done" || payload.type === "done") {
        conversationId = payload.conversation_id || null;
      }
    }
  }
  return { text: full, conversationId: conversationId };
}

async function readJsonReply(response) {
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.detail || `Request failed (${response.status}).`);
  }
  if (!data || !data.reply || !data.reply.trim()) {
    throw new Error("The AI returned an empty reply. Please try again.");
  }
  return { text: data.reply.trim(), conversationId: data.conversation_id || null };
}

/* -------------------- Chat actions -------------------- */

async function sendToBackend(text) {
  const payload = {
    message: text,
    conversation_id: currentConversationId,
    model: null,
    // Kept for compatibility; the server now reads history from SQLite.
    history: conversationMessages.slice(0, -1).slice(-HISTORY_LIMIT),
  };

  const options = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  };

  const typing = showTypingIndicator();
  let replyRow = null;

  try {
    let response = await fetch("/api/chat/stream", options);
    let streaming = response.ok && Boolean(response.body);

    if (response.status === 404) {
      response = await fetch("/api/chat", options);
      streaming = false;
    }

    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new Error(data?.detail || `Request failed (${response.status}).`);
    }

    let result;
    if (streaming) {
      typing.remove();
      replyRow = addMessage("assistant", "");
      replyRow.showTyping();
      result = await readStream(response, replyRow);
      if (!result.text.trim()) throw new Error("The AI returned an empty reply. Please try again.");
      replyRow.setText(result.text.trim());
    } else {
      result = await readJsonReply(response);
      typing.remove();
      replyRow = addMessage("assistant", result.text);
    }

    if (result.conversationId) currentConversationId = result.conversationId;
    conversationMessages.push({ role: "assistant", content: result.text });
    setStatus("Saved to conversation history");
    await loadConversations();
  } catch (error) {
    typing.remove();
    if (replyRow) replyRow.remove();
    conversationMessages.pop();
    const message = error instanceof Error ? error.message : "Something went wrong.";
    addMessage("assistant", "Error: " + message);
    setStatus("Could not get a reply");
    showToast("Could not get a reply");
    await loadConversations();
  }
}

async function handleSubmit(event) {
  event.preventDefault();
  if (isSending) return;

  const text = els.input.value.trim();
  if (!text) return;

  isSending = true;
  updateSendButton();

  try {
    await ensureConversation();
  } catch (error) {
    isSending = false;
    updateSendButton();
    addMessage("assistant", "Error: Could not create a conversation. Is the server running?");
    return;
  }

  addMessage("user", text);
  conversationMessages.push({ role: "user", content: text });

  els.input.value = "";
  autoResizeInput();

  if (els.conversationTitle.textContent === "New conversation") {
    els.conversationTitle.textContent = text.length > 42 ? text.slice(0, 42) + "..." : text;
  }

  try {
    await sendToBackend(text);
  } finally {
    isSending = false;
    updateSendButton();
    els.input.focus();
  }
}

async function startNewChat() {
  if (isSending) return;
  removeMessages();
  showEmptyState();
  conversationMessages = [];
  currentConversationId = null;
  els.conversationTitle.textContent = "New conversation";
  els.input.value = "";
  autoResizeInput();
  updateSendButton();
  closeSidebar();

  try {
    await ensureConversation();
    setStatus("New conversation ready");
  } catch (error) {
    setStatus("Could not create a conversation");
  }
  await loadConversations();
  els.input.focus();
}

async function clearCurrentChat() {
  if (isSending) return;
  if (!window.confirm("Clear all messages in this conversation?")) return;

  if (currentConversationId) {
    try {
      await fetch("/api/conversations/" + currentConversationId + "/messages", { method: "DELETE" });
    } catch (error) {
      showToast("Could not clear on the server");
    }
  }
  removeMessages();
  showEmptyState();
  conversationMessages = [];
  setStatus("Conversation cleared");
  await loadConversations();
  els.input.focus();
  showToast("Conversation cleared");
}

/* -------------------- Mobile sidebar -------------------- */

function openSidebar() {
  els.sidebar.classList.add("open");
  els.sidebarOverlay.hidden = false;
  els.menuBtn.setAttribute("aria-expanded", "true");
}

function closeSidebar() {
  els.sidebar.classList.remove("open");
  els.sidebarOverlay.hidden = true;
  els.menuBtn.setAttribute("aria-expanded", "false");
}

/* -------------------- Setup -------------------- */

function init() {
  applyTheme(preferredTheme());
  updateSendButton();
  checkBackend();
  loadConversations();

  els.form.addEventListener("submit", handleSubmit);
  els.input.addEventListener("input", () => {
    autoResizeInput();
    updateSendButton();
  });

  els.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      els.form.requestSubmit();
    }
  });

  els.newChatBtn.addEventListener("click", startNewChat);
  els.clearBtn.addEventListener("click", clearCurrentChat);
  els.themeToggle.addEventListener("click", toggleTheme);
  els.menuBtn.addEventListener("click", openSidebar);
  els.sidebarClose.addEventListener("click", closeSidebar);
  els.sidebarOverlay.addEventListener("click", closeSidebar);

  els.suggestions.querySelectorAll(".suggestion").forEach((button) => {
    button.addEventListener("click", () => {
      els.input.value = button.dataset.prompt || "";
      autoResizeInput();
      updateSendButton();
      els.input.focus();
    });
  });
}
