import os
import sys
import json
import uuid
import time
import threading
import subprocess
from flask import (
    Flask, render_template, request, jsonify, Response
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
    """Executa ferramenta em subprocesso e grava progresso/resultados"""
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
    with open(result_file, "w", encoding="utf-8") as f:
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


# ----------------- SHERLOCK -----------------
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
            progress = "0"
            if os.path.exists(progress_file):
                with open(progress_file) as f:
                    progress = f.read().strip()

            yield f"data: {json.dumps({'progress': progress})}\n\n"

            if progress == "100" and os.path.exists(result_file):
                with open(result_file, encoding="utf-8") as f:
                    result = f.read()
                yield f"data: {json.dumps({'progress': 100, 'result': result})}\n\n"
                break
            time.sleep(1)

    return Response(generate(), mimetype="text/event-stream")


# ----------------- VAZAMENTO -----------------
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
            progress = "0"
            if os.path.exists(progress_file):
                with open(progress_file) as f:
                    progress = f.read().strip()

            yield f"data: {json.dumps({'progress': progress})}\n\n"

            if progress == "100" and os.path.exists(result_file):
                with open(result_file, encoding="utf-8") as f:
                    result = f.read()
                yield f"data: {json.dumps({'progress': 100, 'result': result})}\n\n"
                break
            time.sleep(1)

    return Response(generate(), mimetype="text/event-stream")


# ----------------- METAWEB -----------------
@app.route("/start_metaweb", methods=["POST"])
def start_metaweb():
    if "file" not in request.files:
        return jsonify({"error": "Arquivo não enviado"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Nome de arquivo inválido"}), 400

    task_id = str(uuid.uuid4())
    upload_path = os.path.join(UPLOADS_DIR, f"{task_id}_{file.filename}")
    file.save(upload_path)

    progress_file = os.path.join(PROGRESS_DIR, f"metaweb_{task_id}.txt")
    result_file = os.path.join(RESULTS_DIR, f"metaweb_{task_id}.txt")

    thread = threading.Thread(
        target=run_tool,
        args=(["python3", os.path.join(TOOLS_DIR, "metaweb.py"), upload_path],
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
            progress = "0"
            if os.path.exists(progress_file):
                with open(progress_file) as f:
                    progress = f.read().strip()

            yield f"data: {json.dumps({'progress': progress})}\n\n"

            if progress == "100" and os.path.exists(result_file):
                with open(result_file, encoding="utf-8") as f:
                    result = f.read()
                yield f"data: {json.dumps({'progress': 100, 'result': result})}\n\n"
                break
            time.sleep(1)

    return Response(generate(), mimetype="text/event-stream")


# ----------------- RELATÓRIOS -----------------
@app.route("/relatorio/<data>/<arquivo>")
def mostrar_relatorio(data, arquivo):
    caminho = os.path.join("static", "relatorios", data, arquivo)
    if not os.path.exists(caminho):
        return "Relatório não encontrado", 404

    with open(caminho, "r", encoding="utf-8") as f:
        conteudo = f.read()

    return render_template("relatorio.html", conteudo=conteudo, arquivo=arquivo)


# ==============================================
# ROTAS DE RESULTADOS COM TEMPLATES
# ==============================================

@app.route('/sherlock_results/<task_id>')
def sherlock_results(task_id):
    result_file = os.path.join(RESULTS_DIR, f"sherlock_{task_id}.txt")
    if not os.path.exists(result_file):
        return "Resultado não encontrado", 404
    with open(result_file, encoding="utf-8") as f:
        result = f.read()
    return render_template('_results.html', task={'id': task_id, 'result': result})

@app.route('/vazamento_results/<task_id>')
def vazamento_results(task_id):
    result_file = os.path.join(RESULTS_DIR, f"vazamento_{task_id}.txt")
    if not os.path.exists(result_file):
        return "Resultado não encontrado", 404
    with open(result_file, encoding="utf-8") as f:
        result = f.read()
    return render_template('_results.html', task={'id': task_id, 'result': result})

@app.route('/metaweb_results/<task_id>')
def metaweb_results(task_id):
    result_file = os.path.join(RESULTS_DIR, f"metaweb_{task_id}.txt")
    if not os.path.exists(result_file):
        return "Resultado não encontrado", 404
    with open(result_file, encoding="utf-8") as f:
        result = f.read()
    return render_template('_results.html', task={'id': task_id, 'result': result})

# ==============================================
# ROTAS DE PROGRESSO COM TEMPLATES
# ==============================================

@app.route('/sherlock_progress_template/<task_id>')
def sherlock_progress_template(task_id):
    progress_file = os.path.join(PROGRESS_DIR, f"sherlock_{task_id}.txt")
    if not os.path.exists(progress_file):
        return "Progresso não encontrado", 404
    with open(progress_file) as f:
        progress = f.read().strip()
    return render_template('_progress.html', task={'id': task_id, 'progress': progress})

@app.route('/vazamento_progress_template/<task_id>')
def vazamento_progress_template(task_id):
    progress_file = os.path.join(PROGRESS_DIR, f"vazamento_{task_id}.txt")
    if not os.path.exists(progress_file):
        return "Progresso não encontrado", 404
    with open(progress_file) as f:
        progress = f.read().strip()
    return render_template('_progress.html', task={'id': task_id, 'progress': progress})

@app.route('/metaweb_progress_template/<task_id>')
def metaweb_progress_template(task_id):
    progress_file = os.path.join(PROGRESS_DIR, f"metaweb_{task_id}.txt")
    if not os.path.exists(progress_file):
        return "Progresso não encontrado", 404
    with open(progress_file) as f:
        progress = f.read().strip()
    return render_template('_progress.html', task={'id': task_id, 'progress': progress})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port)
