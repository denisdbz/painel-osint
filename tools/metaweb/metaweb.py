#!/usr/bin/env python3
import argparse
import os
import sys
import subprocess
import hashlib
import mimetypes

def file_hashes(path):
    hashes = {"md5": hashlib.md5(), "sha1": hashlib.sha1(), "sha256": hashlib.sha256()}
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            for h in hashes.values():
                h.update(chunk)
    return {k: v.hexdigest() for k, v in hashes.items()}

def run_tool(cmd, label):
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in proc.stdout:
            print(f"[{label}] {line.strip()}")
        for line in proc.stderr:
            print(f"[{label} ERR] {line.strip()}")
        proc.wait()
    except FileNotFoundError:
        print(f"[WARN] {cmd[0]} não encontrado, pulando {label}.")

def analyze_file(path):
    print(f"[INFO] Analisando arquivo: {path}")
    print(f"[INFO] Tamanho: {os.path.getsize(path)} bytes")

    # Hashes
    hashes = file_hashes(path)
    for k, v in hashes.items():
        print(f"[HASH] {k}: {v}")

    mime, _ = mimetypes.guess_type(path)
    print(f"[MIME] {mime or 'desconhecido'}")

    # ExifTool (metadados avançados)
    run_tool(["exiftool", path], "EXIF")

    # MediaInfo (áudio/vídeo)
    run_tool(["mediainfo", path], "MEDIAINFO")

def main():
    parser = argparse.ArgumentParser(description="MetaWeb - análise de metadados")
    parser.add_argument("--file", help="Arquivo local para análise")
    parser.add_argument("--target", help="URL para download e análise temporária")
    args = parser.parse_args()

    if args.file:
        if not os.path.exists(args.file):
            print(f"[ERRO] Arquivo não encontrado: {args.file}")
            sys.exit(1)
        analyze_file(args.file)
    elif args.target:
        import requests, tempfile
        print(f"[INFO] Baixando {args.target}...")
        r = requests.get(args.target, timeout=30)
        if r.status_code != 200:
            print(f"[ERRO] Falha no download: HTTP {r.status_code}")
            sys.exit(1)
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(r.content)
        tmp.close()
        print(f"[INFO] Arquivo baixado em {tmp.name}")
        analyze_file(tmp.name)
        os.unlink(tmp.name)
    else:
        print("[ERRO] Forneça --file ou --target")
        sys.exit(1)

if __name__ == "__main__":
    main()
