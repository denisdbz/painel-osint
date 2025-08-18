import os
import sys
import json
import uuid
import time
import shutil
import threading
import subprocess
from flask import (
    Flask, render_template, request, jsonify, Response, send_from_directory
)
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TOOLS_DIR = os.path.join(BASE_DIR, "tools")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
PROGRESS_DIR = os.path.join(BASE_DIR, "progress")
RELATORIOS_DIR = os.path.join(BASE_DIR, "static", "relatorios")

for d in [RESULTS_DIR, UPLOADS_DIR, PROGRESS_DIR, RELATORIOS_DIR]:
    os.makedirs(d, exist_ok=True)


def run_tool(command, progress_file, result_file):
    with open(progress_file, "w") as f:
        f.write("0")

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    output_lines = []
    for i, line in enumerate(process.stdout, start=1):
        output_lines.append(line.strip())
        with open(progress_file, "w") as f:
            f.write(str(min(100, i)))

    process.wait()
    with open(result_file, "w") as f:
        f.write("\n".join(output_lines))

    with open(progress_file, "w") as f:
        f.write("100")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/ajuda")
def ajuda():
    return render_template("ajuda.html")


@app.route("/sherlock")
def sherlock():
    return render_template("sherlock.html")


@app.route("/vazamento")
def vazamento():
    return render_template("vazamento.html")


@app.route("/metaweb")
def metaweb():
    return render_template("metaweb.html")


@app.route("/start_sherlock", methods=["POST"])
def start_sherlock():
    username = request.form.get("username")
    if not username:
        return jsonify({"error": "Usuário não informado"}), 400

    task_id = str(uuid.uuid4())
    progress_file = os.path.join(PROGRESS_DIR, f"sherlock_{task_id}.txt")
    result_file = os.path.join(RESULTS_DIR, f"sherlock_{task_id}.txt")

    thread = threading.Thread(
        target=run_tool,
        args=(["python3", os.path.join(TOOLS_DIR, "sherlock.py"), username],
              progress_file, result_file)
    )
    thread.start()

    return jsonify({"task_id": task_id})


@app.route("/sherlock_progress/<task_id>")
def sherlock_progress(task_id):
    progress_file = os.path.join(PROGRESS_DIR, f"sherlock_{task_id}.txt")
    result_file = os.path.join(RESULTS_DIR, f"sherlock_{task_id}.txt")

    def generate():
        while True:
            if os.path.exists(progress_file):
                with open(progress_file) as f:
                    progress = f.read().strip()
            else:
                progress = "0"

            yield f"data: {json.dumps({'progress': progress})}\n\n"

            if progress == "100" and os.path.exists(result_file):
                with open(result_file) as f:
                    result = f.read()
                yield f"data: {json.dumps({'progress': 100, 'result': result})}\n\n"
                break

            time.sleep(1)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/start_vazamento", methods=["POST"])
def start_vazamento():
    email = request.form.get("email")
    if not email:
        return jsonify({"error": "E-mail não informado"}), 400

    task_id = str(uuid.uuid4())
    progress_file = os.path.join(PROGRESS_DIR, f"vazamento_{task_id}.txt")
    result_file = os.path.join(RESULTS_DIR, f"vazamento_{task_id}.txt")

    thread = threading.Thread(
        target=run_tool,
        args=(["python3", os.path.join(TOOLS_DIR, "leakcheck.py"), email],
              progress_file, result_file)
    )
    thread.start()

    return jsonify({"task_id": task_id})


@app.route("/vazamento_progress/<task_id>")
def vazamento_progress(task_id):
    progress_file = os.path.join(PROGRESS_DIR, f"vazamento_{task_id}.txt")
    result_file = os.path.join(RESULTS_DIR, f"vazamento_{task_id}.txt")

    def generate():
        while True:
            if os.path.exists(progress_file):
                with open(progress_file) as f:
                    progress = f.read().strip()
            else:
                progress = "0"

            yield f"data: {json.dumps({'progress': progress})}\n\n"

            if progress == "100" and os.path.exists(result_file):
                with open(result_file) as f:
                    result = f.read()
                yield f"data: {json.dumps({'progress': 100, 'result': result})}\n\n"
                break

            time.sleep(1)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/start_metaweb", methods=["POST"])
def start_metaweb():
    query = request.form.get("query")
    if not query:
        return jsonify({"error": "Consulta não informada"}), 400

    task_id = str(uuid.uuid4())
    progress_file = os.path.join(PROGRESS_DIR, f"metaweb_{task_id}.txt")
    result_file = os.path.join(RESULTS_DIR, f"metaweb_{task_id}.txt")

    thread = threading.Thread(
        target=run_tool,
        args=(["python3", os.path.join(TOOLS_DIR, "metaweb.py"), query],
              progress_file, result_file)
    )
    thread.start()

    return jsonify({"task_id": task_id})


@app.route("/metaweb_progress/<task_id>")
def metaweb_progress(task_id):
    progress_file = os.path.join(PROGRESS_DIR, f"metaweb_{task_id}.txt")
    result_file = os.path.join(RESULTS_DIR, f"metaweb_{task_id}.txt")

    def generate():
        while True:
            if os.path.exists(progress_file):
                with open(progress_file) as f:
                    progress = f.read().strip()
            else:
                progress = "0"

            yield f"data: {json.dumps({'progress': progress})}\n\n"

            if progress == "100" and os.path.exists(result_file):
                with open(result_file) as f:
                    result = f.read()
                yield f"data: {json.dumps({'progress': 100, 'result': result})}\n\n"
                break

            time.sleep(1)

    return Response(generate(), mimetype="text/event-stream")


# 🔹 NOVA ROTA PARA RELATÓRIOS
@app.route("/relatorio/<data>/<arquivo>")
def mostrar_relatorio(data, arquivo):
    caminho = os.path.join("static", "relatorios", data, arquivo)
    if not os.path.exists(caminho):
        return "Relatório não encontrado", 404

    with open(caminho, "r", encoding="utf-8") as f:
        conteudo = f.read()

    return render_template("relatorio.html", conteudo=conteudo, arquivo=arquivo)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
