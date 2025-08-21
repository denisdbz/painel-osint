import os
import subprocess
import json
import uuid
import hashlib
import time
import sqlite3
import threading
import shlex
import shutil
import io
from flask import (
    Flask, request, jsonify, Response, send_file, abort, make_response
)
from werkzeug.utils import secure_filename
from datetime import datetime

app = Flask(__name__)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

DB_PATH = "history.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            task_id TEXT,
            tool TEXT,
            params TEXT,
            result TEXT,
            raw_output TEXT,
            status TEXT
        )"""
    )
    conn.commit()
    conn.close()

init_db()

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "changeme")

# ------------------ utilitários ------------------
def check_admin_token():
    token = request.args.get("token")
    return token == ADMIN_TOKEN

def record_history(task_id, tool, params_dict, result_dict, raw_output, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    ts = datetime.utcnow().isoformat()
    c.execute(
        "INSERT INTO history (timestamp, task_id, tool, params, result, raw_output, status) VALUES (?,?,?,?,?,?,?)",
        (ts, task_id, tool, json.dumps(params_dict), json.dumps(result_dict), raw_output, status),
    )
    conn.commit()
    conn.close()

def save_history(tool, params=None, result=None, raw_output=None, status="queued", task_id=None):
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

def fetch_history(limit=100):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, timestamp, task_id, tool, params, result, status FROM history ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = c.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "timestamp": r[1],
            "task_id": r[2],
            "tool": r[3],
            "params": json.loads(r[4] or "{}"),
            "result": json.loads(r[5] or "{}"),
            "status": r[6],
        })
    return out

def fetch_history_raw(hid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT raw_output FROM history WHERE id=?", (hid,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

TASKS = {}
TASK_LOCK = threading.Lock()

def start_task():
    tid = str(uuid.uuid4())
    with TASK_LOCK:
        TASKS[tid] = {"status": "running", "messages": [], "result": None}
    return tid

def append_task_message(tid, msg):
    with TASK_LOCK:
        if tid in TASKS:
            TASKS[tid]["messages"].append(msg)

def finish_task(tid, result):
    with TASK_LOCK:
        if tid in TASKS:
            TASKS[tid]["status"] = "done"
            TASKS[tid]["result"] = result

def task_status(tid):
    with TASK_LOCK:
        return TASKS.get(tid, None)

def run_subprocess_with_sse(tid, cmd, cwd=None):
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, universal_newlines=True, cwd=cwd
    )
    lines = []
    for line in process.stdout:
        line = line.rstrip()
        lines.append(line)
        append_task_message(tid, line)
    process.wait()
    return "\n".join(lines), process.returncode

def get_param_any(req, key):
    val = req.form.get(key) or req.args.get(key)
    if val:
        return val
    try:
        js = req.get_json(force=True, silent=True)
        if js and key in js:
            return js[key]
    except Exception:
        pass
    return None

# ------------------- Rotas -------------------

@app.route("/")
def index():
    return "painel_unificado rodando"

# sherlock
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

def _sherlock_worker(task_id, username):
    outdir = os.path.join("sherlock_results", task_id)
    os.makedirs(outdir, exist_ok=True)
    cmd = ["python3", "sherlock/sherlock", username, "--output", os.path.join(outdir, "result.json")]
    output, rc = run_subprocess_with_sse(task_id, cmd)
    result = {}
    if rc == 0:
        try:
            with open(os.path.join(outdir, "result.json"), "r", encoding="utf-8") as f:
                result = json.load(f)
        except Exception as e:
            result = {"error": str(e)}
    else:
        result = {"error": f"return_code={rc}"}
    record_history(task_id, "sherlock", {"username": username}, result, output[:10000], "done")
    finish_task(task_id, result)

# vazamento
@app.route("/vazamento/start", methods=["POST"])
def vazamento_start():
    email = get_param_any(request, "email")
    password = get_param_any(request, "password")
    if not email and not password:
        return jsonify({"error": "email_or_password_required"}), 400

    task_id = start_task()
    tool_name = "vazamento_password" if password and not email else (
        "vazamento_holehe" if email and not password else "vazamento"
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
    th = threading.Thread(target=_vazamento_worker, args=(task_id, email, password), daemon=True)
    th.start()
    return jsonify({"task_id": task_id})

def _vazamento_worker(task_id, email, password):
    script = os.path.join(os.getcwd(), "email_leak_checker_full.sh")
    args = ["bash", script]
    if email:
        args.extend(["--email", email])
    if password:
        args.extend(["--password", password])
    output, rc = run_subprocess_with_sse(task_id, args)
    result = {"return_code": rc}
    try:
        start = output.find("{")
        end = output.rfind("}")
        if start >= 0 and end > start:
            result.update(json.loads(output[start:end+1]))
    except Exception as e:
        result["json_error"] = str(e)
    record_history(task_id, "vazamento", {"email": email, "password": "***" if password else None}, result, output[:10000], "done")
    finish_task(task_id, result)

# metaweb
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

def _metaweb_worker(task_id, file_path=None, target=None):
    output_dir = os.path.join("metaweb_results", task_id)
    os.makedirs(output_dir, exist_ok=True)
    args = ["python3", "metaweb.py"]
    if file_path:
        args.extend(["--file", file_path])
    if target:
        args.extend(["--target", target])
    args.extend(["--out", output_dir])
    output, rc = run_subprocess_with_sse(task_id, args)
    result = {"return_code": rc}
    outjson = os.path.join(output_dir, "result.json")
    if os.path.exists(outjson):
        try:
            with open(outjson, "r", encoding="utf-8") as f:
                result.update(json.load(f))
        except Exception as e:
            result["json_error"] = str(e)
    record_history(task_id, "metaweb", {"file": file_path, "target": target}, result, output[:10000], "done")
    finish_task(task_id, result)

# SSE
@app.route("/events/<task_id>")
def sse_events(task_id):
    def gen():
        pos = 0
        while True:
            st = task_status(task_id)
            if st is None:
                yield f"data: {json.dumps({'error':'task_not_found'})}\n\n"
                break
            msgs = st["messages"]
            if pos < len(msgs):
                for m in msgs[pos:]:
                    yield f"data: {json.dumps({'message':m})}\n\n"
                pos = len(msgs)
            if st["status"] == "done":
                yield f"data: {json.dumps({'done':True,'result':st['result']})}\n\n"
                break
            time.sleep(1)
    return Response(gen(), mimetype="text/event-stream")

# admin
@app.route("/admin/history")
def admin_history():
    if not check_admin_token():
        return abort(401)
    data = fetch_history(limit=200)
    html = "<h1>History</h1><table border=1><tr><th>id</th><th>timestamp</th><th>task_id</th><th>tool</th><th>params</th><th>result</th><th>status</th><th>raw</th></tr>"
    for d in data:
        html += f"<tr><td>{d['id']}</td><td>{d['timestamp']}</td><td>{d['task_id']}</td><td>{d['tool']}</td><td>{d['params']}</td><td>{d['result']}</td><td>{d['status']}</td><td><a href='/admin/history/{d['id']}/download?token={ADMIN_TOKEN}'>download</a></td></tr>"
    html += "</table>"
    return html

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.logger.info("Starting app on port %s", port)
    print(f"[INFO] {datetime.utcnow().isoformat()} Starting app on port {port}")
    app.run(host="0.0.0.0", port=port)
