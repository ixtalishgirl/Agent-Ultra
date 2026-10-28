/* Agent-Ultra chat UI logic. No demo chats, no fake content: the list,
   messages, and browser events all come from the server API. Agent
   replies come from the server's model loop (real model reply when
   MODEL_API_URL is configured, honest not-live message otherwise) —
   never invented here. The browser panel shows the live screenshot
   of a model-opened browser session, or the honest no-session state. */
(function () {
  var currentChatId = null;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function api(path, method, body) {
    return fetch(path, {
      method: method || "GET",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, status: r.status, data: j }; });
    });
  }

  function renderChatList(chats) {
    var list = document.getElementById("chat-list");
    if (!chats.length) {
      list.innerHTML = '<li class="empty" style="padding:10px">No chats yet — create one above.</li>';
      return;
    }
    list.innerHTML = "";
    chats.forEach(function (c) {
      var row = document.createElement("li");
      row.className = "chat-row" + (c.chat_id === currentChatId ? " active" : "");
      var title = document.createElement("span");
      title.className = "title";
      title.textContent = c.title || c.chat_id;
      title.addEventListener("click", function () { selectChat(c.chat_id); });
      // Per-chat delete icon: visible on every row, deletes only this chat.
      var del = document.createElement("button");
      del.className = "chat-delete";
      del.type = "button";
      del.textContent = "×";
      del.title = "Delete this chat";
      del.setAttribute("aria-label", "Delete chat " + (c.title || c.chat_id));
      del.addEventListener("click", function (e) {
        e.stopPropagation();
        api("/api/chats/" + c.chat_id, "DELETE").then(function () {
          if (currentChatId === c.chat_id) {
            currentChatId = null;
            stopScreenshotPoll();
            document.getElementById("chat-title").textContent = "No chat selected";
            document.getElementById("messages").innerHTML =
              '<p class="empty">Select a chat, or create a new one to start.</p>';
            document.getElementById("browser-events").innerHTML =
              '<p class="empty">No browser events yet.</p>';
          }
          loadChats();
        });
      });
      row.appendChild(title);
      row.appendChild(del);
      list.appendChild(row);
    });
  }

  function loadChats() {
    return api("/api/chats").then(function (res) {
      if (res.ok) renderChatList(res.data.chats || []);
    });
  }

  function renderMessages(messages) {
    var box = document.getElementById("messages");
    if (!messages.length) {
      box.innerHTML = '<p class="empty">No messages yet. Type below to start.</p>';
      return;
    }
    box.innerHTML = "";
    messages.forEach(function (m) {
      var div = document.createElement("div");
      div.className = "msg " + (m.role === "user" ? "user" : "agent");
      var meta = document.createElement("span");
      meta.className = "meta";
      meta.textContent = m.role + " · " + new Date(m.ts * 1000).toLocaleTimeString();
      div.appendChild(meta);
      div.appendChild(document.createTextNode(m.text));
      box.appendChild(div);
    });
  }

  function renderBrowserEvents(events) {
    var box = document.getElementById("browser-events");
    var status = document.getElementById("browser-status");
    if (!events.length) {
      box.innerHTML = '<p class="empty">No browser events yet. The model opens the browser on its own when it decides to — its real events appear here.</p>';
      status.textContent = "idle";
      status.className = "browser-status";
      return;
    }
    box.innerHTML = "";
    events.forEach(function (ev) {
      var div = document.createElement("div");
      div.className = "browser-event";
      div.textContent = JSON.stringify(ev, null, 2);
      box.appendChild(div);
    });
    var last = events[events.length - 1];
    status.textContent = last.status || "";
    status.className = "browser-status" + (last.status === "UNTESTED" ? " untested" : "");
  }

  // Live screen: poll the screenshot endpoint while a chat is
  // selected. A live session returns real PNG bytes; no session
  // returns an error, shown as the honest no-session state — never a
  // placeholder image.
  var screenshotTimer = null;
  var screenshotObjectUrl = null;

  function showNoSession() {
    var img = document.getElementById("browser-screenshot");
    var note = document.getElementById("browser-nosession");
    if (screenshotObjectUrl) {
      URL.revokeObjectURL(screenshotObjectUrl);
      screenshotObjectUrl = null;
    }
    img.classList.add("hidden");
    img.removeAttribute("src");
    note.classList.remove("hidden");
  }

  function refreshScreenshot() {
    if (!currentChatId) return;
    fetch("/api/chats/" + currentChatId + "/browser/screenshot")
      .then(function (r) {
        if (!r.ok) { showNoSession(); return null; }
        return r.blob();
      })
      .then(function (blob) {
        if (!blob) return;
        var img = document.getElementById("browser-screenshot");
        var note = document.getElementById("browser-nosession");
        if (screenshotObjectUrl) URL.revokeObjectURL(screenshotObjectUrl);
        screenshotObjectUrl = URL.createObjectURL(blob);
        img.src = screenshotObjectUrl;
        img.classList.remove("hidden");
        note.classList.add("hidden");
      })
      .catch(function () { showNoSession(); });
  }

  function startScreenshotPoll() {
    if (screenshotTimer) clearInterval(screenshotTimer);
    refreshScreenshot();
    screenshotTimer = setInterval(refreshScreenshot, 2000);
  }

  function stopScreenshotPoll() {
    if (screenshotTimer) { clearInterval(screenshotTimer); screenshotTimer = null; }
    showNoSession();
  }

  function selectChat(chatId) {
    currentChatId = chatId;
    api("/api/chats/" + chatId).then(function (res) {
      if (!res.ok) return;
      document.getElementById("chat-title").textContent = res.data.meta.title || chatId;
      renderMessages(res.data.messages || []);
      loadChats();
    });
    api("/api/chats/" + chatId + "/browser/events").then(function (res) {
      if (res.ok) renderBrowserEvents(res.data.events || []);
    });
    startScreenshotPoll();
  }

  document.getElementById("new-chat").addEventListener("click", function () {
    api("/api/chats", "POST", {}).then(function (res) {
      if (res.ok) selectChat(res.data.chat_id);
    });
  });

  document.getElementById("toggle-browser").addEventListener("click", function () {
    document.getElementById("browser-panel").classList.toggle("hidden");
  });

  document.getElementById("browser-open").addEventListener("click", function () {
    if (!currentChatId) {
      alert("Create or select a chat first.");
      return;
    }
    var url = document.getElementById("browser-url").value.trim();
    if (!url) return;
    api("/api/chats/" + currentChatId + "/browser/open", "POST", { url: url }).then(function (res) {
      if (res.ok) {
        renderBrowserEvents(res.data.events || []);
      } else {
        renderBrowserEvents([{ type: "browser.open_failed", status: "error", detail: (res.data && res.data.detail) || "request failed" }]);
      }
    });
  });

  document.getElementById("composer").addEventListener("submit", function (e) {
    e.preventDefault();
    if (!currentChatId) {
      alert("Create or select a chat first.");
      return;
    }
    var input = document.getElementById("composer-input");
    var text = input.value.trim();
    if (!text) return;
    input.value = "";
    // The server runs the model loop and appends the real agent
    // message (model reply, or the honest not-live message) — the
    // reloaded chat shows it, so nothing is invented here.
    api("/api/chats/" + currentChatId + "/messages", "POST", { role: "user", text: text }).then(function () {
      selectChat(currentChatId);
    });
  });

  // Tool chips: what the agent knows, with REAL / UNTESTED status.
  api("/api/tools").then(function (res) {
    if (!res.ok) return;
    var chips = document.getElementById("tool-chips");
    Object.keys(res.data.tools || {}).forEach(function (name) {
      var t = res.data.tools[name];
      var chip = document.createElement("span");
      chip.className = "tool-chip" + (t.status === "UNTESTED" ? " untested" : "");
      chip.textContent = name + " · " + t.status;
      chips.appendChild(chip);
    });
  });

  loadChats();
})();
