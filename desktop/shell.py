# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""GoWild Desktop — shell de arranque (esto es lo que se empaqueta como .exe).

MISMO MODELO QUE LOS COLAB (thin-launcher), pero de escritorio:

  - El **ejecutable es delgado y estable**: sólo trae el runtime de Python, las
    dependencias y este arranque. Casi nunca hay que reconstruirlo.
  - En cada arranque **descarga la última versión del código desde GitHub**
    (zip de `main`), la deja en la carpeta de datos del usuario y la importa
    desde ahí. Motores, orquestadores y **también la UI** vienen de ahí.
  - Resultado: `git push` = todos los usuarios actualizados al siguiente doble
    clic, sin redistribuir nada. Igual que hoy con los notebooks.

Sólo hay que reconstruir el .exe si cambian las DEPENDENCIAS (equivalente al
`launcher_schema` de los notebooks).

Tolerante a fallos: si no hay internet o GitHub falla, usa la última copia
descargada. Si no hay ninguna, avisa con un mensaje claro.
"""
from __future__ import annotations

import io
import os
import shutil
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

REPO = "carloscruzerrazuriz/GoWild-Scraper"
BRANCH = "main"
ZIP_URL = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"
DEFAULT_PORT = 8733


def app_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    d = base / "GoWild"
    d.mkdir(parents=True, exist_ok=True)
    return d


CODE_DIR = app_dir() / "code"


def _log(msg):
    print(f"  {msg}", flush=True)


def update_code() -> Path | None:
    """Descarga la última versión desde GitHub. Devuelve la raíz del repo local.

    Si falla la descarga pero ya hay una copia, la reusa (modo offline).
    """
    current = CODE_DIR / f"{REPO.split('/')[1]}-{BRANCH}"
    try:
        _log("Buscando actualizaciones en GitHub…")
        req = urllib.request.Request(ZIP_URL, headers={"User-Agent": "GoWild-Desktop"})
        with urllib.request.urlopen(req, timeout=45) as r:
            data = r.read()
        tmp = CODE_DIR / "_tmp"
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(tmp)
        extracted = next((p for p in tmp.iterdir() if p.is_dir()), None)
        if not extracted:
            raise RuntimeError("zip vacío")
        if current.exists():
            shutil.rmtree(current, ignore_errors=True)
        shutil.move(str(extracted), str(current))
        shutil.rmtree(tmp, ignore_errors=True)
        _log("Código actualizado.")
        return current
    except Exception as e:  # noqa: BLE001
        if current.exists():
            _log(f"Sin conexión ({type(e).__name__}); uso la última versión descargada.")
            return current
        _log(f"ERROR: no pude descargar el código y no hay copia local ({e}).")
        return None


def ensure_chromium():
    """Instala el Chromium de Playwright la primera vez (MK7 y Sección lo usan)."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exe = p.chromium.executable_path
            if exe and Path(exe).exists():
                return True
    except Exception:  # noqa: BLE001
        pass
    _log("Instalando el navegador (sólo la primera vez, ~150 MB)…")
    try:
        import subprocess
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                       check=True)
        _log("Navegador instalado.")
        return True
    except Exception as e:  # noqa: BLE001
        _log(f"Aviso: no pude instalar el navegador ({e}). "
             "MK7 y Sección lo necesitan; Fast funciona igual.")
        return False


def free_port(start=DEFAULT_PORT) -> int:
    for port in range(start, start + 40):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def main():
    print("\n  GoWild Desktop\n  " + "─" * 40, flush=True)
    root = update_code()
    if root is None:
        input("\n  Presiona Enter para salir…")
        return 1

    # El código fresco manda: engines/ desde la raíz, y desktop/ para el server.
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "desktop"))

    ensure_chromium()

    import server  # noqa: E402  (viene del código recién descargado)
    port = free_port()
    httpd = server.serve(port)
    url = f"http://127.0.0.1:{port}/"
    _log(f"Servidor local en {url}")
    _log(f"Los Excel se guardan en: {server.OUTPUT_DIR}")
    print("  " + "─" * 40, flush=True)
    print("  Deja esta ventana abierta mientras trabajas.", flush=True)
    print("  Para cerrar: cierra esta ventana o pulsa Ctrl+C.\n", flush=True)

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _log("Cerrando…")
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
