import os
import sys
import json
import uuid
import time
import shutil
import threading
import subprocess
from flask import (
    Flask, render_template, request, jsonify, Response, redirect, url_for
)
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Dicionário para armazenar status e logs
tasks_status = {}
tasks_logs = {}

def run_command(task_id, cmd):
    """
    Executa um comando externo em subprocesso e envia logs em tempo real.
    """
    tasks_status[task_id] = "running"
    tasks_logs[task_id] = []

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        for line in iter(process.stdout.readline, ''):
            line = line.strip()
            if line:
                tasks_logs[task_id].append(line)
                print(f"[{task_id}] {line}")

        process.stdout.close()
        return_code = process.wait()

        if return_code == 0:
            tasks_status[task_id] = "finished"
        else:
            tasks_status[task_id] = "error"
            tasks_logs[task_id].append(f"[ERRO] Processo retornou {return_code}")

    except Exception as e:
        tasks_status[task_id] = "error"
        tasks_logs[task_id].append(f"[FATAL] {str(e)}")


def stream_logs(task_id):
    """
    Gera logs em tempo real via SSE.
    """
    last_index = 0
    while tasks_status.get(task_id) == "running":
        logs = tasks_logs.get(task_id, [])
        while last_index < len(logs):
            yield f"data: {logs[last_index]}\n\n"
            last_index += 1
        time.sleep(1)

    # Envia logs finais
    logs = tasks_logs.get(task_id, [])
    while last_index < len(logs):
        yield f"data: {logs[last_index]}\n\n"
        last_index += 1

    yield f"data: [status] {tasks_status.get(task_id, 'desconhecido')}\n\n"


# -------------------
# ROTAS PRINCIPAIS
# -------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/sherlock")
def sherlock_page():
    return render_template("sherlock.html")


@app.route("/vazamento")
def vazamento_page():
    return render_template("vazamento.html")


@app.route("/metaweb")
def metaweb_page():
    return render_template("metaweb.html")


# -------------------
# INICIAR FERRAMENTAS
# -------------------

@app.route("/sherlock/start", methods=["POST"])
def start_sherlock():
    username = request.form.get("username")
    if not username:
        return jsonify({"error": "Usuário não informado"}), 400

    task_id = str(uuid.uuid4())
    cmd = ["python3", "tools/sherlock/sherlock.py", username, "--json", f"{task_id}.json"]

    threading.Thread(target=run_command, args=(task_id, cmd)).start()

    return jsonify({"task_id": task_id})


@app.route("/vazamento/start", methods=["POST"])
def start_vazamento():
    email = request.form.get("email")
    if not email:
        return jsonify({"error": "E-mail não informado"}), 400

    task_id = str(uuid.uuid4())
    cmd = ["holehe", email]  # removi -j -s porque não existem no holehe

    threading.Thread(target=run_command, args=(task_id, cmd)).start()

    return jsonify({"task_id": task_id})


@app.route("/metaweb/start", methods=["POST"])
def start_metaweb():
    if "file" not in request.files:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Arquivo inválido"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_DIR, filename)
    file.save(filepath)

    task_id = str(uuid.uuid4())
    cmd = ["python3", "tools/metaweb/main.py", filepath]

    threading.Thread(target=run_command, args=(task_id, cmd)).start()

    return jsonify({"task_id": task_id})


# -------------------
# STREAM DE LOGS
# -------------------

@app.route("/sse/<tool>/<task_id>")
def sse_logs(tool, task_id):
    return Response(stream_logs(task_id), mimetype="text/event-stream")


# -------------------
# EXECUÇÃO
# -------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
