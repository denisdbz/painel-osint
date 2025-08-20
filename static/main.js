document.addEventListener("DOMContentLoaded", () => {

  function setProgress(id, val) {
    const el = document.getElementById(id);
    if (!el) return;
    val = Math.max(0, Math.min(100, val)); // garante 0-100
    el.style.width = val + "%";
    el.textContent = val + "%"; // opcional: mostrar percentual
  }

  function appendOut(tool, text) {
    const out = document.getElementById(`out-${tool}`);
    if (!out) return;

    // Corrige Sherlock para links clicáveis
    if (tool === "sherlock") {
        out.innerHTML += text + "<br>";
    } else {
        out.textContent += text + "\n";
    }

    out.scrollTop = out.scrollHeight;
  }

  function startSSE(tool, task_id) {
    const out = document.getElementById(`out-${tool}`);
    if (out) out.textContent = "";
    const progressEl = document.getElementById(`pg-${tool}`);
    let progress = 0;

    const es = new EventSource(`/sse/${tool}/${task_id}`);

    function advanceProgress(increment = 1) {
      if (!progressEl) return;
      progress = Math.min(95, progress + increment); // nunca passa 95 até receber 'done'
      setProgress(`pg-${tool}`, progress);
    }

    es.addEventListener("log", (evt) => {
      try {
        const d = JSON.parse(evt.data);
        appendOut(tool, d.line || JSON.stringify(d));
      } catch (e) {
        appendOut(tool, evt.data);
      }
      advanceProgress(1);
    });

    es.addEventListener("status", (evt) => {
      try {
        const d = JSON.parse(evt.data);
        appendOut(tool, "[STATUS] " + (d.msg || JSON.stringify(d)));
      } catch (e) {
        appendOut(tool, "[STATUS] " + evt.data);
      }
      advanceProgress(2);
    });

    es.addEventListener("result", (evt) => {
      try {
        const d = JSON.parse(evt.data);
        appendOut(tool, "[RESULT] " + JSON.stringify(d));
      } catch (e) {
        appendOut(tool, "[RESULT] " + evt.data);
      }
      advanceProgress(3);
    });

    es.addEventListener("done", (evt) => {
      try {
        const d = JSON.parse(evt.data);
        appendOut(tool, "[DONE] " + (d.ok ? "ok" : JSON.stringify(d)));
      } catch (e) {
        appendOut(tool, "[DONE] " + evt.data);
      }
      setProgress(`pg-${tool}`, 100);
      es.close();
    });

    es.addEventListener("error", (evt) => {
      try {
        const d = JSON.parse(evt.data);
        appendOut(tool, "[ERROR] " + (d.msg || JSON.stringify(d)));
      } catch (e) {
        appendOut(tool, "[ERROR] " + evt.data);
      }
      es.close();
    });

    es.addEventListener("ping", () => {
      // opcional: poderia avançar lentamente a barra se quiser
    });

    return es;
  }

  // SHERLOCK
  const sherlockForm = document.getElementById("sherlock-form");
  if (sherlockForm) {
    sherlockForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const username = document.getElementById("sherlock-username").value.trim();
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

// VAZAMENTO
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

    // SSE customizado para vazamento
    const out = document.getElementById("out-vazamento");
    if (out) out.innerHTML = ""; // limpa saída

    const es = startSSE("vazamento", data.task_id);

    // Substitui appendOut por appendVazamento
    es.addEventListener("log", (evt) => {
      try {
        const d = JSON.parse(evt.data);
        appendVazamento(d.line || JSON.stringify(d));
      } catch (err) {
        appendVazamento(evt.data);
      }
    });
  });
}

// Função appendVazamento com cores e links clicáveis
function appendVazamento(text) {
  const out = document.getElementById("out-vazamento");
  if (!out) return;

  let formatted = text;

  if (text.startsWith("[+]")) {
    const urlMatch = text.match(/https?:\/\/\S+/);
    if (urlMatch) {
      formatted = `<span style="color:#2ee6a5;font-weight:bold;">[+] <a href="${urlMatch[0]}" target="_blank" rel="noopener noreferrer">${urlMatch[0]}</a></span>`;
    } else {
      formatted = `<span style="color:#2ee6a5;font-weight:bold;">${text}</span>`;
    }
  } else if (text.startsWith("[-]")) {
    formatted = `<span style="color:#ff3860;">${text}</span>`;
  } else if (text.startsWith("[x]")) {
    formatted = `<span style="color:#f3c623;">${text}</span>`;
  }

  out.innerHTML += formatted + "<br/>";
  out.scrollTop = out.scrollHeight;
}

  // METAWEB
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
