#!/usr/bin/env sh

# If you could not download the model from the official site, you can use the mirror site.
# Just remove the comment of the following line .
# Si no puedes descargar el modelo desde el sitio web oficial, puedes usar un sitio espejo.
# Solo tienes que quitar el comentario de la siguiente línea.

# export HF_ENDPOINT=https://hf-mirror.com

CURRENT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONPATH="$CURRENT_DIR${PYTHONPATH:+:$PYTHONPATH}"

# 0.0.0.0 solo significa "escuchar en todas las interfaces de red"; no sirve como dirección de acceso del navegador.
# En macOS/Linux, abrir http://0.0.0.0:8501 en el navegador podría pasar por un proxy o puerta de enlace
# y terminar en un error 502. Por defecto se enlaza y abre 127.0.0.1, igual que en el script de inicio de Windows.
MPT_WEBUI_HOST="${MPT_WEBUI_HOST:-127.0.0.1}"
MPT_WEBUI_PORT="${MPT_WEBUI_PORT:-8501}"

if [ -x "$CURRENT_DIR/.venv/bin/python" ]; then
  PORT_CHECK_CMD="$CURRENT_DIR/.venv/bin/python"
  set -- "$CURRENT_DIR/.venv/bin/python" -m streamlit
elif command -v uv >/dev/null 2>&1; then
  PORT_CHECK_CMD="uv run python"
  set -- uv run streamlit
elif command -v streamlit >/dev/null 2>&1; then
  echo "***** Advertencia: usando streamlit del PATH. Si fallan las dependencias, ejecuta primero 'uv sync --frozen'. *****"
  PORT_CHECK_CMD="python3"
  set -- streamlit
else
  echo "***** No se encontró ni el Python del proyecto, ni uv, ni streamlit. Instala primero las dependencias. *****"
  exit 1
fi

find_available_port() {
  WEBUI_HOST="$MPT_WEBUI_HOST" WEBUI_PORT="$MPT_WEBUI_PORT" "$@" - <<'PY' 2>/dev/null
import os
import socket
import sys

host = os.environ.get("WEBUI_HOST", "127.0.0.1")
preferred = int(os.environ.get("WEBUI_PORT", "8501"))
candidates = [preferred] + [port for port in range(8502, 8600) if port != preferred]

for port in candidates:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            continue
        print(port)
        sys.exit(0)

sys.exit(1)
PY
}

# La detección de puertos se hace con Python para no depender de lsof/nc, que varían entre distribuciones de macOS/Linux.
# shellcheck disable=SC2086
SELECTED_WEBUI_PORT=$(find_available_port $PORT_CHECK_CMD)

if [ -z "$SELECTED_WEBUI_PORT" ]; then
  echo "***** No se encontró ningún puerto WebUI disponible en 8501-8599 para $MPT_WEBUI_HOST. *****"
  exit 1
fi

if [ "$SELECTED_WEBUI_PORT" != "$MPT_WEBUI_PORT" ]; then
  echo "***** El puerto $MPT_WEBUI_PORT no está disponible, usando $SELECTED_WEBUI_PORT en su lugar. *****"
fi

MPT_WEBUI_PORT="$SELECTED_WEBUI_PORT"

echo "***** Dirección de la WebUI: http://$MPT_WEBUI_HOST:$MPT_WEBUI_PORT *****"
"$@" run "$CURRENT_DIR/webui/Main.py" \
  --server.address="$MPT_WEBUI_HOST" \
  --server.port="$MPT_WEBUI_PORT" \
  --browser.serverAddress="$MPT_WEBUI_HOST" \
  --browser.gatherUsageStats=False \
  --client.toolbarMode=minimal \
  --logger.hideWelcomeMessage=True \
  --server.showEmailPrompt=False \
  --server.enableCORS=True
