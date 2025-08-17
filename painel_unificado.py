import os
import sys
import json
import uuid
import time
import shutil
import threading
import subprocess
from flask import (
    Flask, render_template, request, jsonify, Response
)
from flask_cors import CORS  # <<< ADICIONADO

app = Flask(__name__)
CORS(app)  # <<< ADICIONADO

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
STATIC_DIR = os.path.join(BASE_DIR, "static")

for d in (UPLOAD_DIR, RESULTS_DIR):
    os.makedirs(d, exist_ok=True)

# --- Infra simples de SSE em memória ---
TASK_COND = {}
TASK_QUEUE = {}
TASK_TOOL = {}  # task_id -> "vazamento" | "metaweb" | "sherlock"


def _ensure_task(task_id: str, tool: str = None):
    if task_id not in TASK_COND:
        TASK_COND[task_id] = threading.Condition()
        TASK_QUEUE[task_id] = []
    if tool:
        TASK_TOOL[task_id] = tool


def _push_event(task_id: str, etype: str, payload: dict):
    _ensure_task(task_id)
    cond = TASK_COND[task_id]
    with cond:
        TASK_QUEUE[task_id].append((etype, payload))
        cond.notify_all()


def _sse_stream_named(task_id: str):
    _ensure_task(task_id)
    cond = TASK_COND[task_id]
    idx = 0
    while True:
        with cond:
            if idx >= len(TASK_QUEUE[task_id]):
                cond.wait(timeout=30)
            if idx >= len(TASK_QUEUE[task_id]):
                yield ": keep-alive\n\n"
                continue
            etype, payload = TASK_QUEUE[task_id][idx]
            idx += 1

        yield f"event: {etype}\n"
        yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

        if etype in ("complete", "error"):
            break


# ========= Função de links de busca =========
def montar_links_busca(email: str):
    email_q = f'"{email}"'  # busca exata

    return {
        "Google": f"https://www.google.com/search?q={email_q}",
        "Bing": f"https://www.bing.com/search?q={email_q}",
        "DuckDuckGo": f"https://duckduckgo.com/?q={email_q}",
        "Yahoo": f"https://search.yahoo.com/search?p={email_q}",
        "Yandex": f"https://yandex.com/search/?text={email_q}",
        "GitHub": f"https://github.com/search?q={email_q}",
        "Pastebin": f"https://pastebin.com/search?q={email_q}",
        "Twitter/X": f"https://x.com/search?q={email_q}&src=typed_query",
        "Reddit": f"https://www.reddit.com/search/?q={email_q}",
        "LinkedIn": f"https://www.linkedin.com/search/results/all/?keywords={email_q}"
    }


# ========= Filtro para limpar resultados inúteis =========
def filtrar_resultados(links, email):
    extensoes_ruins = [".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".woff", ".ico"]
    vistos = set()
    filtrados = {}

    for nome, url in links.items():
        if any(url.lower().endswith(ext) for ext in extensoes_ruins):
            continue
        if url in vistos:
            continue
        vistos.add(url)
        filtrados[nome] = url
    return filtrados


# ========== ROTAS BÁSICAS ==========
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/vazamento", methods=["GET"])
def email_leak():
    return render_template("vazamento.html")


@app.route("/metaweb", methods=["GET"])
def metaweb():
    return render_template("metaweb.html")


@app.route("/sherlock", methods=["GET"])
def sherlock_search():
    return render_template("sherlock.html")


@app.route("/ajuda", methods=["GET"])
def ajuda():
    return render_template("ajuda.html")


# ========== START ==========
@app.route("/start_vazamento", methods=["POST"])
def vazamento_start():    email = request.form.get("email", "").strip()
    if not email:
        return jsonify({"ok": False, "error": "Email não informado"}), 400
    task_id = str(uuid.uuid4())
    _ensure_task(task_id, tool="vazamento")
    threading.Thread(
        target=_run_vazamento_task, args=(task_id, email), daemon=True
    ).start()
    return jsonify({"ok": True, "task_id": task_id})


@app.route("/metaweb/start", methods=["POST"])
def metaweb_start():
    file = request.files.get("file")
    if not file:
        return jsonify({"ok": False, "error": "Arquivo não enviado"}), 400
    uid = str(uuid.uuid4())
    safe_name = f"{uid}__{os.path.basename(file.filename)}"
    save_path = os.path.join(UPLOAD_DIR, safe_name)
    file.save(save_path)
    task_id = str(uuid.uuid4())
    _ensure_task(task_id, tool="metaweb")
    threading.Thread(
        target=_run_metaweb_task, args=(task_id, save_path), daemon=True
    ).start()
    return jsonify({"ok": True, "task_id": task_id})


@app.route("/sherlock/start", methods=["POST"])
def sherlock_start():
    username = request.form.get("username", "").strip()
    include_nsfw = bool(request.form.get("nsfw"))
    if not username:
        return jsonify({"ok": False, "error": "Nome de usuário não informado"}), 400
    task_id = str(uuid.uuid4())
    _ensure_task(task_id, tool="sherlock")
    threading.Thread(
        target=_run_sherlock_task, args=(task_id, username, include_nsfw), daemon=True
    ).start()
    return jsonify({"ok": True, "task_id": task_id})


# ========== SSE ==========
@app.route("/sse/vazamento/<task_id>")
def sse_vazamento_named(task_id):
    return Response(_sse_stream_named(task_id), mimetype="text/event-stream")


@app.route("/sse/metaweb/<task_id>")
def sse_metaweb_named(task_id):
    return Response(_sse_stream_named(task_id), mimetype="text/event-stream")


@app.route("/sse/sherlock/<task_id>")
def sse_sherlock(task_id):
    return Response(_sse_stream_named(task_id), mimetype="text/event-stream")


# ========== RESULTADOS ==========
@app.route("/sherlock/result/<task_id>")
def sherlock_result(task_id):
    rel_json = os.path.join(BASE_DIR, "leak_check_results", "ultimo_relatorio_sherlock.json")
    if not os.path.exists(rel_json):
        return render_template("sherlock_result.html", username="-", resultados=[])

    with open(rel_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    username = data.get("username", "-")
    resultados_dict = data.get("resultados", {})

    resultados = []
    for fonte, info in resultados_dict.items():
        resultados.append({
            "fonte": fonte,
            "achou": True,
            "quantidade": 1,
            "arquivo": info["arquivo"],
            "link": info["link"]
        })

    stderr = data.get("stderr", "")

    return render_template(
        "sherlock_result.html",
        username=username,
        resultados=resultados,
        stderr=stderr
    )


# ========== IMPLEMENTAÇÕES DAS TASKS ==========
def _run_vazamento_task(task_id: str, email: str):
    _push_event(task_id, "progress", {"percent": 1, "message": "Iniciando verificação..."})
    script = os.path.join(TOOLS_DIR, "email_leak_checker_full.sh")
    if not os.path.exists(script):
        _push_event(task_id, "error", {"message": "Script de vazamento não encontrado"})
        return

    try:
        proc = subprocess.Popen(
            ["/bin/bash", script, email],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # ✅ leitura assíncrona até finalizar
        while True:
            ret = proc.poll()
            if ret is not None:
                break
            time.sleep(0.5)

        rel_json = os.path.join(BASE_DIR, "leak_check_results", "ultimo_relatorio.json")
        dados = {}
        if os.path.exists(rel_json):
            with open(rel_json, "r", encoding="utf-8") as f:
                dados = json.load(f)

        links = montar_links_busca(email)
        links = filtrar_resultados(links, email)

        _push_event(task_id, "payload", {
            "dados": dados,
            "links": [{"nome": nome, "url": url} for nome, url in links.items()],
            "resumo": f"Verificação concluída para {email}"
        })
        _push_event(task_id, "complete", {"ok": True})
    except Exception as e:
        _push_event(task_id, "error", {"message": str(e)})


def _run_metaweb_task(task_id: str, filepath: str):
    resultado = {}
    etapas = [
        ("file", ["file", filepath]),
        ("exiftool", ["exiftool", filepath]),
        ("strings", ["strings", "-n", "8", filepath]),
        ("md5sum", ["md5sum", filepath]),
        ("sha256sum", ["sha256sum", filepath])
    ]
    for nome, cmd in etapas:
        try:
            resultado[nome] = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
        except Exception as e:
            resultado[nome] = f"Erro: {e}"

    _push_event(task_id, "payload", {"resultado": resultado})
    _push_event(task_id, "complete", {"ok": True})


def _run_sherlock_task(task_id: str, username: str, include_nsfw: bool):
    _push_event(task_id, "progress", {"percent": 1, "message": "Executando Sherlock..."})

    py = sys.executable or "python3"
    runner = os.path.join(TOOLS_DIR, "sherlock_runner.py")
    cmd = [py, runner, username]
    if include_nsfw:
        cmd.append("--nsfw")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=TOOLS_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # ✅ espera não bloqueante
        while True:
            ret = proc.poll()
            if ret is not None:
                break
            time.sleep(0.5)

        rel_json = os.path.join(BASE_DIR, "leak_check_results", "ultimo_relatorio_sherlock.json")
        dados = {}
        if os.path.exists(rel_json):
            with open(rel_json, "r", encoding="utf-8") as f:
                dados = json.load(f)

        _push_event(task_id, "payload", {"dados": dados, "resumo": f"Sherlock concluído para {username}"})
        _push_event(task_id, "complete", {"ok": True})
    except Exception as e:
        _push_event(task_id, "error", {"message": f"Erro ao rodar Sherlock: {e}"})


# ========== MAIN ==========
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
