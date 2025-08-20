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
from pathlib import Path

from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from flask_cors import CORS

# ----------------------
# Config / paths
# ----------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
RUNS_DIR = os.path.join(BASE_DIR, "runs")
# NOTE: SHERLOCK_PATH kept for backwards compatibility but we prefer tools/sherlock local layout
SHERLOCK_PATH = os.path.join(BASE_DIR, "sherlock", "sherlock.py")
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
    app.logger.info("start_task %s", task_id)
    return task_id

def end_task(task_id):
    time.sleep(0.2)
    streams.pop(task_id, None)
    app.logger.info("end_task %s", task_id)

def sse_put(task_id, event, data):
    """
    Push an SSE event (event name + JSON-able data) to task queue.
    data must be JSON-serializable (often a dict with 'line' or payload).
    """
    q = streams.get(task_id)
    if not q:
        app.logger.debug("sse_put: no stream %s", task_id)
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
                if now - last_ping > 15:
                    sse_put(task_id, "ping", {"t": now})
                    last_ping = now
    except GeneratorExit:
        app.logger.debug("SSE client disconnected")
    except Exception:
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
    Raises FileNotFoundError if binary missing.
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
    except FileNotFoundError:
        raise

    try:
        for line in iter(proc.stdout.readline, ""):
            if line is None:
                break
            yield line.rstrip("\n")
        proc.stdout.close()
        ret = proc.wait()
        if ret != 0:
            # still may have printed useful lines; raise so caller can handle the error
            raise subprocess.CalledProcessError(ret, cmd_list)
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass

def detect_executable(module_name, script_name=None):
    """
    Return an executable command list. Prefer installed script (shutil.which),
    else fallback to local script (script_name) or python -m module.
    Returns tuple (cmd_prefix_list, how) where how is 'exe'/'script'/'module'.
    """
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
    return Response(stream_with_context(sse_stream(task_id)), mimetype="text/event-stream")

# -------------------
# Utilities to read params (accept JSON or form)
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
# Worker implementations
# -------------------
def _sherlock_worker(task_id, username):
    """
    Run Sherlock in streaming mode (--print-found). Prefer local site-database to avoid remote download.
    """
    try:
        sse_put(task_id, "status", {"phase": "starting", "msg": "Iniciando Sherlock"})
        # Prefer local sherlock main if present (tools/sherlock/sherlock_project/__main__.py)
        sherlock_dir = os.path.join(BASE_DIR, "tools", "sherlock")
        local_main = os.path.join(sherlock_dir, "sherlock_project", "__main__.py")
        cwd = sherlock_dir

        if os.path.exists(local_main):
            exe_prefix = [sys.executable, "-m", "sherlock_project.__main__"]
            how = "local-main"
        else:
            # fallback: detect installed sherlock binary or local script
            exe_prefix, how = detect_executable("sherlock", script_name=os.path.join("tools", "sherlock", "sherlock.py"))
            cwd = None  # use default

        # build command (removido --site-database, compatível com nova versão)
        cmd = exe_prefix + [username, "--print-found", "--timeout", "8"]
        sse_put(task_id, "log", {"line": f"CMD: {' '.join(cmd)}"})

        # --- NOVO: transformar URLs em links clicáveis ---
        url_pattern = re.compile(r"(https?://\S+)")
        try:
            for line in run_command_stream(cmd, cwd=cwd):
                # converte URLs para <a href="...">...</a>
                line_with_links = url_pattern.sub(
                    r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>',
                    line,
                )
                sse_put(task_id, "log", {"line": line_with_links})
        except FileNotFoundError:
            sse_put(task_id, "error", {"msg": "sherlock não encontrado no ambiente (ver requisitos)."})
            return
        except subprocess.CalledProcessError as e:
            sse_put(task_id, "error", {"msg": f"Sherlock retornou erro (exit {e.returncode})"})
            return

        sse_put(task_id, "done", {"ok": True})
    except Exception:
        app.logger.exception("Erro no _sherlock_worker")
        sse_put(task_id, "error", {"msg": "Erro interno no worker sherlock"})
    finally:
        end_task(task_id)

def _vazamento_worker(task_id, email=None, password=None):
    """
    Vazamento: if password -> HIBP k-anonymity; if email -> holehe (if available).
    """
    try:
        if password:
            sse_put(task_id, "status", {"phase": "starting", "msg": "Verificando senha (HIBP)"})
            try:
                import requests
                sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
                prefix, suffix = sha1[:5], sha1[5:]
                url = f"https://api.pwnedpasswords.com/range/{prefix}"
                r = requests.get(url, timeout=10)
                if r.status_code != 200:
                    sse_put(task_id, "error", {"msg": f"HIBP retornou status {r.status_code}"})
                    return
                count = 0
                for line in r.text.splitlines():
                    if ":" not in line:
                        continue
                    h, c = line.split(":")
                    if h == suffix:
                        try:
                            count = int(c.strip())
                        except Exception:
                            count = 1
                        break
                if count > 0:
                    sse_put(task_id, "result", {"type": "password", "compromised": True, "count": count})
                    sse_put(task_id, "log", {"line": f"[ALERTA] Senha encontrada {count} vezes em dumps públicos."})
                else:
                    sse_put(task_id, "result", {"type": "password", "compromised": False})
                    sse_put(task_id, "log", {"line": "[OK] Senha não encontrada nos dumps conhecidos (HIBP)."})
            except Exception as e:
                sse_put(task_id, "error", {"msg": f"Erro HIBP: {e}"})
        elif email:
            sse_put(task_id, "status", {"phase": "starting", "msg": "Rodando checagem de vazamento (holehe)"})
            exe_prefix, how = detect_executable("holehe", script_name=None)
            cmd = exe_prefix + [email]
            sse_put(task_id, "log", {"line": f"CMD: {' '.join(cmd)}"})
            try:
                for line in run_command_stream(cmd):
                    sse_put(task_id, "log", {"line": line})
                    stripped = line.strip()
                    if stripped.startswith("{") and stripped.endswith("}"):
                        try:
                            obj = json.loads(stripped)
                            sse_put(task_id, "result", {"type": "holehe", "data": obj})
                        except Exception:
                            pass
            except FileNotFoundError:
                sse_put(task_id, "error", {"msg": "holehe não encontrado no ambiente (ver requirements)."})
                sse_put(task_id, "log", {"line": "Se quiser checar e-mails, instale 'holehe' ou use APIs (Dehashed / HIBP Enterprise)."})
                return
            except subprocess.CalledProcessError as e:
                sse_put(task_id, "error", {"msg": f"Holehe retornou erro (exit {e.returncode})"})
                return
        else:
            sse_put(task_id, "error", {"msg": "Nenhum email ou senha fornecido."})
            return

        sse_put(task_id, "done", {"ok": True})
    except Exception:
        app.logger.exception("Erro no _vazamento_worker")
        sse_put(task_id, "error", {"msg": "Erro interno no worker vazamento"})
    finally:
        end_task(task_id)

def _metaweb_worker(task_id, file_path=None, target=None):
    """
    MetaWeb: analyze uploaded file (hashes + exiftool/mediainfo/file when available),
    or legacy network checks when target provided.
    """
    try:
        sse_put(task_id, "status", {"phase": "starting", "msg": "Coletando MetaWeb"})
        if file_path:
            sse_put(task_id, "log", {"line": f"Analisando arquivo: {file_path}"})
            try:
                info = file_hashes(file_path)
                info["filename"] = os.path.basename(file_path)
                with open(file_path, "rb") as f:
                    preview = f.read(1024)
                info["preview_hex"] = preview[:256].hex()
                sse_put(task_id, "result", {"type": "file", "data": info})
            except Exception as e:
                sse_put(task_id, "log", {"line": f"Erro ao analisar arquivo: {e}"})

            # exiftool
            try:
                for line in run_command_stream(["exiftool", file_path]):
                    sse_put(task_id, "log", {"line": line})
            except FileNotFoundError:
                sse_put(task_id, "log", {"line": "exiftool não está instalado no ambiente."})
            except subprocess.CalledProcessError as e:
                sse_put(task_id, "log", {"line": f"exiftool retornou erro (exit {e.returncode})"})

            # mediainfo
            try:
                for line in run_command_stream(["mediainfo", file_path]):
                    sse_put(task_id, "log", {"line": line})
            except FileNotFoundError:
                sse_put(task_id, "log", {"line": "mediainfo não está instalado no ambiente."})
            except subprocess.CalledProcessError as e:
                sse_put(task_id, "log", {"line": f"mediainfo retornou erro (exit {e.returncode})"})

            # file -b
            try:
                for line in run_command_stream(["file", "-b", file_path]):
                    sse_put(task_id, "log", {"line": line})
            except FileNotFoundError:
                sse_put(task_id, "log", {"line": "utilitário 'file' não está instalado no ambiente."})
            except subprocess.CalledProcessError as e:
                sse_put(task_id, "log", {"line": f"'file' retornou erro (exit {e.returncode})"})
        elif target:
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
            except Exception:
                sse_put(task_id, "log", {"line": "dns/resolver indisponível"})
                dns_info = {}
            sse_put(task_id, "result", {"type": "dns", "data": dns_info})
            # whois
            try:
                import whois
                w = whois.whois(host)
                who = {k: (str(v) if not isinstance(v, (list, tuple)) else ", ".join(map(str, v))) for k, v in w.items()}
                sse_put(task_id, "result", {"type": "whois", "data": who})
            except Exception:
                sse_put(task_id, "log", {"line": "WHOIS erro"})
            # http + meta
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
            except Exception:
                sse_put(task_id, "log", {"line": "HTTP erro"})
            # robots/sitemap/wayback
            try:
                r = requests.get(f"http://{host}/robots.txt", timeout=8)
                sse_put(task_id, "result", {"type": "robots", "data": {"status": r.status_code, "text": r.text[:5000]}})
            except Exception:
                sse_put(task_id, "log", {"line": "robots erro"})
            try:
                r = requests.get(f"http://{host}/sitemap.xml", timeout=8)
                sse_put(task_id, "result", {"type": "sitemap", "data": {"status": r.status_code, "text": r.text[:5000]}})
            except Exception:
                sse_put(task_id, "log", {"line": "sitemap erro"})
            try:
                wb = requests.get(f"https://web.archive.org/cdx/search/cdx?url={host}&output=json&limit=5&filter=statuscode:200&from=2000", timeout=10)
                if wb.ok:
                    sse_put(task_id, "result", {"type": "wayback", "data": wb.json()})
            except Exception:
                sse_put(task_id, "log", {"line": "wayback erro"})
        else:
            sse_put(task_id, "log", {"line": "Nenhum arquivo nem target fornecido."})

        sse_put(task_id, "done", {"ok": True})
    except Exception:
        app.logger.exception("Erro no _metaweb_worker")
        sse_put(task_id, "error", {"msg": "Erro interno no worker metaweb"})
    finally:
        end_task(task_id)

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
    th = threading.Thread(target=_sherlock_worker, args=(task_id, username), daemon=True)
    th.start()
    return jsonify({"task_id": task_id})

@app.route("/vazamento/start", methods=["POST"])
def vazamento_start():
    # accepts either 'email' or 'password' form field (or JSON)
    email = get_param_any(request, "email")
    password = get_param_any(request, "password")
    if not email and not password:
        return jsonify({"error": "email_or_password_required"}), 400
    task_id = start_task()
    th = threading.Thread(target=_vazamento_worker, args=(task_id, email, password), daemon=True)
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
    app.logger.info("Starting app on port %s", port)
    app.run(host="0.0.0.0", port=port, debug=False)
