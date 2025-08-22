#!/usr/bin/env python3

import subprocess
import json
import argparse
import os

# Caminho para o executável do ExifTool (pode variar)
EXIFTOOL_PATH = "exiftool"

def analyze_file(file_path):
    """
    Analisa um arquivo local usando ExifTool.
    """
    if not os.path.exists(file_path):
        print(f"[ERROR] File not found: {file_path}")
        return

    try:
        print(f"[STATUS] Analisando arquivo: {file_path}")
        # Comando para executar o exiftool e obter a saída em formato JSON
        cmd = [EXIFTOOL_PATH, "-json", "-f", "-G", file_path]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"[ERROR] ExifTool failed with code {result.returncode}")
            print(result.stderr)
            return

        metadata = json.loads(result.stdout)
        
        print(f"[RESULTADO] Metadados encontrados para '{os.path.basename(file_path)}':")
        print(json.dumps(metadata, indent=2, ensure_ascii=False))

    except FileNotFoundError:
        print(f"[ERROR] ExifTool not found. Please install it.")
        print("  - On Debian/Ubuntu: sudo apt-get install libimage-exiftool-perl")
    except Exception as e:
        print(f"[EXCEPTION] An error occurred: {e}")
    
def analyze_target(target_url):
    """
    Analisa uma URL usando ExifTool.
    """
    print(f"[STATUS] Analisando URL: {target_url}")
    
    try:
        # ExifTool pode analisar URLs diretamente
        cmd = [EXIFTOOL_PATH, "-json", "-f", "-G", target_url]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"[ERROR] ExifTool failed with code {result.returncode}")
            print(result.stderr)
            return

        metadata = json.loads(result.stdout)
        
        print(f"[RESULTADO] Metadados encontrados para '{target_url}':")
        print(json.dumps(metadata, indent=2, ensure_ascii=False))

    except FileNotFoundError:
        print(f"[ERROR] ExifTool not found. Please install it.")
    except Exception as e:
        print(f"[EXCEPTION] An error occurred: {e}")


def main():
    parser = argparse.ArgumentParser(description="Analisador de metadados MetaWeb.")
    parser.add_argument("--file", help="Caminho para o arquivo a ser analisado.")
    parser.add_argument("--target", help="URL do arquivo a ser analisado.")
    
    args = parser.parse_args()

    if args.file:
        analyze_file(args.file)
    elif args.target:
        analyze_target(args.target)
    else:
        print("[ERROR] Por favor, forneça um --file ou um --target para análise.")

if __name__ == "__main__":
    main()


