async function startTask(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload || {})
  });
  if (!res.ok) throw new Error("Falha ao iniciar tarefa");
  const data = await res.json();
  return data.task_id;
}

function logLine(el, text) {
  el.textContent += (text.endsWith("\n") ? text : text + "\n");
  el.scrollTop = el.scrollHeight;
}

function sseListen(path, onEvent) {
  const es = new EventSource(path);
  es.onmessage = (e) => onEvent("message", e);
  es.addEventListener("log", (e) => onEvent("log", e));
  es.addEventListener("result", (e) => onEvent("result", e));
  es.addEventListener("status", (e) => onEvent("status", e));
  es.addEventListener("done", (e) => onEvent("done", e));
  es.addEventListener("error", (e) => onEvent("error", e));
  es.addEventListener("ping", (e) => onEvent("ping", e));
  return es;
}

function fakeProgress(el, until=87) {
  let v = 0;
  const id = setInterval(() => {
    v += Math.max(1, Math.floor(Math.random()*5));
    if (v >= until) { v = until; clearInterval(id); }
    el.style.width = v + "%";
  }, 250);
  return () => clearInterval(id);
}

document.addEventListener("DOMContentLoaded", () => {
  // Sherlock
  const btnS = document.getElementById("btn-sherlock");
  if (btnS) {
    btnS.addEventListener("click", async () => {
      const out = document.getElementById("out-sherlock");
      const pg = document.getElementById("pg-sherlock");
      out.textContent = "";
      pg.style.width = "0%";
      const stopFake = fakeProgress(pg, 90);
      try {
        const username = document.getElementById("sherlock-username").value.trim();
        const taskId = await startTask("/sherlock/start", {username});
        const es = sseListen(`/sse/sherlock/${taskId}`, (type, ev) => {
          if (type === "log" || type === "message") {
            try {
              const obj = JSON.parse(ev.data);
              logLine(out, obj.line || ev.data);
            } catch { logLine(out, ev.data); }
          } else if (type === "result") {
            const obj = JSON.parse(ev.data);
            logLine(out, "\n--- RESULTADO PARCIAL ---\n" + JSON.stringify(obj, null, 2));
          } else if (type === "status") {
            const obj = JSON.parse(ev.data);
            logLine(out, `[status] ${obj.msg || ""}`);
          } else if (type === "done") {
            stopFake();
            pg.style.width = "100%";
            logLine(out, "\n[FIM]\n");
            es.close();
          } else if (type === "error") {
            stopFake();
            logLine(out, "[ERRO] " + ev.data);
            es.close();
          }
        });
      } catch (e) {
        stopFake();
        logLine(out, "[ERRO] " + e.message);
      }
    });
  }

  // MetaWeb
  const btnM = document.getElementById("btn-metaweb");
  if (btnM) {
    btnM.addEventListener("click", async () => {
      const out = document.getElementById("out-metaweb");
      const pg = document.getElementById("pg-metaweb");
      out.textContent = "";
      pg.style.width = "0%";
      const stopFake = fakeProgress(pg, 92);
      try {
        const target = document.getElementById("metaweb-target").value.trim();
        const taskId = await startTask("/metaweb/start", {target});
        const es = sseListen(`/sse/metaweb/${taskId}`, (type, ev) => {
          if (type === "log" || type === "message") {
            try {
              const obj = JSON.parse(ev.data);
              logLine(out, obj.line || ev.data);
            } catch { logLine(out, ev.data); }
          } else if (type === "result") {
            const obj = JSON.parse(ev.data);
            logLine(out, "\n--- BLOCO ---\n" + JSON.stringify(obj, null, 2));
          } else if (type === "status") {
            const obj = JSON.parse(ev.data);
            logLine(out, `[status] ${obj.msg || ""}`);
          } else if (type === "done") {
            stopFake();
            pg.style.width = "100%";
            logLine(out, "\n[FIM]\n");
            es.close();
          } else if (type === "error") {
            stopFake();
            logLine(out, "[ERRO] " + ev.data);
            es.close();
          }
        });
      } catch (e) {
        stopFake();
        logLine(out, "[ERRO] " + e.message);
      }
    });
  }

  // Vazamento
  const btnV = document.getElementById("btn-vazamento");
  if (btnV) {
    btnV.addEventListener("click", async () => {
      const out = document.getElementById("out-vazamento");
      const pg = document.getElementById("pg-vazamento");
      out.textContent = "";
      pg.style.width = "0%";
      const stopFake = fakeProgress(pg, 88);
      try {
        const email = document.getElementById("vazamento-email").value.trim();
        const taskId = await startTask("/vazamento/start", {email});
        const es = sseListen(`/sse/vazamento/${taskId}`, (type, ev) => {
          if (type === "log" || type === "message") {
            try {
              const obj = JSON.parse(ev.data);
              logLine(out, obj.line || ev.data);
            } catch { logLine(out, ev.data); }
          } else if (type === "result") {
            const obj = JSON.parse(ev.data);
            logLine(out, "\n--- SITE ---\n" + JSON.stringify(obj, null, 2));
          } else if (type === "status") {
            const obj = JSON.parse(ev.data);
            logLine(out, `[status] ${obj.msg || ""}`);
          } else if (type === "done") {
            stopFake();
            pg.style.width = "100%";
            logLine(out, "\n[FIM]\n");
            es.close();
          } else if (type === "error") {
            stopFake();
            logLine(out, "[ERRO] " + ev.data);
            es.close();
          }
        });
      } catch (e) {
        stopFake();
        logLine(out, "[ERRO] " + e.message);
      }
    });
  }
});

