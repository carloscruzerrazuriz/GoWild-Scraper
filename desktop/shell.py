# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Vulpex — shell de arranque (esto es lo que se empaqueta como .exe).

MISMO MODELO QUE LOS COLAB (thin-launcher), pero de escritorio:

  - El **ejecutable es delgado y estable**: sólo trae el runtime de Python, las
    dependencias y este arranque. Casi nunca hay que reconstruirlo.
  - En cada arranque **descarga la última versión del código desde GitHub**
    (zip de `main`) a una carpeta TEMPORAL y la importa desde ahí. Motores,
    orquestadores y **también la UI** vienen de ahí.
  - **El código NO queda en el equipo**: se borra al cerrar (ver "Código
    EFÍMERO" más abajo). Sin internet la app no arranca, a propósito: depende
    de GitHub por diseño.
  - Resultado: `git push` = todos los usuarios actualizados al siguiente doble
    clic, sin redistribuir nada. Igual que hoy con los notebooks.

Sólo hay que reconstruir el .exe si cambian las DEPENDENCIAS (equivalente al
`launcher_schema` de los notebooks).
"""
from __future__ import annotations

import io
import os
import shutil
import socket
import sys
import threading
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

REPO = "carloscruzerrazuriz/GoWild-Scraper"
BRANCH = "main"
ZIP_URL = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"
DEFAULT_PORT = 8733


# ── Código EFÍMERO ──────────────────────────────────────────────────────────
# Requisito del titular: el código NO debe quedar guardado en el PC del usuario.
# Se descarga de GitHub a una carpeta temporal, se usa, y se borra al cerrar.
#
# Cobertura del borrado:
#   - Salida normal .................. atexit
#   - Ctrl+C / cierre de ventana ..... handlers de SIGINT/SIGTERM
#   - Excepción no capturada ......... atexit corre igual
#   - Kill duro / corte de luz ....... queda huérfano, PERO el siguiente arranque
#                                      barre los restos (_sweep_stale) antes de
#                                      descargar. Así nunca se acumula ni queda
#                                      código viejo utilizable.
#
# LÍMITE HONESTO: mientras la app corre, el código está en disco y en RAM, así
# que un usuario decidido puede copiarlo. Esto eleva la barrera (nadie lo
# encuentra por casualidad ni queda tras desinstalar), no la vuelve infranqueable
# — misma conclusión del §11 cuando se evaluó PyArmor.
import atexit
import signal
import tempfile

_TMP_PREFIX = "vulpex-code-"
_CODE_DIR: Path | None = None


def _log(msg):
    print(f"  {msg}", flush=True)


def _sweep_stale(min_age_secs=900):
    """Borra restos de ejecuciones anteriores que murieron sin limpiar.

    Sólo toca carpetas con más de `min_age_secs` de antigüedad: si el usuario
    abre una segunda ventana de la app, no queremos que le borre el código a la
    que ya está corriendo.
    """
    import time as _t
    base = Path(tempfile.gettempdir())
    n = 0
    for p in base.glob(f"{_TMP_PREFIX}*"):
        if _CODE_DIR and p == _CODE_DIR:
            continue
        try:
            if _t.time() - p.stat().st_mtime < min_age_secs:
                continue          # probablemente sea otra instancia viva
            shutil.rmtree(p, ignore_errors=True)
            n += 1
        except Exception:  # noqa: BLE001
            pass
    if n:
        _log(f"Limpieza: {n} copia(s) de una ejecución anterior eliminada(s).")


def wipe_code():
    """Borra el código descargado. Idempotente."""
    global _CODE_DIR
    if _CODE_DIR and Path(_CODE_DIR).exists():
        shutil.rmtree(_CODE_DIR, ignore_errors=True)
        _log("Código temporal eliminado.")
    _CODE_DIR = None


def _install_cleanup():
    atexit.register(wipe_code)

    def _bye(signum, frame):
        wipe_code()
        os._exit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _bye)
        except Exception:  # noqa: BLE001
            pass
    if os.name == "nt":  # cierre de la ventana de consola en Windows
        try:
            signal.signal(signal.SIGBREAK, _bye)
        except Exception:  # noqa: BLE001
            pass


def update_code() -> Path | None:
    """Descarga la última versión desde GitHub a una carpeta TEMPORAL.

    Sin copia persistente: si no hay internet, la app no arranca (a propósito —
    el requisito es que dependa de GitHub y no deje código en el equipo).
    """
    global _CODE_DIR
    _sweep_stale()
    try:
        _log("Descargando la última versión desde GitHub…")
        req = urllib.request.Request(ZIP_URL, headers={"User-Agent": "Vulpex-Desktop"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        tmp = Path(tempfile.mkdtemp(prefix=_TMP_PREFIX))
        _CODE_DIR = tmp
        _install_cleanup()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(tmp)
        root = next((p for p in tmp.iterdir() if p.is_dir()), None)
        if not root:
            raise RuntimeError("el zip venía vacío")
        _log(f"Código cargado ({len(data) // 1024} KB). Se borrará al cerrar.")
        return root
    except Exception as e:  # noqa: BLE001
        wipe_code()
        _log(f"ERROR: no pude descargar el código desde GitHub ({e}).")
        _log("Revisa tu conexión a internet: la app necesita GitHub para funcionar.")
        return None


def ensure_chromium():
    """Instala el Chromium de Playwright la primera vez (MK7 y Sección lo usan).

    ⚠️ NUNCA usar `sys.executable -m playwright install` acá: dentro de un .exe
    de PyInstaller `sys.executable` ES EL PROPIO EJECUTABLE, no un intérprete de
    Python. Esa llamada relanzaba Vulpex.exe, que volvía a descargar el código y
    a llamar a esta función → bucle infinito de descargar/borrar (bug real
    reportado en la v1).

    Se invoca el **driver de Node de Playwright** directamente, que es lo que
    hace por dentro `playwright.__main__`.
    """
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
        from playwright._impl._driver import compute_driver_executable, get_driver_env

        drv = compute_driver_executable()
        cmd = ([str(drv[0]), str(drv[1])] if isinstance(drv, (tuple, list))
               else [str(drv)])          # la API cambió de forma entre versiones
        subprocess.run(cmd + ["install", "chromium"], env=get_driver_env(), check=True)
        _log("Navegador instalado.")
        return True
    except Exception as e:  # noqa: BLE001
        _log(f"Aviso: no pude instalar el navegador ({e}).")
        _log("MK7, Sección y Ferni lo necesitan; Fast funciona igual.")
        return False


def free_port(start=DEFAULT_PORT) -> int:
    for port in range(start, start + 40):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def _minimize_console():
    """Minimiza la ventana de consola en Windows una vez abierta la app.

    La consola es el servidor: no se puede cerrar sin apagar la app. Pero sí se
    puede mandar al fondo para que no estorbe, conservándola disponible por si
    hay que ver un error o cerrar la app. Usa la API Win32 vía ctypes (sin
    dependencias). En Mac/Linux es un no-op.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE = 6
    except Exception:  # noqa: BLE001
        pass


def main():
    # Guardia anti-bucle: si un subproceso relanzara el ejecutable (fue el bug de
    # la v1 con `sys.executable`), el hijo detecta la marca y se detiene en vez
    # de volver a descargar el código y relanzarse otra vez.
    if os.environ.get("VULPEX_RUNNING") == "1":
        print("  [Vulpex] Instancia hija detectada; no se relanza.", flush=True)
        return 0
    os.environ["VULPEX_RUNNING"] = "1"

    print("\n  Vulpex\n  " + "─" * 40, flush=True)
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
    print("  La app está abierta en tu navegador.", flush=True)
    print("  Esta ventana se minimiza sola; NO la cierres mientras trabajas.", flush=True)
    print("  Para salir de la app: cierra esta ventana.\n", flush=True)

    def _open_and_minimize():
        webbrowser.open(url)
        _minimize_console()

    threading.Timer(1.2, _open_and_minimize).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _log("Cerrando…")
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
