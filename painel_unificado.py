import os
import re
import json
import uuid
import queue
import time
import threading
import subprocess
from urllib.parse import urlparse

from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from flask_cors import CORS

import requests
from bs4 import BeautifulSoup
import dns.resolver
import whois

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

# ------------------- SSE infra -------------------
streams = {}  # task_id -> Queue[str]

def sse_put(task_id, event, data):
    try:
        q = streams[task_id]
    except KeyError:
        return
    payload = f"event: {event}\n" + "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"
    q.put(payload)

def sse_stream(task_id):
    q = streams.get(task_id)
    if q is None:
        yield "event: error\ndata: \"task_not_found\"\n\n"
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
        pass

def start_task():
    task_id = str(uuid.uuid4())
    streams[task_id] = queue.Queue()
    return task_id

def end_task(task_id):
    time.sleep(0.2)
    streams.pop(task_id, None)

# ------------------- Helpers -------------------
def safe_domain(input_str):
    parsed = urlparse(input_str if re.match(r"^https?://", input_str) else f"http://{input_str}")
    host = parsed.hostname or input_str
    return host

def run_command_stream(cmd_list, cwd=None, env=None):
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
    try:
        for line in proc.stdout:
            yield line.rstrip("\n")
        proc.wait()
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd_list)
    finally:
        try: proc.stdout.close()
        except Exception: pass

# ------------------- Views -------------------
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

# ------------------- SSE endpoints -------------------
@app.route("/sse/<tool>/<task_id>")
def sse(tool, task_id):
    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return Response(stream_with_context(sse_stream(task_id)), headers=headers)

# ------------------- Start endpoints -------------------
@app.route("/sherlock/start", methods=["POST"])
def sherlock_start():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    if not username:
        return jsonify({"error": "username_required"}), 400

    task_id = start_task()
    t = threading.Thread(target=_sherlock_worker, args=(task_id, username), daemon=True)
    t.start()
    return jsonify({"task_id": task_id})

def _sherlock_worker(task_id, username):
    try:
        sse_put(task_id, "status", {"phase": "starting", "msg": "Iniciando Sherlock"})
        cmd = ["python3", "-m", "sherlock", username, "--print-found", "--timeout", "8", "--json"]
        for line in run_command_stream(cmd):
            sse_put(task_id, "log", {"line": line})
            ls = line.strip()
            if ls.startswith("{") and ls.endswith("}"):
                try:
                    result_json = json.loads(ls)
                    hits = result_json.get("sites", {})
                    found = []
                    for k, v in hits.items():
                        if isinstance(v, dict):
                            st = v.get("status") or {}
                            if st.get("code") == 200:
                                found.append(k)
                    sse_put(task_id, "result", {"found_count": len(found), "found_sites": found[:50]})
                except Exception:
                    pass
        sse_put(task_id, "done", {"ok": True})
    except subprocess.CalledProcessError as e:
        sse_put(task_id, "error", {"msg": f"Falha no sherlock (exit {e.returncode})"})
    except Exception as e:
        sse_put(task_id, "error", {"msg": f"Erro: {e}"})
    finally:
        end_task(task_id)

@app.route("/vazamento/start", methods=["POST"])
def vazamento_start():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    if not email or "@" not in email:
        return jsonify({"error": "email_required"}), 400

    task_id = start_task()
    t = threading.Thread(target=_vazamento_worker, args=(task_id, email), daemon=True)
    t.start()
    return jsonify({"task_id": task_id})

def _vazamento_worker(task_id, email):
    try:
        sse_put(task_id, "status", {"phase": "starting", "msg": "Rodando holehe (checagem de vazamentos por e-mail)"})
        cmd = ["holehe", email, "-j", "--no-color", "-s"]
        for line in run_command_stream(cmd):
            sse_put(task_id, "log", {"line": line})
            ls = line.strip()
            if ls.startswith("{") and ls.endswith("}"):
                try:
                    obj = json.loads(ls)
                    sse_put(task_id, "result", obj)
                except Exception:
                    pass
        sse_put(task_id, "done", {"ok": True})
    except FileNotFoundError:
        sse_put(task_id, "error", {"msg": "holehe não instalado no ambiente. Confirme instalação em requirements.txt"})
    except subprocess.CalledProcessError as e:
        sse_put(task_id, "error", {"msg": f"Falha no holehe (exit {e.returncode})"})
    except Exception as e:
        sse_put(task_id, "error", {"msg": f"Erro: {e}"})
    finally:
        end_task(task_id)

@app.route("/metaweb/start", methods=["POST"])
def metaweb_start():
    data = request.get_json(silent=True) or {}
    target = (data.get("target") or "").strip()
    if not target:
        return jsonify({"error": "target_required"}), 400

    task_id = start_task()
    t = threading.Thread(target=_metaweb_worker, args=(task_id, target), daemon=True)
    t.start()
    return jsonify({"task_id": task_id})

def _metaweb_worker(task_id, target):
    try:
        sse_put(task_id, "status", {"phase": "starting", "msg": "Coletando metadados da web"})
        host = safe_domain(target)
        # DNS
        dns_info = {}
        for rtype in ["A", "AAAA", "MX", "NS", "TXT"]:
            try:
                answers = dns.resolver.resolve(host, rtype)
                dns_info[rtype] = [str(rdata) for rdata in answers]
            except Exception:
                dns_info[rtype] = []
        sse_put(task_id, "result", {"type": "dns", "data": dns_info})

        # WHOIS
        try:
            w = whois.whois(host)
            who = {k: (str(v) if not isinstance(v, (list, tuple)) else ", ".join(map(str, v))) for k, v in w.items()}
            sse_put(task_id, "result", {"type": "whois", "data": who})
        except Exception as e:
            sse_put(task_id, "log", {"line": f"WHOIS erro: {e}"})

        # HTTP GET
        url = f"http://{host}"
        try:
            r = requests.get(url, timeout=10, allow_redirects=True, headers={"User-Agent": "OSINT-Panel/1.0"})
            info = {
                "final_url": r.url,
                "status": r.status_code,
                "headers": dict(r.headers),
            }
            try:
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

        # robots.txt
        try:
            r = requests.get(f"http://{host}/robots.txt", timeout=8)
            sse_put(task_id, "result", {"type": "robots", "data": {"status": r.status_code, "text": r.text[:5000]}})
        except Exception as e:
            sse_put(task_id, "log", {"line": f"robots erro: {e}"})

        # sitemap.xml
        try:
            r = requests.get(f"http://{host}/sitemap.xml", timeout=8)
            sse_put(task_id, "result", {"type": "sitemap", "data": {"status": r.status_code, "text": r.text[:5000]}})
        except Exception as e:
            sse_put(task_id, "log", {"line": f"sitemap erro: {e}"})

        # Wayback snapshots
        try:
            wb = requests.get(f"https://web.archive.org/cdx/search/cdx?url={host}&output=json&limit=5&filter=statuscode:200&from=2000", timeout=10)
            if wb.ok:
                sse_put(task_id, "result", {"type": "wayback", "data": wb.json()})
        except Exception as e:
            sse_put(task_id, "log", {"line": f"wayback erro: {e}"})

        sse_put(task_id, "done", {"ok": True})
    except Exception as e:
        sse_put(task_id, "error", {"msg": f"Erro: {e}"})
    finally:
        end_task(task_id)

@app.route("/favicon.ico")
def favicon():
    return ("", 204)

@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})

def create_app():
    return app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

