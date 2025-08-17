#!/bin/bash
set -uo pipefail

EMAIL="${1:-}"

if [[ -z "$EMAIL" ]]; then
  echo "Uso: ./email_leak_checker_full.sh email@exemplo.com"
  exit 1
fi

mkdir -p leak_check_results static/relatorios
RELATORIO_JSON="leak_check_results/ultimo_relatorio.json"
DATA="$(LC_ALL=C date +"%Y-%m-%d_%H-%M-%S")"
PASTA="static/relatorios/$DATA"
mkdir -p "$PASTA"

UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

buscar_fonte() {
  local fonte="$1"
  local url="$2"
  local arquivo="$PASTA/$fonte.html"

  echo "<h2>Resultados para $EMAIL em $fonte</h2>" > "$arquivo"

  links=$(curl -s -A "$UA" --header 'Accept-Encoding: identity' --max-time 15 "$url" \
    | grep -Eo '(http|https)://[^"]+' | sort -u | head -n 15 || true)

  for link in $links; do
      resumo=$(curl -m 8 -s -A "$UA" --header 'Accept-Encoding: identity' "$link" \
        | sed 's/<[^>]*>//g' | head -n 3 | tr -d '\n' | cut -c1-200 || true)
      echo "<p><b>Link:</b> <a href='$link' target='_blank'>$link</a><br><b>Resumo:</b> $resumo</p>" >> "$arquivo"
  done
}

buscar_fonte_tor() {
  local fonte="$1"
  local url="$2"
  local arquivo="$PASTA/$fonte.html"

  echo "<h2>Resultados (Tor) para $EMAIL em $fonte</h2>" > "$arquivo"

  links=$(curl -s --socks5 127.0.0.1:9050 -A "$UA" --header 'Accept-Encoding: identity' --max-time 20 "$url" \
    | grep -Eo '(http|https)://[^"]+' | sort -u | head -n 15 || true)

  for link in $links; do
      resumo=$(curl --socks5 127.0.0.1:9050 -m 10 -s -A "$UA" --header 'Accept-Encoding: identity' "$link" \
        | sed 's/<[^>]*>//g' | head -n 3 | tr -d '\n' | cut -c1-200 || true)
      echo "<p><b>Link:</b> <a href='$link' target='_blank'>$link</a><br><b>Resumo:</b> $resumo</p>" >> "$arquivo"
  done
}

# ================= SUPER LISTA DE FONTES =================
# Surface
buscar_fonte "Google"      "https://www.google.com/search?q=$EMAIL"
buscar_fonte "Bing"        "https://www.bing.com/search?q=$EMAIL"
buscar_fonte "DuckDuckGo"  "https://duckduckgo.com/html/?q=$EMAIL"
buscar_fonte "Yahoo"       "https://search.yahoo.com/search?p=$EMAIL"
buscar_fonte "Ask"         "https://www.ask.com/web?q=$EMAIL"
buscar_fonte "Yandex"      "https://yandex.com/search/?text=$EMAIL"

# Deep/Dark (via Tor)
buscar_fonte_tor "Ahmia"       "https://ahmia.fi/search/?q=$EMAIL"
buscar_fonte_tor "OnionLand"   "https://onionlandsearchengine.com/search?q=$EMAIL"
buscar_fonte_tor "OnionSearch" "https://onionsearchengine.com/search?q=$EMAIL"
buscar_fonte_tor "Torch"       "http://xmh57jrzrnw6insl.onion/cgi-bin/omega/omega?P=$EMAIL"
buscar_fonte_tor "DarkSearch"  "https://darksearch.io/search?q=$EMAIL"
buscar_fonte_tor "Phobos"      "http://phobos4czs77u.onion/?query=$EMAIL"

# Pastebin & similares
buscar_fonte "Pastebin"  "https://pastebin.com/search?q=$EMAIL"
buscar_fonte "GitHub"    "https://github.com/search?q=$EMAIL&type=code"
buscar_fonte "GitLab"    "https://gitlab.com/search?search=$EMAIL&group_id=&project_id=&snippets=false&repository_ref=&nav_source=navbar"

# Redes sociais
buscar_fonte "Reddit"    "https://www.reddit.com/search/?q=$EMAIL"
buscar_fonte "Twitter"   "https://twitter.com/search?q=$EMAIL&src=typed_query"
buscar_fonte "Facebook"  "https://www.facebook.com/search/top?q=$EMAIL"

# ================= API INTEGRAÇÕES =================
# HaveIBeenPwned
HIBP_RES=$(curl -s --header 'Accept-Encoding: identity' "https://haveibeenpwned.com/api/v3/breachedaccount/$EMAIL" \
  -H "hibp-api-key: 6e1d61b77f45db7694d665994570e28f" || true)
echo "<h2>HaveIBeenPwned</h2><pre>$HIBP_RES</pre>" > "$PASTA/HaveIBeenPwned.html"

# LeakCheck.io
LEAKCHECK_RES=$(curl -s --header 'Accept-Encoding: identity' "https://leakcheck.io/api?key=4Qm41/3B+mF/qZCl+C5xcwa7KNvSsbhBaQbyvW1Fos3W9d9Sg0c0BAs=&check=$EMAIL" || true)
echo "<h2>LeakCheck.io</h2><pre>$LEAKCHECK_RES</pre>" > "$PASTA/LeakCheck.html"

# Breachdirectory.org
BREACH_RES=$(curl -s --header 'Accept-Encoding: identity' "https://breachdirectory.org/api/?func=auto&term=$EMAIL&key=62MA8ziDlgTZXvGaAXCkuPCfnaLrSfiL" || true)
echo "<h2>BreachDirectory</h2><pre>$BREACH_RES</pre>" > "$PASTA/BreachDirectory.html"

# ================= GERAR JSON =================
cat <<EOF > "$RELATORIO_JSON"
{
  "email": "$EMAIL",
  "data": "$DATA",
  "resultados": {
    "google": "Google.html",
    "bing": "Bing.html",
    "duckduckgo": "DuckDuckGo.html",
    "yahoo": "Yahoo.html",
    "ask": "Ask.html",
    "yandex": "Yandex.html",
    "ahmia": "Ahmia.html",
    "onionland": "OnionLand.html",
    "onionsearch": "OnionSearch.html",
    "torch": "Torch.html",
    "darksearch": "DarkSearch.html",
    "phobos": "Phobos.html",
    "pastebin": "Pastebin.html",
    "github": "GitHub.html",
    "gitlab": "GitLab.html",
    "reddit": "Reddit.html",
    "twitter": "Twitter.html",
    "facebook": "Facebook.html",
    "haveibeenpwned": "HaveIBeenPwned.html",
    "leakcheck": "LeakCheck.html",
    "breachdirectory": "BreachDirectory.html"
  }
}
EOF

echo "[✅] Relatório gerado em: $RELATORIO_JSON"
echo "[✅] Arquivos HTML por fonte em: $PASTA"
