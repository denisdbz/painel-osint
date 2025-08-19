document.addEventListener("DOMContentLoaded", () => {

    // Submissão Sherlock
    const sherlockForm = document.getElementById("sherlock-form");
    if (sherlockForm) {
        sherlockForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const username = document.getElementById("sherlock-username").value;
            const res = await fetch("/sherlock/start", {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: new URLSearchParams({ username })
            });

            const data = await res.json();
            startSSE("sherlock", data.task_id, "out-sherlock");
        });
    }

    // Submissão Holehe
    const vazamentoForm = document.getElementById("vazamento-form");
    if (vazamentoForm) {
        vazamentoForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const email = document.getElementById("vazamento-email").value;

            const res = await fetch("/vazamento/start", {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: new URLSearchParams({ email })
            });

            const data = await res.json();
            startSSE("vazamento", data.task_id, "out-vazamento");
        });
    }

    // Submissão Metaweb (UPLOAD)
    const metawebForm = document.getElementById("metaweb-form");
    if (metawebForm) {
        metawebForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const fileInput = document.getElementById("metaweb-file");
            if (!fileInput.files.length) {
                alert("Selecione um arquivo para enviar!");
                return;
            }

            const formData = new FormData();
            formData.append("file", fileInput.files[0]);

            const res = await fetch("/metaweb/start", {
                method: "POST",
                body: formData
            });

            const data = await res.json();
            startSSE("metaweb", data.task_id, "out-metaweb");
        });
    }

    // Função para receber logs em tempo real
    function startSSE(tool, task_id, outputId) {
        const logBox = document.getElementById(outputId);
        logBox.innerHTML = "";

        const evtSource = new EventSource(`/sse/${tool}/${task_id}`);
        evtSource.onmessage = (event) => {
            const line = document.createElement("div");
            line.textContent = event.data;
            logBox.appendChild(line);
            logBox.scrollTop = logBox.scrollHeight;
        };
    }
});
