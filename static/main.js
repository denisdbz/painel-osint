document.addEventListener("DOMContentLoaded", () => {

  // ==============================
  // Função appendVazamento (links clicáveis e cores)
  // ==============================
  function appendVazamento(text) {
    const out = document.getElementById("out-vazamento");
    if (!out) return;

    let formatted = text;

    if (typeof text === "string" && text.startsWith("[+]")) {
      const urlMatch = text.match(/https?:\/\/\S+/);
      if (urlMatch) {
        formatted = `<span style="color:#2ee6a5;font-weight:bold;">[+] <a href="${urlMatch[0]}" target="_blank" rel="noopener noreferrer">${urlMatch[0]}</a></span>`;
      } else {
        formatted = `<span style="color:#2ee6a5;font-weight:bold;">${text}</span>`;
      }
    } else if (typeof text === "string" && text.startsWith("[-]")) {
      formatted = `<span style="color:#ff3860;">${text}</span>`;
    } else if (typeof text === "string" && text.startsWith("[x]")) {
      formatted = `<span style="color:#f3c623;">${text}</span>`;
    } else {
      // não escapa HTML, mantém links vindos do backend
      formatted = text;
    }

    out.innerHTML += formatted + "<br/>";
    out.scrollTop = out.scrollHeight;
  }

  // ==============================
  // Função genérica appendOut (Sherlock, Metaweb, etc.)
  // ==============================
  function appendOut(tool, text) {
    const out = document.getElementById(`out-${tool}`);
    if (!out) return;

    if (tool === "sherlock") {
      // Sherlock já envia HTML formatado (links clicáveis)
      out.innerHTML += text + "<br/>";
    } else {
      // Outras ferramentas: texto puro por segurança
      out.textContent += text + "\n";
    }

    out.scrollTop = out.scrollHeight;
  }

  // ==============================
  // Progress bar sem números
  // ==============================
  function setProgress(id, val) {
    const el = document.getElementById(id);
    if (!el) return;
    val = Math.max(0, Math.min(100, val));
    el.style.width = val + "%";
    // 🔥 removemos o texto de porcentagem
    // el.textContent = val + "%";
  }

  // ==============================
  // Função startSSE (genérica)
  // ==============================
  function startSSE(tool, task_id) {
    const out = document.getElementById(`out-${tool}`);
    if (out) {
      out.textContent = ""; // limpa output antes de iniciar
    }
    const progressEl = document.getElementById(`pg-${tool}`);
    let progress = 0;

    const es = new EventSource(`/sse/${tool}/${task_id}`);

    function advanceProgress(increment = 1) {
      if (!progressEl) return;
      progress = Math.min(95, progress + increment);
      setProgress(`pg-${tool}`, progress);
    }

    es.addEventListener("log", (evt) => {
      const raw = evt.data;
      if (!raw) return;
      try {
        const d = JSON.parse(raw);
        if (Object.prototype.hasOwnProperty.call(d, "line")) {
          if (d.line !== null && d.line !== undefined && d.line !== "") {
            appendOut(tool, d.line);
          }
        } else {
          appendOut(tool, JSON.stringify(d));
        }
      } catch (e) {
        appendOut(tool, raw);
      }
      advanceProgress(1);
    });

    es.addEventListener("status", (evt) => {
      const raw = evt.data;
      if (!raw) return;
      try {
        const d = JSON.parse(raw);
        const msg = d.msg || JSON.stringify(d);
        appendOut(tool, "[STATUS] " + msg);
      } catch (e) {
        appendOut(tool, "[STATUS] " + raw);
      }
      advanceProgress(2);
    });

    es.addEventListener("result", (evt) => {
      const raw = evt.data;
      if (!raw) return;
      try {
        const d = JSON.parse(raw);
        appendOut(tool, "[RESULT] " + JSON.stringify(d));
      } catch (e) {
        appendOut(tool, "[RESULT] " + raw);
      }
      advanceProgress(3);
    });

    es.addEventListener("done", (evt) => {
      const raw = evt.data;
      if (raw) {
        try {
          const d = JSON.parse(raw);
          appendOut(tool, "[DONE] " + (d.ok ? "ok" : JSON.stringify(d)));
        } catch (e) {
          appendOut(tool, "[DONE] " + raw);
        }
      } else {
        appendOut(tool, "[DONE]");
      }
      setProgress(`pg-${tool}`, 100);
      try { es.close(); } catch (e) {}
    });

    es.addEventListener("error", (evt) => {
      const raw = (evt && evt.data) ? evt.data : null;
      if (!raw) {
        appendOut(tool, "[ERROR] connection or streaming error (no data)");
      } else {
        try {
          const d = JSON.parse(raw);
          appendOut(tool, "[ERROR] " + (d.msg || JSON.stringify(d)));
        } catch (e) {
          appendOut(tool, "[ERROR] " + raw);
        }
      }
      try { es.close(); } catch (e) {}
    });

    return es;
  }

  // ==============================
  // Sherlock Form
  // ==============================
  const sherlockForm = document.getElementById("sherlock-form");
  if (sherlockForm) {
    sherlockForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const usernameEl = document.getElementById("sherlock-username");
      const username = usernameEl ? usernameEl.value.trim() : "";
      if (!username) return alert("Informe um usuário.");
      setProgress("pg-sherlock", 5);
      const res = await fetch("/sherlock/start", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username })
      });
      const data = await res.json();
      startSSE("sherlock", data.task_id);
    });
  }

  // ==============================
  // Vazamento Form
  // ==============================
  const vazForm = document.getElementById("vazamento-form");
  if (vazForm) {
    vazForm.addEventListener("submit", async (e) => {
      e.preventDefault();

      const emailEl = document.getElementById("vazamento-email");
      const passEl = document.getElementById("vazamento-password");
      const email = emailEl ? emailEl.value.trim() : "";
      const password = passEl ? passEl.value : "";

      if (!email && !password) return alert("Informe e-mail ou senha.");

      setProgress("pg-vazamento", 5);

      const body = new URLSearchParams();
      if (email) body.append("email", email);
      if (password) body.append("password", password);

      const res = await fetch("/vazamento/start", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body
      });

      const data = await res.json();

      const out = document.getElementById("out-vazamento");
      if (out) out.innerHTML = ""; // limpa saída

      const es = startSSE("vazamento", data.task_id);

      // Substitui logs do vazamento para usar appendVazamento
      es.addEventListener("log", (evt) => {
        const raw = evt.data;
        if (!raw) return;
        try {
          const d = JSON.parse(raw);
          if (Object.prototype.hasOwnProperty.call(d, "line")) {
            if (d.line !== null && d.line !== undefined && d.line !== "") {
              appendVazamento(d.line);
            }
          } else {
            appendVazamento(JSON.stringify(d));
          }
        } catch (err) {
          appendVazamento(raw);
        }
      });
    });
  }

  // ==============================
  // Metaweb Form
  // ==============================
  const metaForm = document.getElementById("metaweb-form");
  if (metaForm) {
    metaForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = document.getElementById("metaweb-file");
      if (!input || !input.files || !input.files[0]) return alert("Selecione um arquivo.");
      setProgress("pg-metaweb", 5);
      const fd = new FormData();
      fd.append("file", input.files[0]);
      const res = await fetch("/metaweb/start", { method: "POST", body: fd });
      const data = await res.json();
      startSSE("metaweb", data.task_id);
    });
  }

});
