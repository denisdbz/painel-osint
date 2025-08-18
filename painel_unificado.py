#!/usr/bin/env python3
import os
import sys
import json
import uuid
import time
import shutil
import threading
import subprocess
from flask import Flask, render_template, request, jsonify, Response

# -------------------------------------------------
# Configuração básica do Flask
# -------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
STATIC_DIR = os.path.join(BASE_DIR, "static")
LEAK_DIR = os.path.join(BASE_DIR, "leak_check_results")

# Garante diretórios usados em runtime
for d in (UPLOAD_DIR, RESULTS_DIR, LEAK_DIR):
    os.makedirs(d, exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["JSON_AS_ASCII"] = False

# -------------------------------------------------
# Infra simples de SSE em memória
# -------------------------------------------------
TASK_COND = {}   # task_id -> threading.Condition
TASK_QUEUE = {}  # task_id -> list[(etype, payload)]
TASK_TOOL = {}   # task_id -> "vazamento" | "metaweb" | "sherlock"


def _ensure_task(task_id: str, tool: str | None = None):
    if task_id not in TASK_COND:
        TASK_COND[task_id] = threading.Condition()
        TASK_QUEUE[task_id] = []
    if tool:
        TASK_TOOL[task_id] = tool


def _push_event(task_id: str, etype: str, payload: dict):
    """Empilha um evento para a task e notifica listeners SSE."""
    _ensure_task(task_id)
    cond = TASK_COND[task_id]
    with cond:
        TASK_QUEUE[task_id].append((etype, payload))
        cond.notify_all()


def _sse_stream_named(task_id: str):
    """
    Generator para SSE.
    Envia eventos 'progress', 'payload', 'complete', 'error' + keep-alive.
    """
    _ensure_task(task_id)
    cond = TASK_COND[task_id]
    idx = 0
    while True:
        with cond:
            if idx >= len(TASK_QUEUE[task_id]):
                # espera até 30s por novos eventos
                cond.wait(timeout=30)
            if idx >= len(TASK_QUEUE[task_id]):
                # keep-alive para proxies não derrubarem a conexão
                yield ": keep-alive\n\n"
                continue

            etype, payload = TASK_QUEUE[task_id][idx]
            idx += 1

        # envia o evento nomeado
        yield f"event: {etype}\n"
        yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

        if etype in ("complete", "error"):
            break


def _sse_response(gen):
    """Gera uma Response SSE com cabeçalhos adequados."""
    resp = Response(gen, mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"  # nginx/render: tentar desabilitar buffering
    return resp


# -------------------------------------------------
# Rotas de página (navegação do usuário)
# -------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/vazamento", methods=["GET"])
def vazamento():
    return render_template("vazamento.html")


@app.route("/metaweb", methods=["GET"])
def metaweb():
    return render_template("metaweb.html")


@app.route("/sherlock", methods=["GET"])
def sherlock():
    return render_template("sherlock.html")


@app.route("/ajuda", methods=["GET"])
def ajuda():
    return render_template("ajuda.html")


# -------------------------------------------------
# Rotas START (iniciam tasks assíncronas)
# -------------------------------------------------
@app.route("/vazamento/start", methods=["POST"])
def vazamento_start():
    email = request.form.get("email", "").strip()
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


# -------------------------------------------------
# Rotas SSE (stream de progresso/resultados)
# -------------------------------------------------
@app.route("/sse/vazamento/<task_id>")
def sse_vazamento_named(task_id):
    return _sse_response(_sse_stream_named(task_id))


@app.route("/sse/metaweb/<task_id>")
def sse_metaweb_named(task_id):
    return _sse_response(_sse_stream_named(task_id))


@app.route("/sse/sherlock/<task_id>")
def sse_sherlock_named(task_id):
    return _sse_response(_sse_stream_named(task_id))


# -------------------------------------------------
# Rotas de compatibilidade (se o front ainda usa ..._progress)
# -------------------------------------------------
@app.route("/vazamento_progress/<task_id>")
def compat_vazamento_progress(task_id):
    return _sse_response(_sse_stream_named(task_id))


@app.route("/metaweb_progress/<task_id>")
def compat_metaweb_progress(task_id):
    return _sse_response(_sse_stream_named(task_id))


@app.route("/sherlock_progress/<task_id>")
def compat_sherlock_progress(task_id):
    return _sse_response(_sse_stream_named(task_id))


# -------------------------------------------------
# Implementações das tasks
# -------------------------------------------------
def _run_vazamento_task(task_id: str, email: str):
    _push_event(task_id, "progress", {"percent": 1, "message": "Iniciando verificação de vazamento..."})

    script = os.path.join(TOOLS_DIR, "email_leak_checker_full.sh")
    if not os.path.exists(script):
        _push_event(task_id, "error", {"message": "Script de vazamento não encontrado."})
        return

    try:
        # Consumir stdout para evitar deadlock em caso de muita saída
        proc = subprocess.Popen(
            ["/bin/bash", script, email],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        # Stream de logs (opcional para UI que queira exibir)
        if proc.stdout:
            for line in proc.stdout:
                line = line.rstrip("\n")
                if line:
                    _push_event(task_id, "log", {"line": line})

        code = proc.wait()
        if code != 0:
            _push_event(task_id, "error", {"message": f"Script retornou código {code}."})
            return

        _push_event(task_id, "progress", {"percent": 80, "message": "Lendo relatório..."})

        rel_json = os.path.join(LEAK_DIR, "ultimo_relatorio.json")
        dados = {}
        if os.path.exists(rel_json):
            with open(rel_json, "r", encoding="utf-8") as f:
                dados = json.load(f)

        _push_event(task_id, "payload", {
            "dados": dados,
            "resumo": f"Verificação concluída para {email}"
        })
        _push_event(task_id, "progress", {"percent": 100, "message": "Concluído."})
        _push_event(task_id, "complete", {"ok": True})

    except Exception as e:
        _push_event(task_id, "error", {"message": f"Falha ao executar verificação: {e}"})


def _run_metaweb_task(task_id: str, filepath: str):
    _push_event(task_id, "progress", {"percent": 1, "message": "Processando arquivo..."})

    resultado = {}
    etapas = [
        ("file", ["file", filepath]),
        ("exiftool", ["exiftool", filepath]),
        ("strings", ["strings", "-n", "8", filepath]),
        ("md5sum", ["md5sum", filepath]),
        ("sha256sum", ["sha256sum", filepath]),
    ]

    for i, (nome, cmd) in enumerate(etapas, start=1):
        try:
            _push_event(task_id, "progress", {"percent": min(10 + i * 15, 90), "message": f"Executando {nome}..."})
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
            resultado[nome] = out.strip()
        except Exception as e:
            resultado[nome] = f"Erro: {e}"

    _push_event(task_id, "payload", {"resultado": resultado})
    _push_event(task_id, "progress", {"percent": 100, "message": "Concluído."})
    _push_event(task_id, "complete", {"ok": True})

    # limpeza opcional: mover arquivo para results
    try:
        dest = os.path.join(RESULTS_DIR, os.path.basename(filepath))
        if os.path.exists(filepath):
            shutil.move(filepath, dest)
    except Exception:
        pass


def _run_sherlock_task(task_id: str, username: str, include_nsfw: bool):
    """
    Executa tools/sherlock_runner.py que deve gerar HTMLs/JSON sob leak_check_results/.
    """
    _push_event(task_id, "progress", {"percent": 1, "message": "Executando Sherlock..."})

    runner = os.path.join(TOOLS_DIR, "sherlock_runner.py")
    if not os.path.exists(runner):
        _push_event(task_id, "error", {"message": "Runner do Sherlock não encontrado."})
        return

    py = sys.executable or "python3"
    cmd = [py, runner, username]
    if include_nsfw:
        cmd.append("--nsfw")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=TOOLS_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        if proc.stdout:
            for line in proc.stdout:
                line = line.rstrip("\n")
                if line:
                    _push_event(task_id, "log", {"line": line})

        code = proc.wait()
        if code != 0:
            _push_event(task_id, "error", {"message": f"Sherlock retornou código {code}."})
            return

        _push_event(task_id, "progress", {"percent": 80, "message": "Lendo resultados..."})

        rel_json = os.path.join(LEAK_DIR, "ultimo_relatorio_sherlock.json")
        dados = {}
        if os.path.exists(rel_json):
            with open(rel_json, "r", encoding="utf-8") as f:
                dados = json.load(f)

        _push_event(task_id, "payload", {"dados": dados, "resumo": f"Sherlock concluído para {username}"})
        _push_event(task_id, "progress", {"percent": 100, "message": "Concluído."})
        _push_event(task_id, "complete", {"ok": True})

    except Exception as e:
        _push_event(task_id, "error", {"message": f"Erro ao rodar Sherlock: {e}"})


# -------------------------------------------------
# Main / execução local
# -------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))  # Render normalmente injeta PORT
    # threaded=True ajuda o SSE no servidor embutido
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
