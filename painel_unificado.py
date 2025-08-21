#!/usr/bin/env python3
# painel_unificado.py  -- Versão com histórico SQLite + SSE + ferramentas

import os
import sys
import re
import json
import uuid
import time
import queue
import shutil
import hashlib
import logging
import threading
import subprocess
import sqlite3
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import (
    Flask, render_template, request, jsonify, Response,
    stream_with_context, abort, make_response
)
from flask_cors import CORS


# ----------------------
# Config / paths
# ----------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
RUNS_DIR = os.path.join(BASE_DIR, "runs")
DB_PATH = os.path.join(BASE_DIR, "painel.db")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RUNS_DIR, exist_ok=True)

# max chars of raw output to keep in DB (prevents DB blowup)
MAX_OUTPUT_CHARS = 16000


# ----------------------
# Flask app
# ----------------------

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

# logging
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s %(message)s"))
app.logger.setLevel(logging.INFO)
app.logger.addHandler(handler)


# =====================================================
# 📱 PhoneInfoga
# =====================================================

def detect_phoneinfoga():
    # tenta binário no sistema
    bin_path = "/usr/local/bin/phoneinfoga"
    if os.path.isfile(bin_path):
        return [bin_path], "bin"

    # tenta binário no diretório tools/ do projeto
    local_path = os.path.join(os.path.dirname(__file__), "tools", "phoneinfoga")
    if os.path.isfile(local_path):
        return [local_path], "bin"

    # se não achar em lugar nenhum
    return None, "not_found"


@app.route("/phoneinfoga", methods=["GET", "POST"])
def phoneinfoga():
    if request.method == "POST":
        numero = request.form.get("numero")
        if not numero:
            return render_template("phoneinfoga.html", erro="Digite um número de telefone.")

        pasta_relatorios = "static/relatorios/"
        os.makedirs(pasta_relatorios, exist_ok=True)
        json_path = os.path.join(pasta_relatorios, f"phoneinfoga_{numero}.json")

        try:
            cmd_prefix, _how = detect_phoneinfoga()
            if not cmd_prefix:
                return render_template("phoneinfoga.html", erro="PhoneInfoga não encontrado.")

            # v2 não suporta -o/-f, apenas scan -n
            cmd = cmd_prefix + ["scan", "-n", numero]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode != 0:
                return render_template(
                    "phoneinfoga.html",
                    erro=f"Erro ao executar PhoneInfoga: {result.stderr}"
                )

            output = result.stdout.strip()

            try:
                dados = json.loads(output)
            except json.JSONDecodeError:
                dados = {"raw_output": output}

            # salvar relatório
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(dados, f, indent=2, ensure_ascii=False)

            # 🔎 extrair links com regex
            raw_text = json.dumps(dados, ensure_ascii=False)
            links = re.findall(r'https?://[^\s"\'<>]+', raw_text)

            return render_template(
                "relatorio_phoneinfoga.html",
                numero=numero,
                dados=dados,
                dados_json=json.dumps(dados, ensure_ascii=False),
                links=links
            )
        except Exception as e:
            return render_template("phoneinfoga.html", erro=str(e))

    # GET
    return render_template("phoneinfoga.html")
# -------------------
# SQLite (history)
# -------------------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            tool TEXT,
            params TEXT,
            result TEXT,
            raw_output TEXT,
            status TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def record_history(task_id, tool, params_dict, result_dict, raw_output, status="ok"):
    try:
        init_db()
        ro = raw_output or ""
        if len(ro) > MAX_OUTPUT_CHARS:
            ro = ro[:MAX_OUTPUT_CHARS] + "\n\n...[truncated]..."
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO history (task_id, tool, params, result, raw_output, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                tool,
                json.dumps(params_dict, ensure_ascii=False),
                json.dumps(result_dict, ensure_ascii=False),
                ro,
                status,
                datetime.utcnow().isoformat() + "Z",
            ),
        )
        conn.commit()
        conn.close()
        app.logger.info("history recorded: tool=%s task=%s status=%s", tool, task_id, status)
    except Exception:
        app.logger.exception("failed to record history")


def save_history(tool, params=None, result=None, raw_output=None, status="started", task_id=None):
    if task_id is None:
        task_id = str(uuid.uuid4())
    record_history(
        task_id=task_id,
        tool=tool,
        params_dict=(params or {}),
        result_dict=(result or {}),
        raw_output=(raw_output or ""),
        status=status,
    )
    return task_id


def fetch_history(limit=200):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, task_id, tool, params, result, status, created_at "
        "FROM history ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = c.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append(
            {
                "id": r[0],
                "task_id": r[1],
                "tool": r[2],
                "params": json.loads(r[3]) if r[3] else {},
                "result": json.loads(r[4]) if r[4] else {},
                "status": r[5],
                "created_at": r[6],
            }
        )
    return out


def fetch_history_raw(hid):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT raw_output FROM history WHERE id = ?", (hid,))
    r = c.fetchone()
    conn.close()
    if not r:
        return None
    return r[0]


# -------------------
# SSE infra
# -------------------

streams = {}  # task_id -> queue.Queue()


def start_task():
    task_id = str(uuid.uuid4())
    streams[task_id] = queue.Queue()
    app.logger.info("start_task %s", task_id)
    return task_id


def end_task(task_id):
    time.sleep(0.2)
    app.logger.info("end_task %s", task_id)


def sse_put(task_id, event, data):
    q = streams.get(task_id)
    if not q:
        app.logger.debug("sse_put: no stream %s", task_id)
        return
    payload = f"event: {event}\n" + "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"
    q.put(payload)


def sse_stream(task_id):
    q = streams.get(task_id)
    if q is None:
        yield "event: error\n" + "data: " + json.dumps({"msg": "task_not_found"}) + "\n\n"
        return
    try:
        last_ping = 0
        while True:
            try:
                chunk = q.get(timeout=0.25)
                yield chunk
                if chunk.startswith("event: done") or chunk.startswith("event: error"):
                    break
            except queue.Empty:
                now = time.time()
                if now - last_ping > 15:
                    yield "event: ping\n" + "data: " + json.dumps({"t": now}) + "\n\n"
                    last_ping = now
    except GeneratorExit:
        app.logger.debug("SSE client disconnected")
    except Exception:
        app.logger.exception("sse_stream exception")
    finally:
        streams.pop(task_id, None)
        app.logger.debug("sse_stream finished for %s", task_id)
# -------------------
# Helpers
# -------------------

def safe_domain(input_str):
    parsed = urlparse(input_str if re.match(r"^https?://", input_str) else f"http://{input_str}")
    host = parsed.hostname or input_str
    return host


def run_command_stream(cmd_list, cwd=None, env=None):
    try:
        cmd_str = " ".join(cmd_list) if isinstance(cmd_list, (list, tuple)) else str(cmd_list)
    except Exception:
        cmd_str = str(cmd_list)
    app.logger.info("run_command_stream: %s", cmd_str)

    try:
        proc = subprocess.Popen(
            cmd_list,
            cwd=cwd or BASE_DIR,
            env=env or os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )
    except FileNotFoundError:
        raise

    try:
        for raw in iter(proc.stdout.readline, ""):
            if raw is None:
                break
            line = raw.rstrip("\r\n")
            if not line.strip():
                continue
            yield line
        try:
            proc.stdout.close()
        except Exception:
            pass
        ret = proc.wait()
        if ret != 0:
            raise subprocess.CalledProcessError(ret, cmd_str)
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass


def detect_executable(module_name, script_name=None):
    exe = shutil.which(module_name)
    if exe:
        return [exe], "exe"
    if script_name:
        script_path = os.path.join(BASE_DIR, script_name)
        if os.path.exists(script_path):
            return [sys.executable, script_path], "script"
    return [sys.executable, "-m", module_name], "module"


def file_hashes(path):
    sha256 = hashlib.sha256()
    md5 = hashlib.md5()
    size = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            sha256.update(chunk)
            md5.update(chunk)
            size += len(chunk)
    return {"size": size, "sha256": sha256.hexdigest(), "md5": md5.hexdigest()}


# -------------------
# Workers (cada worker acumula saída e grava histórico)
# -------------------

def _sherlock_worker(task_id, username):
    lines = []
    found_count = 0
    try:
        sse_put(task_id, "status", {"phase": "starting", "msg": "Iniciando Sherlock"})
        sherlock_dir = os.path.join(BASE_DIR, "tools", "sherlock")
        local_main = os.path.join(sherlock_dir, "sherlock_project", "main.py")
        cwd = sherlock_dir

        if os.path.exists(local_main):
            exe_prefix = [sys.executable, "-m", "sherlock_project.__main__"]
            how = "local-main"
        else:
            exe_prefix, how = detect_executable(
                "sherlock",
                script_name=os.path.join("tools", "sher
# -------------------
# Views / pages & SSE endpoint
# -------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/sherlock")
def sherlock_page():
    return render_template("sherlock.html")


@app.route("/metaweb")
def metaweb_page():
    return render_template("metaweb.html")


@app.route("/vazamento")
def vazamento_page():
    return render_template("vazamento.html")


@app.route("/sse/<tool>/<task_id>")
def sse(tool, task_id):
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return Response(
        stream_with_context(sse_stream(task_id)),
        mimetype="text/event-stream",
        headers=headers,
    )


# -------------------
# Utilities to read params
# -------------------

def get_param_any(request_obj, name):
    try:
        data = request_obj.get_json(silent=True)
    except Exception:
        data = None
    if data and name in data:
        return data.get(name)
    v = request_obj.form.get(name)
    if v:
        return v
    v = request_obj.values.get(name)
    return v


# -------------------
# HTTP endpoints to start tools
# -------------------

@app.route("/sherlock/start", methods=["POST"])
def sherlock_start():
    username = get_param_any(request, "username") or ""
    username = username.strip()
    if not username:
        return jsonify({"error": "username_required"}), 400

    task_id = start_task()

    save_history(
        tool="sherlock",
        params={"username": username},
        result={"note": "start"},
        status="started",
        task_id=task_id,
    )

    th = threading.Thread(target=_sherlock_worker, args=(task_id, username), daemon=True)
    th.start()
    return jsonify({"task_id": task_id})


@app.route("/vazamento/start", methods=["POST"])
def vazamento_start():
    email = get_param_any(request, "email")
    password = get_param_any(request, "password")
    if not email and not password:
        return jsonify({"error": "email_or_password_required"}), 400

    task_id = start_task()

    tool_name = (
        "vazamento_password"
        if password and not email
        else ("vazamento_holehe" if email and not password else "vazamento")
    )

    snapshot_params = {}
    if email:
        snapshot_params["email"] = email
    if password:
        sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        snapshot_params["password_prefix"] = sha1[:5]

    save_history(
        tool=tool_name,
        params=snapshot_params,
        result={"note": "start"},
        status="started",
        task_id=task_id,
    )

    th = threading.Thread(
        target=_vazamento_worker, args=(task_id, email, password), daemon=True
    )
    th.start()
    return jsonify({"task_id": task_id})


@app.route("/metaweb/start", methods=["POST"])
def metaweb_start():
    file = request.files.get("file")
    target = get_param_any(request, "target")
    if not file and not target:
        return jsonify({"error": "file_or_target_required"}), 400

    file_path = None
    if file:
        filename = secure_filename(file.filename)
        unique = f"{int(time.time())}_{uuid.uuid4().hex}_{filename}"
        file_path = os.path.join(UPLOAD_DIR, unique)
        file.save(file_path)
        app.logger.info("metaweb saved upload %s", file_path)

    task_id = start_task()

    if file_path:
        save_history(
            tool="metaweb_file",
            params={"file": os.path.basename(file_path)},
            result={"note": "start"},
            status="started",
            task_id=task_id,
        )
    else:
        save_history(
            tool="metaweb_target",
            params={"target": target},
            result={"note": "start"},
            status="started",
            task_id=task_id,
        )

    th = threading.Thread(
        target=_metaweb_worker,
        kwargs={"task_id": task_id, "file_path": file_path, "target": (target or None)},
        daemon=True,
    )
    th.start()
    return jsonify({"task_id": task_id})


# -------------------
# favicon & health
# -------------------

@app.route("/favicon.ico")
def favicon():
    return ("", 204)


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


# -------------------
# Admin: histórico (protegido por token)
# -------------------

def check_admin_token():
    token_env = os.environ.get("ADMIN_TOKEN", "changeme")
    token_req = request.headers.get("X-Admin-Token") or request.args.get("token")
    if not token_req or token_req != token_env:
        return False
    return True


@app.route("/admin/history")
def admin_history_page():
    if not check_admin_token():
        return abort(401)
    rows = fetch_history(limit=500)
    html = [
        "<html><head><meta charset='utf-8'><title>Histórico</title>"
        "<style>body{background:#0b0f14;color:#cde; font-family:Inter,Segoe UI,Helvetica,Arial;} "
        "table{width:100%;border-collapse:collapse} "
        "th,td{padding:8px;border-bottom:1px solid #223} "
        "th{background:#071018;text-align:left}</style></head><body>"
    ]
    html.append("<h2>Histórico de consultas</h2>")
    html.append("<p>Use o token seguro no header X-Admin-Token ou ?token=SEUTOKEN</p>")
    html.append(
        "<table><tr><th>ID</th><th>Tool</th><th>Params</th><th>Result</th>"
        "<th>Status</th><th>Created</th><th>Download</th></tr>"
    )
    for r in rows:
        html.append("<tr>")
        html.append(f"<td>{r['id']}</td>")
        html.append(f"<td>{r['tool']}</td>")
        html.append(f"<td><pre style='margin:0'>{json.dumps(r['params'], ensure_ascii=False)}</pre></td>")
        html.append(f"<td><pre style='margin:0'>{json.dumps(r['result'], ensure_ascii=False)}</pre></td>")
        html.append(f"<td>{r['status']}</td>")
        html.append(f"<td>{r['created_at']}</td>")
        html.append(
            f"<td><a href='/admin/history/{r['id']}/download?token={request.args.get('token') or ''}'>download</a></td>"
        )
        html.append("</tr>")
    html.append("</table></body></html>")
    return Response("\n".join(html), mimetype="text/html")


@app.route("/admin/history.json")
def admin_history_json():
    if not check_admin_token():
        return abort(401)
    limit = request.args.get("limit", 200)
    try:
        limit = int(limit)
    except Exception:
        limit = 200
    rows = fetch_history(limit=limit)
    return jsonify(rows)


@app.route("/admin/history/<int:hid>/download")
def admin_history_download(hid):
    if not check_admin_token():
        return abort(401)
    raw = fetch_history_raw(hid)
    if raw is None:
        return abort(404)
    resp = make_response(raw)
    resp.headers.set("Content-Type", "text/plain; charset=utf-8")
    resp.headers.set("Content-Disposition", f"attachment; filename=history_{hid}.txt")
    return resp


# -------------------
# factory (useful for gunicorn)
# -------------------

def create_app():
    init_db()
    return app


# -------------------
# Main
# -------------------

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 10000))
    app.logger.info("Starting app on port %s", port)
    app.run(host="0.0.0.0", port=port, debug=False)
