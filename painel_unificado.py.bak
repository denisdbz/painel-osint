#!/usr/bin/env python3
# painel_unificado.py  -- Versão robusta para Render (SSE + ferramentas)
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
from urllib.parse import urlparse
from werkzeug.utils import secure_filename

from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from flask_cors import CORS

# ----------------------
# Config / paths
# ----------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
RUNS_DIR = os.path.join(BASE_DIR, "runs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RUNS_DIR, exist_ok=True)

# Flask app
app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

# logging
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s %(message)s"))
app.logger.setLevel(logging.INFO)
app.logger.addHandler(handler)

# -------------------
# SSE infra
# -------------------
streams = {}  # task_id -> queue.Queue()

def start_task():
    task_id = str(uuid.uuid4())
    streams[task_id] = queue.Queue()
    app.logger.info(f"start_task {task_id}")
    return task_id

def end_task(task_id):
    time.sleep(0.2)
    streams.pop(task_id, None)
    app.logger.info(f"end_task {task_id}")

def sse_put(task_id, event, data):
    """
    Push an SSE event (event name + JSON-able data) to task queue.
    """
    q = streams.get(task_id)
    if not q:
        app.logger.debug(f"sse_put: no stream {task_id}")
        return
    payload = f"event: {event}\n" + "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"
    q.put(payload)

def sse_stream(task_id):
    q = streams.get(task_id)
    if q is None:
        yield 'event: error\n' + 'data: "task_not_found"\n\n'
        return
    try:
        last_ping = 0
        while True:
            try:
                chunk = q.get(timeout=0.25)
                yield chunk
            except queue.Empty:
                now = time.time()
                # periodic ping to keep connection alive
                if now - last_ping > 15:
                    sse_put(task_id, "ping", {"t": now})
                    last_ping = now
    except GeneratorExit:
        app.logger.debug("SSE client disconnected")
    except Exception as e:
        app.logger.exception("sse_stream exception")
    finally:
        app.logger.debug("sse_stream finished")

# -------------------
# Helpers
# -------------------
def safe_domain(input_str):
    parsed = urlparse(input_str if re.match(r"^https?://", input_str) else f"http://{input_str}")
    host = parsed.hostname or input_str
    return host

def run_command_stream(cmd_list, cwd=None, env=None):
    """
    Run subprocess and yield stdout lines as they appear.
    """
    app.logger.info("run_command_stream: %s", " ".join(cmd_list))
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
    except FileNotFoundError as e:
        raise

    try:
        for line in iter(proc.stdout.readline, ""):
            if line is None:
                break
            yield line.rstrip("\n")
        proc.stdout.close()
        ret = proc.wait()
        if ret != 0:
            raise subprocess.CalledProcessError(ret, cmd_list)
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass

def detect_executable(module_name, script_name=None):
    """
    Return an executable command list. Prefer installed script (shutil.which),
    else fallback to python -m module.
    Returns tuple (cmd_prefix_list, how) where how is 'exe' or 'module'.
    """
    import shutil
    exe = shutil.which(module_name)
    if exe:
        return [exe], "exe"
    # try script_name in repo tools (e.g. tools/sherlock/sherlock.py)
    if script_name:
        script_path = os.path.join(BASE_DIR, script_name)
        if os.path.exists(script_path):
            return [sys.executable, script_path], "script"
    # fallback to python -m module
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
# Views / pages
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

# SSE endpoint
@app.route("/sse/<tool>/<task_id>")
def sse(tool, task_id):
    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return Response(stream_with_context(sse_stream(task_id)), headers=headers)

# -------------------
# Utilities to read params (accept JSON or form)
# -------------------
def get_param_any(request_obj, name):
    # prefer JSON
    try:
        data = request_obj.get_json(silent=True)
    except Exception:
        data = None
    if data and name in data:
        return data.get(name)
    # fall back to form or values
    v = request_obj.form.get(name)
    if v:
        return v
    v = request_obj.values.get(name)
    return v

# -------------------
# Worker implementations
# -------------------
def _sherlock_worker(task_id, username):
    try:
        sse_put(task_id, "status", {"phase": "starting", "msg": "Iniciando Sherlock"})
        # choose invocation
        exe_prefix, how = detect_executable("sherlock", script_name=os.path.join("tools", "sherlock", "sherlock.py"))
        output_file = os.path.join(RUNS_DIR, f"{task_id}_sherlock.json")
        # Build command (ensure --json points to file)
        cmd = exe_prefix + [username, "--print-found", "--timeout", "8", "--json", output_file]
        sse_put(task_id, "log", {"line": f"CMD: {' '.join(cmd)}"})
        # stream output
        try:
            for line in run_command_stream(cmd):
                sse_put(task_id, "log", {"line": line})
        except FileNotFoundError:
            sse_put(task_id, "error", {"msg": "sherlock não encontrado no ambiente (ver requirements)."})
            return
        except subprocess.CalledProcessError as e:
            sse_put(task_id, "error", {"msg": f"Sherlock retornou erro (exit {e.returncode})"})
            return
        # try to read JSON output
        if os.path.exists(output_file):
            try:
                with open(output_file, "r", encoding="utf-8") as f:
                    text = f.read()
                # sherlock output can be lines of JSON or a single JSON; try to parse robustly
                try:
                    obj = json.loads(text)
                    sse_put(task_id, "result", {"type": "sherlock_output", "data": obj})
                except Exception:
                    # maybe multiple JSON lines - try last line
                    last = text.strip().splitlines()[-1]
                    try:
                        obj = json.loads(last)
                        sse_put(task_id, "result", {"type": "sherlock_output_last", "data": obj})
                    except Exception:
                        sse_put(task_id, "log", {"line": "Não foi possível parsear saída JSON do sherlock."})
            except Exception as e:
                sse_put(task_id, "log", {"line": f"Falha lendo {output_file}: {e}"})
        sse_put(task_id, "done", {"ok": True})
    except Exception as e:
        app.logger.exception("Erro no _sherlock_worker")
        sse_put(task_id, "error", {"msg": str(e)})
    finally:
        end_task(task_id)

def _vazamento_worker(task_id, email):
    try:
        sse_put(task_id, "status", {"phase": "starting", "msg": "Rodando checagem de vazamento (holehe)"})
        exe_prefix, how = detect_executable("holehe", script_name=None)
        # don't pass -j -s which can be unsupported; run simple invocation
        cmd = exe_prefix + [email]
        sse_put(task_id, "log", {"line": f"CMD: {' '.join(cmd)}"})
        try:
            for line in run_command_stream(cmd):
                sse_put(task_id, "log", {"line": line})
                # if line is JSON try to forward as result
                stripped = line.strip()
                if stripped.startswith("{") and stripped.endswith("}"):
                    try:
                        obj = json.loads(stripped)
                        sse_put(task_id, "result", {"type": "holehe", "data": obj})
                    except Exception:
                        pass
        except FileNotFoundError:
            sse_put(task_id, "error", {"msg": "holehe não encontrado no ambiente (ver requirements)."})
            return
        except subprocess.CalledProcessError as e:
            sse_put(task_id, "error", {"msg": f"Holehe retornou erro (exit {e.returncode})"})
            return

        sse_put(task_id, "done", {"ok": True})
    except Exception as e:
        app.logger.exception("Erro no _vazamento_worker")
        sse_put(task_id, "error", {"msg": str(e)})
    finally:
        end_task(task_id)

def _metaweb_worker(task_id, file_path=None, target=None):
    try:
        sse_put(task_id, "status", {"phase": "starting", "msg": "Coletando MetaWeb"})
        # If upload provided -> analyze file (hashes, size, basic header)
        if file_path:
            sse_put(task_id, "log", {"line": f"Analisando arquivo: {file_path}"})
            try:
                info = file_hashes(file_path)
                info["filename"] = os.path.basename(file_path)
                # try to get first bytes preview
                with open(file_path, "rb") as f:
                    preview = f.read(1024)
                info["preview_hex"] = preview[:256].hex()
                sse_put(task_id, "result", {"type": "file", "data": info})
            except Exception as e:
                sse_put(task_id, "log", {"line": f"Erro ao analisar arquivo: {e}"})
        elif target:
            # preserve old behavior: DNS, WHOIS, HTTP, robots, sitemap, wayback
            host = safe_domain(target)
            sse_put(task_id, "log", {"line": f"Consulta de alvo: {host}"})
            dns_info = {}
            try:
                import dns.resolver
                for rtype in ["A", "AAAA", "MX", "NS", "TXT"]:
                    try:
                        answers = dns.resolver.resolve(host, rtype)
                        dns_info[rtype] = [str(rdata) for rdata in answers]
                    except Exception:
                        dns_info[rtype] = []
            except Exception as e:
                sse_put(task_id, "log", {"line": f"dns/resolver não disponível: {e}"})
                dns_info = {}
            sse_put(task_id, "result", {"type": "dns", "data": dns_info})
            # whois
            try:
                import whois
                w = whois.whois(host)
                who = {k: (str(v) if not isinstance(v, (list, tuple)) else ", ".join(map(str, v))) for k, v in w.items()}
                sse_put(task_id, "result", {"type": "whois", "data": who})
            except Exception as e:
                sse_put(task_id, "log", {"line": f"WHOIS erro: {e}"})
            # http
            try:
                import requests
                r = requests.get(f"http://{host}", timeout=10, allow_redirects=True, headers={"User-Agent": "OSINT-Panel/1.0"})
                info = {"final_url": r.url, "status": r.status_code, "headers": dict(r.headers)}
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(r.text, "html.parser")
                    title = (soup.title.string or "").strip() if soup.title else ""
                    metas = {}
                    for m in soup.find_all("meta"):
                        name = (m.get("name") or m.get("property") or "").strip().lower()
                        if name:
                            metas[name] = m.get("content") or ""
                    info["title"] = title
                    info["meta"] = metas
                except Exception:
                    pass
                sse_put(task_id, "result", {"type": "http", "data": info})
            except Exception as e:
                sse_put(task_id, "log", {"line": f"HTTP erro: {e}"})
            # robots/sitemap/wayback also attempted (similar to previous implementation)
            try:
                import requests
                r = requests.get(f"http://{host}/robots.txt", timeout=8)
                sse_put(task_id, "result", {"type": "robots", "data": {"status": r.status_code, "text": r.text[:5000]}})
            except Exception as e:
                sse_put(task_id, "log", {"line": f"robots erro: {e}"})
            try:
                r = requests.get(f"http://{host}/sitemap.xml", timeout=8)
                sse_put(task_id, "result", {"type": "sitemap", "data": {"status": r.status_code, "text": r.text[:5000]}})
            except Exception as e:
                sse_put(task_id, "log", {"line": f"sitemap erro: {e}"})
            try:
                wb = requests.get(f"https://web.archive.org/cdx/search/cdx?url={host}&output=json&limit=5&filter=statuscode:200&from=2000", timeout=10)
                if wb.ok:
                    sse_put(task_id, "result", {"type": "wayback", "data": wb.json()})
            except Exception as e:
                sse_put(task_id, "log", {"line": f"wayback erro: {e}"})
        else:
            sse_put(task_id, "log", {"line": "Nenhum arquivo nem target fornecido."})
        sse_put(task_id, "done", {"ok": True})
    except Exception as e:
        app.logger.exception("Erro no _metaweb_worker")
        sse_put(task_id, "error", {"msg": str(e)})
    finally:
        end_task(task_id)

# -------------------
# HTTP endpoints to start tools (accept JSON OR form; metaweb accepts files)
# -------------------
@app.route("/sherlock/start", methods=["POST"])
def sherlock_start():
    # accept JSON or form data
    username = get_param_any(request, "username") or ""
    username = username.strip()
    if not username:
        return jsonify({"error": "username_required"}), 400
    task_id = start_task()
    th = threading.Thread(target=_sherlock_worker, args=(task_id, username), daemon=True)
    th.start()
    return jsonify({"task_id": task_id})

@app.route("/vazamento/start", methods=["POST"])
def vazamento_start():
    email = get_param_any(request, "email") or ""
    email = email.strip()
    if not email or "@" not in email:
        return jsonify({"error": "email_required"}), 400
    task_id = start_task()
    th = threading.Thread(target=_vazamento_worker, args=(task_id, email), daemon=True)
    th.start()
    return jsonify({"task_id": task_id})

@app.route("/metaweb/start", methods=["POST"])
def metaweb_start():
    # prefer file upload
    file = request.files.get("file")
    target = get_param_any(request, "target")
    if not file and not target:
        return jsonify({"error": "file_or_target_required"}), 400
    file_path = None
    if file:
        filename = secure_filename(file.filename)
        # create unique name
        unique = f"{int(time.time())}_{uuid.uuid4().hex}_{filename}"
        file_path = os.path.join(UPLOAD_DIR, unique)
        file.save(file_path)
        app.logger.info(f"metaweb saved upload {file_path}")
    task_id = start_task()
    th = threading.Thread(target=_metaweb_worker, kwargs={"task_id": task_id, "file_path": file_path, "target": (target or None)}, daemon=True)
    th.start()
    return jsonify({"task_id": task_id})

# favicon & health
@app.route("/favicon.ico")
def favicon():
    return ("", 204)

@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})

# factory (useful for gunicorn)
def create_app():
    return app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    # Note: for production use gunicorn as documented. For quick testing this is fine.
    app.logger.info("Starting app on port %s", port)
    app.run(host="0.0.0.0", port=port, debug=False)
