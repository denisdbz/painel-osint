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
            result = subprocess.run(
                ["usr/local/bin/phoneinfoga", "scan", "-n", numero, "-o", json_path, "-f", "json"],
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode != 0:
                return render_template("phoneinfoga.html", erro=f"Erro ao executar PhoneInfoga: {result.stderr}")

            with open(json_path, "r") as f:
                dados = json.load(f)

            historico_entry = {
                "tipo": "phoneinfoga",
                "alvo": numero,
                "arquivo": json_path,
                "data": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            historico_file = os.path.join(pasta_relatorios, "historico.json")
            if os.path.exists(historico_file):
                with open(historico_file, "r") as f:
                    historico = json.load(f)
            else:
                historico = []

            historico.append(historico_entry)

            with open(historico_file, "w") as f:
                json.dump(historico, f, indent=2)

            return render_template("relatorio_phoneinfoga.html", numero=numero, dados=dados)

        except Exception as e:
            return render_template("phoneinfoga.html", erro=f"Ocorreu um erro: {str(e)}")

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
    """
    Insere um registro de histórico no DB.
    - params_dict e result_dict são armazenados como JSON strings.
    - raw_output é truncado para MAX_OUTPUT_CHARS.
    """
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
    """
    Snapshot inicial (ou genérico) no histórico.
    Reaproveita o task_id se recebido, senão cria um novo e retorna.
    """
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
    # deixa o worker emitir "done" / "error". Aqui só aguardamos um instante.
    time.sleep(0.2)
    # NÃO removemos a fila aqui para não quebrar quem ainda está drenando os últimos eventos.
    # A remoção segura acontece no finally do sse_stream.
    app.logger.info("end_task %s", task_id)

def sse_put(task_id, event, data):
    q = streams.get(task_id)
    if not q:
        app.logger.debug("sse_put: no stream %s", task_id)
        return
    payload = f"event: {event}\n" + "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"
    q.put(payload)

def sse_stream(task_id):
    """
    - Encerra o stream automaticamente quando receber 'event: done' ou 'event: error'.
    - Envia ping direto ao cliente (sem passar por fila) caso não haja mensagens.
    - Faz cleanup do streams[task_id] com segurança no finally.
    """
    q = streams.get(task_id)
    if q is None:
        yield "event: error\n" + "data: " + json.dumps({"msg": "task_not_found"}) + "\n\n"
        return
    try:
        last_ping = 0
        while True:
            try:
                chunk = q.get(timeout=0.25)
                # repassa ao cliente
                yield chunk
                # se o worker sinalizou término/erro, encerra o SSE
                if chunk.startswith("event: done") or chunk.startswith("event: error"):
                    break
            except queue.Empty:
                now = time.time()
                if now - last_ping > 15:
                    # heartbeat direto para o cliente, independente do estado da fila
                    yield "event: ping\n" + "data: " + json.dumps({"t": now}) + "\n\n"
                    last_ping = now
    except GeneratorExit:
        app.logger.debug("SSE client disconnected")
    except Exception:
        app.logger.exception("sse_stream exception")
    finally:
        # limpeza segura: remove a fila associada (se ainda existir)
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
                script_name=os.path.join("tools", "sherlock", "sherlock.py"),
            )
            cwd = None

        cmd = exe_prefix + [username, "--print-found", "--timeout", "15"]
        sse_put(task_id, "log", {"line": f"CMD: {' '.join(cmd)}"})
        url_pattern = re.compile(r"(https?://\S+)")
        try:
            for line in run_command_stream(cmd, cwd=cwd):
                line_with_links = url_pattern.sub(
                    r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>',
                    line,
                )
                lines.append(line_with_links)
                # estimate found items (simple heuristic: lines with http)
                if "http" in line.lower():
                    found_count += 1
                sse_put(task_id, "log", {"line": line_with_links})
        except FileNotFoundError:
            sse_put(task_id, "error", {"msg": "sherlock não encontrado no ambiente."})
            record_history(
                task_id,
                "sherlock",
                {"username": username},
                {"found": 0, "note": "not found"},
                "\n".join(lines),
                status="error",
            )
            return
        except subprocess.CalledProcessError as e:
            sse_put(task_id, "error", {"msg": f"Sherlock retornou erro (exit {e.returncode})"})
            record_history(
                task_id,
                "sherlock",
                {"username": username},
                {"found": found_count, "error": f"exit {e.returncode}"},
                "\n".join(lines),
                status="error",
            )
            return

        sse_put(task_id, "result", {"type": "sherlock_summary", "found": found_count})
        sse_put(task_id, "done", {"ok": True})
        # grava histórico
        record_history(
            task_id,
            "sherlock",
            {"username": username},
            {"found": found_count},
            "\n".join(lines),
            status="ok",
        )
    except Exception:
        app.logger.exception("Erro no _sherlock_worker")
        sse_put(task_id, "error", {"msg": "Erro interno no worker sherlock"})
        record_history(
            task_id,
            "sherlock",
            {"username": username},
            {"error": "internal"},
            "\n".join(lines),
            status="error",
        )
    finally:
        end_task(task_id)

def _vazamento_worker(task_id, email=None, password=None):
    lines = []
    try:
        url_pattern = re.compile(r"(https?://\S+)")
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
                    record_history(
                        task_id,
                        "vazamento_password",
                        {"password_hash_prefix": prefix},
                        {"error": f"status {r.status_code}"},
                        "\n".join(lines),
                        status="error",
                    )
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
                    sse_put(task_id, "log", {"line": "[OK] Senha não encontrada nos dumps conhecidos."})
                lines.append(f"HIBP count: {count}")
                record_history(
                    task_id,
                    "vazamento_password",
                    {"password_prefix": prefix},
                    {"compromised": count > 0, "count": count},
                    "\n".join(lines),
                    status="ok",
                )
            except Exception as e:
                app.logger.exception("Erro HIBP")
                sse_put(task_id, "error", {"msg": f"Erro HIBP: {e}"})
                record_history(
                    task_id,
                    "vazamento_password",
                    {"error": str(e)},
                    {},
                    "\n".join(lines),
                    status="error",
                )
        elif email:
            sse_put(task_id, "status", {"phase": "starting", "msg": "Rodando checagem de vazamento (holehe)"})
            exe_prefix, how = detect_executable("holehe", script_name=None)
            cmd = exe_prefix + [email]
            sse_put(task_id, "log", {"line": f"CMD: {' '.join(cmd)}"})
            try:
                for line in run_command_stream(cmd):
                    # ignora linhas que são só porcentagem
                    if re.fullmatch(r"\d{1,3}%", line.strip()):
                        continue
                    line_with_links = url_pattern.sub(
                        r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>',
                        line,
                    )
                    lines.append(line_with_links)
                    sse_put(task_id, "log", {"line": line_with_links})
                    stripped = line.strip()
                    # tenta detectar JSON linha única do holehe
                    if stripped.startswith("{") and stripped.endswith("}"):
                        try:
                            obj = json.loads(stripped)
                            sse_put(task_id, "result", {"type": "holehe", "data": obj})
                        except Exception:
                            pass
            except FileNotFoundError:
                sse_put(task_id, "error", {"msg": "holehe não encontrado no ambiente."})
                record_history(
                    task_id,
                    "vazamento_holehe",
                    {"email": email},
                    {"error": "holehe_not_found"},
                    "\n".join(lines),
                    status="error",
                )
                return
            except subprocess.CalledProcessError as e:
                sse_put(task_id, "error", {"msg": f"Holehe retornou erro (exit {e.returncode})"})
                record_history(
                    task_id,
                    "vazamento_holehe",
                    {"email": email},
                    {"error": f"exit {e.returncode}"},
                    "\n".join(lines),
                    status="error",
                )
                return

            sse_put(task_id, "done", {"ok": True})
            # grava histórico com output (truncado internamente)
            record_history(
                task_id,
                "vazamento_holehe",
                {"email": email},
                {"note": "holehe_done"},
                "\n".join(lines),
                status="ok",
            )
        else:
            sse_put(task_id, "error", {"msg": "Nenhum email ou senha fornecido."})
            record_history(
                task_id,
                "vazamento",
                {"error": "no_param"},
                {},
                "\n".join(lines),
                status="error",
            )
            return
    except Exception:
        app.logger.exception("Erro no _vazamento_worker")
        sse_put(task_id, "error", {"msg": "Erro interno no worker vazamento"})
        record_history(
            task_id,
            "vazamento",
            {"error": "internal"},
            {},
            "\n".join(lines),
            status="error",
        )
    finally:
        end_task(task_id)

def _metaweb_worker(task_id, file_path=None, target=None):
    lines = []
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
                lines.append(f"FILE: {info.get('filename')} size={info.get('size')}")
            except Exception as e:
                sse_put(task_id, "log", {"line": f"Erro ao calcular hashes: {e}"})
                lines.append(f"hash_error: {e}")

            # --- exiftool ---
            try:
                for line in run_command_stream(["exiftool", file_path]):
                    lines.append("[EXIF] " + line)
                    sse_put(task_id, "log", {"line": line})
            except FileNotFoundError:
                sse_put(task_id, "log", {"line": "exiftool indisponível."})
            except Exception:
                sse_put(task_id, "log", {"line": "exiftool erro."})

            # --- mediainfo ---
            try:
                for line in run_command_stream(["mediainfo", file_path]):
                    lines.append("[MEDIA] " + line)
                    sse_put(task_id, "log", {"line": line})
            except FileNotFoundError:
                sse_put(task_id, "log", {"line": "mediainfo indisponível."})
            except Exception:
                sse_put(task_id, "log", {"line": "mediainfo erro."})

            # ... outros checks similares (file, pdfinfo, oletools, hachoir, ffprobe, strings) ...
            sse_put(task_id, "done", {"ok": True})
            record_history(
                task_id,
                "metaweb_file",
                {"file": os.path.basename(file_path)},
                {"note": "metaweb done"},
                "\n".join(lines),
                status="ok",
            )
        elif target:
            host = safe_domain(target)
            sse_put(task_id, "log", {"line": f"Consulta de alvo: {host}"})
            # você pode adicionar checks adicionais (whois, http, etc.)
            lines.append(f"target: {host}")
            sse_put(task_id, "done", {"ok": True})
            record_history(
                task_id,
                "metaweb_target",
                {"target": target},
                {"note": "metaweb target done"},
                "\n".join(lines),
                status="ok",
            )
        else:
            sse_put(task_id, "error", {"msg": "Nenhum arquivo nem target fornecido."})
            record_history(
                task_id,
                "metaweb",
                {"error": "no_param"},
                {},
                "\n".join(lines),
                status="error",
            )

    except Exception:
        app.logger.exception("Erro no _metaweb_worker")
        sse_put(task_id, "error", {"msg": "Erro interno no worker metaweb"})
        record_history(
            task_id,
            "metaweb",
            {"error": "internal"},
            {},
            "\n".join(lines),
            status="error",
        )
    finally:
        end_task(task_id)

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
        # "Connection": "keep-alive",  # opcional, alguns proxies adicionam automaticamente
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

    # snapshot inicial no histórico
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

    # Decide o "tool" mais específico conforme o parâmetro
    tool_name = (
        "vazamento_password"
        if password and not email
        else ("vazamento_holehe" if email and not password else "vazamento")
    )

    # snapshot inicial (sem vazar senha)
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

    # snapshot inicial
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
    # aceita token via header X-Admin-Token ou query param ?token=...
    token_req = request.headers.get("X-Admin-Token") or request.args.get("token")
    if not token_req or token_req != token_env:
        return False
    return True

@app.route("/admin/history")
def admin_history_page():
    if not check_admin_token():
        # não expor nada se token incorreto
        return abort(401)
    rows = fetch_history(limit=500)
    # HTML simples — você pode melhorar o template se quiser
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

# CORREÇÃO: rota correta com <int:hid>
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
    # debug False para produção
    app.run(host="0.0.0.0", port=port, debug=False)
