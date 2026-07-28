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


def _startup_logfile():
    """Documents/Cruzer/cruzer_startup.log — diagnóstico de arranque cuando el .exe
    va SIN consola (console=False). Queda junto a los Excel."""
    try:
        d = Path.home() / "Documents" / "Cruzer"
        d.mkdir(parents=True, exist_ok=True)
        return d / "cruzer_startup.log"
    except Exception:  # noqa: BLE001
        return None


def _log(msg):
    line = f"  {msg}"
    print(line, flush=True)
    lf = _startup_logfile()
    if lf:
        try:
            with open(lf, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:  # noqa: BLE001
            pass


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


# Logo (PNG 180x180 base64) para el splash. Se inyecta en el build desde
# desktop/build/cruzer-logo-src.png. No se referencia por URL porque el splash
# se muestra ANTES de que el servidor exista.
_LOGO_B64 = "iVBORw0KGgoAAAANSUhEUgAAALQAAAC0CAIAAACyr5FlAAAAAXNSR0IArs4c6QAAAQJlWElmTU0AKgAAAAgABgEaAAUAAAABAAAAVgEbAAUAAAABAAAAXgEoAAMAAAABAAIAAAExAAIAAABpAAAAZgE7AAIAAAAHAAAA0IdpAAQAAAABAAAA2AAAAAAAAABgAAAAAQAAAGAAAAABQ2FudmEgKFJlbmRlcmVyKSBkb2M9REFIUC10N3M3UVkgdXNlcj1VQUVBSE91S0NrbyBicmFuZD1CQUVBSE02ODRhRSB0ZW1wbGF0ZT1CbHVlICYgQmxhY2sgRmluYW5jaWFsIExvZ28AAENhcmxvcwAAAAOgAQADAAAAAQABAACgAgAEAAAAAQAAALSgAwAEAAAAAQAAALQAAAAAvD/xzQAAAAlwSFlzAAAOxAAADsQBlSsOGwAAA+tpVFh0WE1MOmNvbS5hZG9iZS54bXAAAAAAADx4OnhtcG1ldGEgeG1sbnM6eD0iYWRvYmU6bnM6bWV0YS8iIHg6eG1wdGs9IlhNUCBDb3JlIDYuMC4wIj4KICAgPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4KICAgICAgPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIKICAgICAgICAgICAgeG1sbnM6dGlmZj0iaHR0cDovL25zLmFkb2JlLmNvbS90aWZmLzEuMC8iCiAgICAgICAgICAgIHhtbG5zOmRjPSJodHRwOi8vcHVybC5vcmcvZGMvZWxlbWVudHMvMS4xLyIKICAgICAgICAgICAgeG1sbnM6eG1wPSJodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvIj4KICAgICAgICAgPHRpZmY6UmVzb2x1dGlvblVuaXQ+MjwvdGlmZjpSZXNvbHV0aW9uVW5pdD4KICAgICAgICAgPHRpZmY6WVJlc29sdXRpb24+OTY8L3RpZmY6WVJlc29sdXRpb24+CiAgICAgICAgIDx0aWZmOlhSZXNvbHV0aW9uPjk2PC90aWZmOlhSZXNvbHV0aW9uPgogICAgICAgICA8ZGM6dGl0bGU+CiAgICAgICAgICAgIDxyZGY6QWx0PgogICAgICAgICAgICAgICA8cmRmOmxpIHhtbDpsYW5nPSJ4LWRlZmF1bHQiPkRpc2XDsW8gc2luIHTDrXR1bG8gLSAxPC9yZGY6bGk+CiAgICAgICAgICAgIDwvcmRmOkFsdD4KICAgICAgICAgPC9kYzp0aXRsZT4KICAgICAgICAgPGRjOmNyZWF0b3I+CiAgICAgICAgICAgIDxyZGY6U2VxPgogICAgICAgICAgICAgICA8cmRmOmxpPkNhcmxvczwvcmRmOmxpPgogICAgICAgICAgICA8L3JkZjpTZXE+CiAgICAgICAgIDwvZGM6Y3JlYXRvcj4KICAgICAgICAgPHhtcDpDcmVhdG9yVG9vbD5DYW52YSAoUmVuZGVyZXIpIGRvYz1EQUhQLXQ3czdRWSB1c2VyPVVBRUFIT3VLQ2tvIGJyYW5kPUJBRUFITTY4NGFFIHRlbXBsYXRlPUJsdWUgJmFtcDsgQmxhY2sgRmluYW5jaWFsIExvZ288L3htcDpDcmVhdG9yVG9vbD4KICAgICAgPC9yZGY6RGVzY3JpcHRpb24+CiAgIDwvcmRmOlJERj4KPC94OnhtcG1ldGE+CroCXGEAACJ1SURBVHgB7d113D1FuQDwi93dHYCiGIiNrdgSYl8VRVAsLFQMFFERBQuwEAsLFcVARQS7C7uwu7vzfu997p07n909W2f3nD3ve94/fr85s5PPPDPz9Gzx73//+z8299/73ve+ww477Fvf+tZ//s/fRS5ykc0Nj2z2kGPT/n3hC1+47W1ve5rTnCbB42IXu9gzn/nMv//975sWJvnEt/AjgWZTJT7wgQ/c7W53++EPfxizPu1pT/vPf/4z0nvvvfcRRxwhZ1iAfP/73//Yxz72gx/84EpXutINbnCDM5zhDMO2P3xrOaZsnvRnP/vZC13oQgHNm93sZu985zvlHHLIIRe4wAUi89nPfvaw0NDgec973rR+N77xjb/73e8O28Xgrf3H4C1Ov8Gf/vSn2267bazT/e9//7/+9a9pzB/+8IfPfe5z+3Se85znG9/4RsqfM7H//vsntEiJ61znOr///e/nbHnU6psOOdATt7/97WOF7nKXu/zjH/8owPepT31qfH3Uox5V+NTv57Oe9axo8OIXv/gLX/jCY445Zvvtt48c6X5tLqbWpkOOJz7xibEwV73qVX/5y1+WoYwycGwos/XWW//hD38oF+iU85rXvOb0pz+91lxYn/zkJ6Pu9773vbjU9ttvv06tLbjw5kKON7zhDac73eks1fnOd75TTjllFqzvda97KaPkpz71qVll2uSfdNJJZz/72TV1lrOc5YQTTsir3OIWt5D/iEc8Is+cWvr/uThj3dh/X/ziFx/wgAe4R7AhmBEnx6z53upWt/JJSVTqrDKN+Z/73OfucY97oCp097znPS+wIdVC6EgPzhCl9gdJbBbk+PWvf+08+PnPfw5qj3zkI+985zsXwGfXppztttvuzGc+s58WOGV2SuBEEDQ//vGP1Xryk58cR1FqwW2lgJ8TR45Nca0QYBBpxNrc+ta3/stf/lI4wN/85jcffPDBKdPiITiUt91TZvvEL37xi2tf+9rR3YMe9KB//etfhbqkHXG7Pf7xjy98mtTPTYEcT3/602OpttpqKzKowgL87ne/u9zlLneFK1zhb3/7W/pE+KGKzD/+8Y8ps03iz3/+8y677BLd3eEOd8j55FT9KU95ShR4whOekDInmNj4yPGOd7zjTGc6k8U429nO9sEPfrC8BiGEIK/Myc8HP/jBqpzjHOfAWZSrzMpxSBCcxMKTgf7mN78pl1TmRje6UZRZI0cZPovL+frXv37Ri140VuL5z39+uWMIAWmiAAlHKoCEjMz3v//9KbMxkfhkR84srPrOd75zznOeMxo/4IADGttcYoGNfHLgFK53vevFMlCXlKHszL/JTW4SBfy76667pjInnnhi5BNbpcz6hJJbbLGFWrR3VHqzCr/qVa9KPT7pSU+aVWwK+RsZOe573/vGMkCRSkG1syStk8QVr3hFFEOsyje/+U3CCZkoyjbrhKQNBsdN9N73vremyu677546XZ8cNYAa8ZN9HGvgWnG5lHv62c9+ZoundZIgsPr2t78dJSHTlltuKRPpUK5byHH1hEYGD/La17628DX/Cfm22Wab1KlrKP86tfTGPDk+8pGP2MHW4IxnPOPb3/72SqDbtWmRIuFSyDf9zW9+c/mXuMQlfvWrX1W2EJlkIYmsoUapKenT5z//eUNK/aKF68sv9+sGFIL96Ec/InTCoFoDGECwkRYjJVCLieRMmVaCYiX9dMtIE2ThflNmIUGWRZ4WRiEUdQ972MMKBQo/qVdCNhr5yYKkUGwiPzcacpBVYCbdI+B717ve1YJV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"


def _splash_html():
    """Pantalla de carga con diseño: logo, 'Cruzer', spinner y marca de agua."""
    return (
        '<!doctype html><html><head><meta charset="utf-8"><style>'
        '*{margin:0;box-sizing:border-box}html,body{height:100%}'
        'body{display:flex;flex-direction:column;align-items:center;justify-content:center;'
        'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;'
        'background:radial-gradient(circle at 50% 32%,#1c2432,#0e1116);color:#e7ecf3;'
        'user-select:none;-webkit-user-select:none;overflow:hidden}'
        '.logo{width:118px;height:118px;border-radius:27px;object-fit:cover;background:#fff;'
        'box-shadow:0 16px 44px -12px #000a,0 0 0 1px #ffffff12;animation:pop .6s cubic-bezier(.2,.8,.2,1)}'
        'h1{font-size:33px;letter-spacing:-.02em;margin-top:22px;font-weight:700}'
        '.sub{display:flex;align-items:center;gap:10px;color:#93a2b6;font-size:13.5px;margin-top:9px}'
        '.spin{width:15px;height:15px;border:2px solid #6d7dff40;border-top-color:#6d7dff;'
        'border-radius:50%;animation:spin .8s linear infinite}'
        '@keyframes spin{to{transform:rotate(360deg)}}'
        '@keyframes pop{from{transform:scale(.9);opacity:0}to{transform:scale(1);opacity:1}}'
        '.wm{position:fixed;bottom:18px;font-size:10.5px;font-style:italic;color:#586475;letter-spacing:.04em}'
        '</style></head><body>'
        '<img class="logo" src="data:image/png;base64,' + _LOGO_B64 + '">'
        '<h1>Cruzer</h1>'
        '<div class="sub"><span class="spin"></span> <span id="msg">Iniciando…</span></div>'
        '<div class="wm">Designed by Carlos Cruz</div>'
        '<script>function setMsg(m){var e=document.getElementById("msg");if(e)e.textContent=m}window.setMsg=setMsg;</script>'
        '</body></html>'
    )


def _screen_size():
    """(ancho, alto) de la pantalla principal, o un fallback razonable."""
    try:
        if sys.platform == "win32":
            import ctypes
            u = ctypes.windll.user32
            return int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
        if sys.platform == "darwin":
            from AppKit import NSScreen  # pyobjc (bundleado)
            fr = NSScreen.mainScreen().frame()
            return int(fr.size.width), int(fr.size.height)
    except Exception:  # noqa: BLE001
        pass
    return 1440, 900


def _window_geometry(pref_w=1240, pref_h=800):
    """Tamaño estético (cap a `pref`, pero nunca > ~86% de la pantalla) y posición
    CENTRADA. Sin esto pywebview abre en la posición 'cascada' por defecto (abajo a
    la derecha). Devuelve (w, h, x, y)."""
    sw, sh = _screen_size()
    w = max(940, min(pref_w, int(sw * 0.86)))
    h = max(620, min(pref_h, int(sh * 0.86)))
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2 - 24)   # un pelín sobre el centro exacto: se ve más natural
    return w, h, x, y


def main():
    # Guardia anti-bucle: si un subproceso relanzara el ejecutable (fue el bug de
    # la v1 con `sys.executable`), el hijo detecta la marca y se detiene en vez
    # de volver a descargar el código y relanzarse otra vez.
    if os.environ.get("CRUZER_RUNNING") == "1":
        print("  [Cruzer] Instancia hija detectada; no se relanza.", flush=True)
        return 0
    os.environ["CRUZER_RUNNING"] = "1"

    # Reinicia el log de arranque de esta corrida (útil sin consola en Windows).
    try:
        _lf = _startup_logfile()
        if _lf:
            _lf.write_text(f"Cruzer — arranque {_time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    # Navegador de Playwright en ruta PERSISTENTE (no en el _MEI temporal del
    # bundle, que se borra en cada ejecución → el navegador "desaparecía" y
    # ensure_chromium lo re-descargaba cada vez). Debe fijarse ANTES de
    # ensure_chromium. Sólo Windows; en Mac/Linux se deja el default.
    if sys.platform == "win32":
        _bbase = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    elif sys.platform == "darwin":
        _bbase = Path.home() / "Library" / "Caches"
    else:
        _bbase = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    _bdir = _bbase / "Cruzer" / "browsers"
    _bdir.mkdir(parents=True, exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_bdir)

    print("\n  Cruzer\n  " + "─" * 40, flush=True)

    _state = {}

    def _prepare(stage=None):
        """Descarga el código, prepara el navegador y arranca el server, reportando
        la etapa a `stage(msg)` (para el splash). Devuelve la URL, o None si no hay
        internet. Idempotente."""
        if _state.get("url"):
            return _state["url"]
        if stage:
            stage("Buscando actualización…")
        root = update_code()
        if root is None:
            return None
        sys.path.insert(0, str(root))          # engines/ desde la raíz
        sys.path.insert(0, str(root / "desktop"))  # desktop/ para el server
        if stage:
            stage("Preparando el navegador…")
        ensure_chromium()
        if stage:
            stage("Iniciando…")
        import server  # noqa: E402  (viene del código recién descargado)
        port = free_port()
        httpd = server.serve(port)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{port}/"
        _state["httpd"] = httpd
        _state["url"] = url
        _log(f"Servidor local en {url}")
        return url

    try:
        import webview
    except Exception:  # noqa: BLE001
        webview = None

    # PREFERENCIA: ventana nativa con SPLASH dinámico (logo + mensaje por etapa +
    # marca de agua). El splash abre PRIMERO (antes de descargar) para que el usuario
    # vea algo de inmediato; el trabajo pesado corre en background y el mensaje se va
    # actualizando. Al terminar navega a la app. Cerrar la ventana = cerrar la app.
    if webview is not None:
        _w, _h, _x, _y = _window_geometry()   # tamaño estético + CENTRADA
        win = webview.create_window("Cruzer", html=_splash_html(),
                                    width=_w, height=_h, x=_x, y=_y, min_size=(940, 620))

        def _stage(msg):
            _log(msg)
            try:
                win.evaluate_js('window.setMsg && setMsg("' + msg.replace('"', "'") + '")')
            except Exception:  # noqa: BLE001
                pass

        def _boot():
            try:
                url = _prepare(stage=_stage)
                if url is None:
                    win.load_html(
                        "<body style='font-family:sans-serif;padding:44px;color:#333'>"
                        "<h2>Sin conexión</h2><p>Cruzer necesita internet para actualizarse "
                        "desde GitHub. Revisa tu conexión y vuelve a abrir.</p></body>")
                    return
                threading.Timer(0.4, _minimize_console).start()
                win.load_url(url)
            except Exception as e:  # noqa: BLE001
                _log(f"ERROR al iniciar: {e}")
                try:
                    win.load_html(
                        "<body style='font-family:sans-serif;padding:44px;color:#333'>"
                        "<h2>No se pudo iniciar Cruzer</h2><pre>" + str(e) + "</pre>"
                        "<p>Detalle en Documents/Cruzer/cruzer_startup.log</p></body>")
                except Exception:  # noqa: BLE001
                    pass

        try:
            webview.start(_boot)   # bloquea hasta cerrar la ventana; _boot corre en hilo
            h = _state.get("httpd")
            if h:
                h.shutdown()
            return 0
        except Exception as e:  # noqa: BLE001
            _log(f"(ventana nativa falló: {e} — abro en el navegador)")

    # FALLBACK navegador (sin pywebview o si falló):
    url = _prepare()
    if url is None:
        try:
            if sys.stdin and sys.stdin.isatty():
                input("\n  Sin internet. Presiona Enter para salir…")
        except Exception:  # noqa: BLE001
            pass
        return 1
    print("  La app está abierta en tu navegador.", flush=True)
    _open_browser(url)
    _minimize_console()
    try:
        while True:
            _time.sleep(1)
    except KeyboardInterrupt:
        _log("Cerrando…")
    h = _state.get("httpd")
    if h:
        h.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
