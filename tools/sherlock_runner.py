import subprocess
import sys
import os
import json
from datetime import datetime


def run_sherlock(username, include_nsfw=False):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    results_dir = os.path.join(base_dir, "static", "relatorios")
    json_dir = os.path.join(base_dir, "leak_check_results")

    os.makedirs(results_dir, exist_ok=True)
    os.makedirs(json_dir, exist_ok=True)

    # Nome da pasta com data/hora
    data_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    pasta = os.path.join(results_dir, data_str)
    os.makedirs(pasta, exist_ok=True)

    relatorio_json = os.path.join(json_dir, "ultimo_relatorio_sherlock.json")

    # Caminho para o sherlock.py
    sherlock_path = os.path.join(
        os.path.dirname(__file__), "sherlock", "sherlock_project", "sherlock.py"
    )

    # Monta comando
    cmd = [sys.executable, sherlock_path, username, "--print-found"]
    if include_nsfw:
        cmd.append("--nsfw")

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    stdout, stderr = process.communicate()

    resultados = {}
    for line in stdout.splitlines():
        if "http" in line:
            try:
                # Exemplo de linha:
                # [+] GitHub: https://github.com/fulano
                site_name = line.split(":", 1)[0].replace("[+]", "").strip()
                link = line.split(":", 1)[1].strip()

                if link.startswith("http"):
                    html_path = f"{site_name}.html"
                    with open(
                        os.path.join(pasta, html_path), "w", encoding="utf-8"
                    ) as f:
                        f.write(f"<h2>Resultado para {username} em {site_name}</h2>")
                        f.write(
                            f"<p><b>Perfil encontrado:</b> "
                            f"<a href='{link}' target='_blank'>{link}</a></p>"
                        )
                    resultados[site_name] = {
                        # 🔹 removida a barra inicial para evitar erro [object Object]
                        "arquivo": f"static/relatorios/{data_str}/{html_path}",
                        "link": str(link)
                    }
            except Exception:
                continue

    # Salva o JSON de índice
    with open(relatorio_json, "w", encoding="utf-8") as f:
        json.dump(
            {
                "username": username,
                "data": data_str,
                "resultados": resultados,
                "stdout": stdout,
                "stderr": stderr,
            },
            f,
            indent=2,
            ensure_ascii=False
        )

    return stdout, stderr, relatorio_json, pasta


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python sherlock_runner.py <username> [--nsfw]")
        sys.exit(1)

    include_nsfw = "--nsfw" in sys.argv
    run_sherlock(sys.argv[1], include_nsfw=include_nsfw)
