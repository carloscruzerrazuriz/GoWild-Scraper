# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Cruzer — shell de arranque (esto es lo que se empaqueta como .exe).

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
import time as _time
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

_TMP_PREFIX = "cruzer-code-"
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
        req = urllib.request.Request(ZIP_URL, headers={"User-Agent": "Cruzer-Desktop"})
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
    Python. Esa llamada relanzaba Cruzer.exe, que volvía a descargar el código y
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


def _find_chrome_win():
    """Ruta a chrome.exe en Windows, o None."""
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")):
        if Path(p).exists():
            return p
    return None


def _open_browser(url):
    """Abre `url` en el navegador PREFERIDO por plataforma (para que todos vean
    lo mismo, no el navegador por defecto de cada PC): **Chrome en Windows**,
    **Safari en Mac**. Si falla, cae al navegador por defecto del sistema."""
    try:
        import subprocess
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "Safari", url])   # Safari siempre está en Mac
            return
        if os.name == "nt":
            chrome = _find_chrome_win()
            if chrome:
                subprocess.Popen([chrome, url])
                return
    except Exception:  # noqa: BLE001
        pass
    webbrowser.open(url)  # fallback: navegador por defecto del sistema


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


def _run_native_window(url):
    """Abre la UI en una VENTANA NATIVA propia (pywebview) — su propio ícono en la
    barra de tareas / dock, sin pestañas de navegador. Usa el motor web del SO
    (WebView2/Edge en Windows, WKWebView en Mac). BLOQUEA hasta que se cierra la
    ventana → cerrar la ventana = cerrar la app.

    Devuelve True si se usó la ventana nativa; False si pywebview no está o falla
    → el caller cae al NAVEGADOR (comportamiento existente, que NO se borró)."""
    try:
        import webview
    except Exception:  # noqa: BLE001
        return False
    try:
        threading.Timer(0.4, _minimize_console).start()  # esconde la consola redundante
        webview.create_window("Cruzer", url, width=1280, height=860, min_size=(980, 640))
        webview.start()   # bloquea; retorna cuando el usuario cierra la ventana
        return True
    except Exception as e:  # noqa: BLE001
        _log(f"(ventana nativa no disponible: {e} — abro en el navegador)")
        return False


def main():
    # Guardia anti-bucle: si un subproceso relanzara el ejecutable (fue el bug de
    # la v1 con `sys.executable`), el hijo detecta la marca y se detiene en vez
    # de volver a descargar el código y relanzarse otra vez.
    if os.environ.get("CRUZER_RUNNING") == "1":
        print("  [Cruzer] Instancia hija detectada; no se relanza.", flush=True)
        return 0
    os.environ["CRUZER_RUNNING"] = "1"

    # Navegador de Playwright en ruta PERSISTENTE (no en el _MEI temporal del
    # bundle, que se borra en cada ejecución → el navegador "desaparecía" y
    # ensure_chromium lo re-descargaba cada vez). Debe fijarse ANTES de
    # ensure_chromium. Sólo Windows; en Mac/Linux se deja el default.
    if os.name == "nt":
        _bdir = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "Cruzer" / "browsers"
        _bdir.mkdir(parents=True, exist_ok=True)
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_bdir)

    print("\n  Cruzer\n  " + "─" * 40, flush=True)
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

    # El servidor corre en un hilo daemon; el hilo principal queda libre para la
    # ventana nativa (pywebview la necesita) o para el bloqueo del fallback.
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    # PREFERENCIA: ventana nativa propia (ícono en la barra de tareas, sin navegador).
    # Si pywebview no está / falla → FALLBACK al navegador (lo de siempre, intacto).
    if _run_native_window(url):
        httpd.shutdown()
        return 0

    print("  La app está abierta en tu navegador.", flush=True)
    print("  Esta ventana se minimiza sola; NO la cierres mientras trabajas.", flush=True)
    print("  Para salir de la app: cierra esta ventana.\n", flush=True)
    _open_browser(url)
    _minimize_console()
    try:
        while True:
            _time.sleep(1)
    except KeyboardInterrupt:
        _log("Cerrando…")
    httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
