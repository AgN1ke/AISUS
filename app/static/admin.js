/* Smartest unified front-end behaviours.
   Three self-contained modules, each gated by a root element so the same file
   can be loaded on dashboard, logs, and portal-landing pages without conflict.
   Page-specific data is passed via window.SmartestData / window.SmartestModels
   / window.SmartestTelegram set in a tiny inline <script> before this file.
*/
(function () {
  // ---------- Dashboard (config page) ----------
  function initDashboard() {
    var MODELS = window.SmartestModels;
    if (!MODELS) return;
    if (!document.querySelector(".cap-card")) return;

    document.querySelectorAll("[data-toggle-secret]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var inp =
          (btn.closest(".prov-key-row, .field-control") || btn.parentElement)
            .querySelector("input");
        if (!inp) return;
        inp.type = inp.type === "password" ? "text" : "password";
      });
    });

    var advToggle = document.getElementById("adv-toggle");
    if (advToggle) {
      advToggle.addEventListener("click", function () {
        var body = document.getElementById("adv-body");
        if (body) body.classList.toggle("open");
      });
    }

    document.querySelectorAll(".ck-check").forEach(function (cb) {
      cb.addEventListener("change", function () {
        var f = document.querySelector('.ck-field[data-cap="' + cb.dataset.cap + '"]');
        if (!f) return;
        f.style.display = cb.checked ? "" : "none";
        if (!cb.checked) {
          var i = f.querySelector("input");
          if (i) i.value = "";
        }
      });
    });

    function activeProviders() {
      var s = new Set();
      document.querySelectorAll(".prov-key-input").forEach(function (i) {
        if (i.value.trim()) s.add(i.dataset.provider);
      });
      return s;
    }

    function refreshProviderDropdowns() {
      var active = activeProviders();
      document.querySelectorAll(".cap-provider").forEach(function (sel) {
        var cur = sel.value;
        Array.from(sel.options).forEach(function (opt) {
          opt.disabled = !active.has(opt.value) && opt.value !== cur;
          opt.textContent = opt.textContent.replace(/ \(немає ключа\)$/, "");
          if (opt.disabled && opt.value !== cur) opt.textContent += " (немає ключа)";
        });
      });
    }

    function refreshModels(sel) {
      var card = sel.closest(".cap-card");
      if (!card) return;
      var mt = card.dataset.modelType;
      var prov = sel.value;
      var modelEl = card.querySelector(".cap-model");
      var adapterEl = card.querySelector(".cap-adapter");
      if (adapterEl) {
        adapterEl.value =
          prov === "gemini"
            ? "gemini_generate_content"
            : mt === "vision"
            ? "openai_vision"
            : "openai_chat";
      }
      var opts = (MODELS[mt] || MODELS["text"] || {})[prov] || [];
      var prev = modelEl.value;
      modelEl.innerHTML = "";
      opts.forEach(function (m) {
        modelEl.add(new Option(m, m, false, m === prev));
      });
      refreshReasoning(card);
    }

    function reasoningSupportedFor(provider, model) {
      var p = (provider || "").toLowerCase();
      var m = (model || "").toLowerCase();
      if (!p || !m) return false;
      if (p === "openai") return m.includes("gpt-5") || m.includes("o1") || m.includes("o3") || m.includes("o4");
      if (p === "gemini") return m.includes("gemini-2.5") || m.includes("gemini-3");
      if (p === "deepseek") return m.includes("reasoner");
      if (p === "openrouter") {
        return (
          m.includes("gpt-5") || m.includes("o1") || m.includes("o3") || m.includes("o4") ||
          m.includes("gemini-2.5") || m.includes("gemini-3") ||
          m.includes("reasoner") ||
          m.includes("claude-opus-4") || m.includes("claude-sonnet-4")
        );
      }
      return false;
    }

    function refreshReasoning(card) {
      if (!card) return;
      var prov = (card.querySelector(".cap-provider") || {}).value || "";
      var model = (card.querySelector(".cap-model") || {}).value || "";
      var checkbox = card.querySelector(".reasoning-check");
      var effortWrap = card.querySelector(".reasoning-effort");
      if (!checkbox || !effortWrap) return;
      var supported = reasoningSupportedFor(prov, model);
      checkbox.disabled = !supported;
      if (!supported) checkbox.checked = false;
      effortWrap.style.display = checkbox.checked && supported ? "" : "none";
    }

    function refreshSearchDefault() {
      var active = activeProviders();
      var sel = document.getElementById("search-default-select");
      if (!sel) return;
      Array.from(sel.options).forEach(function (opt) {
        if (opt.value === "auto") return;
        opt.disabled = !active.has(opt.value);
        opt.textContent = opt.textContent.replace(/ \(немає ключа\)$/, "");
        if (opt.disabled) opt.textContent += " (немає ключа)";
      });
    }

    document.querySelectorAll(".prov-key-input").forEach(function (i) {
      i.addEventListener("input", function () {
        refreshProviderDropdowns();
        refreshSearchDefault();
      });
    });
    document.querySelectorAll(".cap-provider").forEach(function (s) {
      s.addEventListener("change", function () {
        refreshModels(s);
      });
    });
    document.querySelectorAll(".cap-provider").forEach(function (s) {
      refreshModels(s);
    });
    document.querySelectorAll(".cap-model").forEach(function (s) {
      s.addEventListener("change", function () {
        refreshReasoning(s.closest(".cap-card"));
      });
    });
    document.querySelectorAll(".reasoning-check").forEach(function (cb) {
      cb.addEventListener("change", function () {
        refreshReasoning(cb.closest(".cap-card"));
      });
    });
    document.querySelectorAll(".cap-card").forEach(function (card) {
      refreshReasoning(card);
    });
    refreshProviderDropdowns();
    refreshSearchDefault();
  }

  // ---------- Logs page ----------
  function initLogs() {
    if (!document.querySelector(".logs-shell")) return;

    function buildParams() {
      var params = new URLSearchParams();
      params.set("service", document.getElementById("svc-select").value);
      params.set("lines", document.getElementById("lines-select").value);
      params.set("source", document.getElementById("source-select").value);
      params.set("chat_id", document.getElementById("chatid-input").value);
      params.set("message_id", document.getElementById("messageid-input").value);
      params.set("trace", document.getElementById("trace-input").value);
      params.set("capability", document.getElementById("capability-input").value);
      params.set("level", document.getElementById("level-select").value);
      params.set("contains", document.getElementById("contains-input").value);
      return params;
    }
    function reload() {
      window.location.href = "/logs?" + buildParams().toString();
    }
    function scrollEnd() {
      var el = document.getElementById("log-wrap");
      if (el) el.scrollTop = el.scrollHeight;
    }
    window.smartestLogsReload = reload;
    window.smartestLogsScrollEnd = scrollEnd;

    ["svc-select", "lines-select", "source-select", "level-select"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener("change", reload);
    });
    scrollEnd();

    setInterval(function () {
      fetch("/logs-text?" + buildParams().toString())
        .then(function (r) { return r.text(); })
        .then(function (t) {
          var pre = document.getElementById("log-pre");
          var wrap = document.getElementById("log-wrap");
          if (!pre || !wrap) return;
          var wasBottom = wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight < 60;
          pre.textContent = t;
          if (wasBottom) scrollEnd();
        })
        .catch(function () {});
    }, 10000);
    var label = document.getElementById("auto-label");
    if (label) label.textContent = "Авто-оновлення: 10с";
  }

  // ---------- Portal landing (Telegram Login) ----------
  function initPortalLanding() {
    if (!document.querySelector(".portal-landing")) return;
    var cfg = window.SmartestTelegram || {};
    var clientId = cfg.client_id || "";
    var nonce = cfg.nonce || "";

    function setStatus(text) {
      var node = document.getElementById("tg-login-status");
      if (node) node.textContent = text;
    }

    async function submitToken(idToken) {
      var response = await fetch("/auth/telegram", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id_token: idToken }),
      });
      var payload = await response.json().catch(function () {
        return { ok: false, message: "invalid_json" };
      });
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || "telegram_login_failed");
      }
      window.location.href = payload.redirect || "/";
    }

    window.smartestTelegramLogin = function () {
      if (!clientId) {
        setStatus("Telegram Login не сконфігурований для цього portal.");
        return;
      }
      if (!window.Telegram || !window.Telegram.Login || typeof window.Telegram.Login.auth !== "function") {
        setStatus("Telegram Login library ще не завантажилась. Перезавантаж сторінку і спробуй ще раз.");
        return;
      }
      setStatus("Відкриваю Telegram Login...");
      window.Telegram.Login.auth(
        { client_id: Number(clientId), nonce: nonce || undefined, lang: "uk" },
        async function (result) {
          if (!result) {
            setStatus("Telegram Login не повернув відповідь. Закрий popup і спробуй ще раз.");
            return;
          }
          if (result.error) {
            setStatus("Telegram Login не завершився: " + result.error);
            return;
          }
          if (!result.id_token) {
            setStatus("Telegram Login не повернув id_token.");
            return;
          }
          setStatus("Перевіряю Telegram token...");
          try {
            await submitToken(result.id_token);
          } catch (error) {
            setStatus("Telegram Login не завершився: " + (error.message || error));
          }
        }
      );
    };

    var btn = document.getElementById("tg-login-btn");
    if (btn && !btn.disabled) {
      btn.addEventListener("click", window.smartestTelegramLogin);
    }
  }

  function boot() {
    try { initDashboard(); } catch (e) { console.error("smartest.dashboard", e); }
    try { initLogs(); } catch (e) { console.error("smartest.logs", e); }
    try { initPortalLanding(); } catch (e) { console.error("smartest.portal", e); }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
