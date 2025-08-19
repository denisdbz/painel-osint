document.addEventListener("DOMContentLoaded", () => {
  // Helpers
  function byId(id) { return document.getElementById(id); }
  function appendLine(preId, text) {
    const box = byId(preId);
    if (!box) return;
    box.textContent += (box.textContent ? "\n" : "") + text;
    box.scrollTop = box.scrollHeight;
  }
  function setProgress(barId, pct) {
    const bar = byId(barId);
    if (bar && typeof pct === "number") {
      bar.style.width = Math.max(0, Math.min(100, pct)) + "%";
    }
  }

  function startSSE(tool, taskId, outId, barId) {
    // Reset UI
    if (outId) byId(outId).textContent = "";
    if (barId) setProgress(barId, 5);

    const es = new EventSource(`/sse/${tool}/${taskId}`);

    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        appendLine(outId, `[message] ${JSON.stringify(data)}`);
      } catch {
        appendLine(outId, ev.data);
      }
    };

    es.addEventListener("status", (ev) => {
      try {
        const obj = JSON.parse(ev.data);
        if (obj.phase === "starting") setProgress(barId, 10);
        appendLine(outId, `[status] ${obj.msg ?? ""}`.trim());
      } catch {}
    });

    es.addEventListener("log", (ev) => {
      try {
        const obj = JSON.parse(ev.data);
        if (obj.line) appendLine(outId, obj.line);
      } catch {
        appendLine(outId, ev.data);
      }
    });

    es.addEventListener("result", (ev) => {
      try {
        const obj = JSON.parse(ev.data);
        appendLine(outId, `[result:${obj.type}] ${JSON.stringify(obj.data)}`);
        setProgress(barId, 90);
      } catch {
        appendLine(outId, ev.data);
      }
    });

    es.addEventListener("error", (ev) => {
      try {
        const obj = JSON.parse(ev.data);
        appendLine(outId, `❌ ${obj.msg || "Erro"}`);
      } catch {
        appendLine(outId, `❌ ${ev.data}`);
      }
      setProgress(barId, 100);
      es.close();
    });

    es.addEventListener("done", (ev) => {
      setProgress(barId, 100);
      try {
        const obj = JSON.parse(ev.data);
        if (obj.ok) appendLine(outId, "✅ Finalizado");
      } catch {}
      es.close();
    });

    es.addEventListener("ping", (_ev) => {});
  }

  // --- Sherlock ---
  const sherlockForm = document.getElementById("form-sherlock");
  if (sherlockForm) {
    sherlockForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const username = (byId("sherlock-username")?.value || "").trim();
      if (!username) { alert("Informe o usuário"); return; }
      const res = await fetch("/sherlock/start", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username })
      });
      if (!res.ok) {
        const t = await res.text();
        appendLine("out-sherlock", `❌ ${t}`);
        return;
      }
      const data = await res.json();
      startSSE("sherlock", data.task_id, "out-sherlock", "pg-sherlock");
    });
  }

  // --- Vazamento (holehe) ---
  const vazForm = document.getElementById("form-vazamento");
  if (vazForm) {
    vazForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const email = (byId("vazamento-email")?.value || "").trim();
      if (!email || !email.includes("@")) { alert("Informe um e-mail válido"); return; }
      const res = await fetch("/vazamento/start", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ email })
      });
      if (!res.ok) {
        const t = await res.text();
        appendLine("out-vazamento", `❌ ${t}`);
        return;
      }
      const data = await res.json();
      startSSE("vazamento", data.task_id, "out-vazamento", "pg-vazamento");
    });
  }

  // --- MetaWeb (upload) ---
  const metaForm = document.getElementById("metaweb-form");
  if (metaForm) {
    metaForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = byId("metaweb-file");
      if (!input?.files?.[0]) { alert("Selecione um arquivo."); return; }
      const fd = new FormData();
      fd.append("file", input.files[0]);
      const res = await fetch("/metaweb/start", { method: "POST", body: fd });
      if (!res.ok) {
        const t = await res.text();
        appendLine("out-metaweb", `❌ ${t}`);
        return;
      }
      const data = await res.json();
      startSSE("metaweb", data.task_id, "out-metaweb", "pg-metaweb");
    });
  }
});
