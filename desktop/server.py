# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Servidor local de Cruzer.

Levanta un HTTP server en 127.0.0.1 (sólo loopback: nadie de la red puede
entrar) que sirve el frontend y expone las 3 herramientas. El progreso viaja al
navegador por **SSE** (Server-Sent Events): un stream de texto plano, sin
websockets ni dependencias extra.

Usa sólo la stdlib (http.server + threading) a propósito: menos dependencias =
un .exe más chico y un build de PyInstaller menos frágil.
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import queue
import re
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote


def _new_loop():
    """Event loop apto para Playwright, incluso en un hilo secundario.

    En WINDOWS, Playwright lanza su driver como SUBPROCESO y eso requiere un
    ProactorEventLoop; el SelectorEventLoop no soporta subprocesos y revienta con
    NotImplementedError apenas se intenta abrir el navegador (era el fallo de
    'Cargar secciones': el request moría al instante). Como el servidor corre cada
    tarea en un hilo, forzamos Proactor explícitamente en Windows.
    """
    if sys.platform == "win32" and hasattr(asyncio, "ProactorEventLoop"):
        return asyncio.ProactorEventLoop()
    return asyncio.new_event_loop()

import os

UI_DIR = Path(__file__).resolve().parent / "ui"
OUTPUT_DIR = Path.home() / "Documents" / "Cruzer"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = OUTPUT_DIR / "_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ── Navegador de Playwright en una carpeta PERSISTENTE (TODAS las plataformas) ─
# En el ejecutable empaquetado, el Playwright bundleado busca/instala el navegador
# DENTRO del bundle (.local-browsers junto al driver, o el _MEIxxxx temporal en
# Windows), que se borra o es de sólo-lectura → "Executable doesn't exist". Fijamos
# una ruta estable por plataforma para que se descargue UNA vez y el runtime lo
# encuentre siempre. Antes esto era SÓLO Windows → en Mac el .app fallaba al abrir
# el navegador ('Cargar secciones'). Se hace acá (código de GitHub) para no
# recompilar. shell.py fija lo mismo antes de importar este módulo (redundante y OK).
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
    if sys.platform == "win32":
        _bbase = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        _bbase = Path.home() / "Library" / "Caches"
    else:
        _bbase = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    _BROWSERS = _bbase / "Cruzer" / "browsers"
    _BROWSERS.mkdir(parents=True, exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_BROWSERS)


def _ensure_browser():
    """Garantiza que Chromium exista en PLAYWRIGHT_BROWSERS_PATH; si no, lo baja.

    Se invoca al arrancar el servidor. Instala vía el driver de Node de Playwright
    (NUNCA sys.executable: en el .exe eso relanzaría Cruzer.exe). Persiste, así que
    sólo descarga la primera vez.
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exe = p.chromium.executable_path
            if exe and Path(exe).exists():
                return
    except Exception:  # noqa: BLE001
        pass
    try:
        import subprocess
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        drv = compute_driver_executable()
        cmd = ([str(drv[0]), str(drv[1])] if isinstance(drv, (tuple, list)) else [str(drv)])
        print("  Descargando el navegador a una ubicación permanente (una vez, ~150 MB)…", flush=True)
        subprocess.run(cmd + ["install", "chromium"], env=get_driver_env(), check=False)
        print("  Navegador listo.", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  (aviso: no pude preparar el navegador: {e})", flush=True)

# ── Registro de jobs (hasta MAX_CONCURRENT en paralelo) ─────────────────────
# Antes había UN solo job global. Ahora cada scrape es un job con su propio
# id, su cola de eventos (SSE) y su hilo+event-loop. La cola se crea al lanzar
# (no al conectar el SSE) para no perder los eventos que se emiten antes de que
# el navegador abra el stream.
MAX_CONCURRENT = 3          # cuántos scrapes a la vez
FAST_WORKER_BUDGET = 12     # workers TOTALES de Fast repartidos entre los Fast activos
JOBS = {}                   # job_id -> {running, events:Queue, result, error, tool, done_at}
JOBS_LOCK = threading.Lock()


def _active_count():
    return sum(1 for j in JOBS.values() if j["running"])


def _active_fast_count():
    return sum(1 for j in JOBS.values() if j["running"] and j["tool"] == "fast")


# EXPERIMENTAL: autorregulación de carga sobre Sodimac. Los jobs CON NAVEGADOR que
# apuntan a Sodimac (Ferni siempre; MK7/Sección sólo si retailer=sodimac) compiten
# con Fast por el mismo techo anti-bot de la misma IP. Falabella/Construmart pegan
# a OTROS sitios → no cuentan. Se usa para descontar workers al lanzar un Fast.
_SODIMAC_BROWSER_TOOLS = {"ferni_sku", "ferni_seccion"}


def _sodimac_browser_jobs():
    n = 0
    for j in JOBS.values():
        if not j["running"]:
            continue
        t, r = j["tool"], j.get("retailer", "sodimac")
        if t in _SODIMAC_BROWSER_TOOLS or (t in ("mk7", "seccion") and r == "sodimac"):
            n += 1
    return n


def _gc_jobs(ttl=300):
    """Saca del registro los jobs terminados hace más de `ttl` s."""
    now = time.time()
    for jid in [k for k, j in JOBS.items()
                if not j["running"] and j.get("done_at") and now - j["done_at"] > ttl]:
        JOBS.pop(jid, None)


def _emit(job_id, ev):
    j = JOBS.get(job_id)
    if j is not None and j["events"] is not None:
        j["events"].put(ev)


def _run_job(job_id, tool, params):
    """Corre la herramienta en un hilo con su propio event loop.

    La corrutina se envuelve en una TASK y se guarda (junto al loop) en JOBS
    para poder CANCELARLA desde /api/cancel (loop.call_soon_threadsafe(task.cancel)).
    """
    from orchestrators import TOOLS
    loop = _new_loop()
    asyncio.set_event_loop(loop)
    emit = lambda ev: _emit(job_id, ev)  # noqa: E731
    tag = job_id[:6]  # sufijo corto para nombre de archivo / screenshots únicos
    task = loop.create_task(TOOLS[tool]["run"](params, emit, OUTPUT_DIR, tag))
    JOBS[job_id]["loop"] = loop
    JOBS[job_id]["task"] = task
    try:
        out = loop.run_until_complete(task)
        JOBS[job_id]["result"] = str(out)
        emit({"type": "done", "file": Path(out).name, "path": str(out)})
    except asyncio.CancelledError:
        emit({"type": "warn", "msg": "Proceso cancelado."})
    except Exception as e:  # noqa: BLE001
        JOBS[job_id]["error"] = str(e)
        emit({"type": "error", "msg": str(e),
              "detail": traceback.format_exc()[-1200:]})
    finally:
        loop.close()
        JOBS[job_id]["running"] = False
        JOBS[job_id]["done_at"] = time.time()
        emit({"type": "eof"})


def _open_path(path, *, reveal=False):
    """Abre `path` con la app por defecto (Excel), o MUESTRA la carpeta (reveal)."""
    import subprocess
    if sys.platform == "win32":
        if reveal:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open"] + (["-R"] if reveal else []) + [path])
    else:
        target = os.path.dirname(path) if reveal else path
        subprocess.Popen(["xdg-open", target])


def _hide_console_win():
    """Windows: OCULTA la ventana de consola de la barra de tareas (SW_HIDE). Con la
    ventana nativa (pywebview) la consola es redundante y molesta. Se hace en runtime
    (código de GitHub) → no requiere recompilar el .exe. En Mac/Linux es no-op."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE = 0
    except Exception:  # noqa: BLE001
        pass


def _hide_console_persistently():
    """Windows: re-oculta la consola varias veces los primeros segundos. Hace falta
    porque shell.py (horneado en el .exe) dispara un `minimize` ~0.4s después de
    arrancar la ventana nativa, que RE-MOSTRABA la consola minimizada en la barra
    de tareas. Con re-hides sucesivos el SW_HIDE termina ganando. No-op fuera de Win."""
    if sys.platform != "win32":
        return

    def _loop():
        for _ in range(12):        # ~6 s cubriendo el minimize tardío del shell
            _hide_console_win()
            time.sleep(0.5)
    threading.Thread(target=_loop, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silencio en consola
        pass

    # ── helpers ──
    def _send(self, code, body=b"", ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    # ── GET ──
    def do_GET(self):
        p = urlparse(self.path)
        route = p.path

        if route in ("/", "/index.html"):
            return self._file(UI_DIR / "index.html")
        if route.startswith("/ui/"):
            return self._file(UI_DIR / route[4:])

        if route == "/api/stores":
            # ?retailer=sodimac|falabella (estáticas) | construmart (descubre en vivo)
            retailer = (parse_qs(p.query).get("retailer") or ["sodimac"])[0]
            try:
                from orchestrators import stores_for_retailer, discover_stores_desktop
                if retailer == "construmart":
                    loop = _new_loop(); asyncio.set_event_loop(loop)
                    try:
                        stores = loop.run_until_complete(discover_stores_desktop("construmart"))
                    finally:
                        loop.close()
                    return self._json(stores)
                return self._json(stores_for_retailer(retailer))
            except Exception as e:  # noqa: BLE001
                tb = traceback.format_exc()
                print("  [ERROR /api/stores]\n" + tb, flush=True)
                return self._json({"error": str(e), "detail": tb[-1500:]}, 500)

        if route == "/api/sections":
            # descubre el árbol (abre navegador una vez); puede tardar ~20s.
            # ?ferni=1 → sin isLanding. ?retailer=sodimac|falabella|construmart.
            try:
                from orchestrators import discover_sections_desktop
                q = parse_qs(p.query)
                incl = (q.get("ferni") or ["0"])[0] != "1"
                retailer = (q.get("retailer") or ["sodimac"])[0]
                loop = _new_loop()
                asyncio.set_event_loop(loop)
                try:
                    tree = loop.run_until_complete(
                        discover_sections_desktop(lambda e: None, include_landing=incl, retailer=retailer))
                finally:
                    loop.close()
                return self._json(tree)
            except Exception as e:  # noqa: BLE001
                tb = traceback.format_exc()
                print("  [ERROR /api/sections]\n" + tb, flush=True)  # visible en la consola
                return self._json({"error": str(e), "detail": tb[-1500:]}, 500)

        if route == "/api/events":
            job_id = (parse_qs(p.query).get("job") or [""])[0]
            return self._sse(job_id)

        if route == "/api/status":
            # resumen de jobs vivos (para reconectar / debug)
            return self._json({
                "active": _active_count(), "max": MAX_CONCURRENT,
                "jobs": [{"id": jid, "tool": j["tool"], "running": j["running"],
                          "error": j["error"]} for jid, j in JOBS.items()]})

        if route == "/api/download":
            q = parse_qs(p.query)
            f = unquote((q.get("f") or [""])[0])
            path = Path(f)
            if not path.is_file() or OUTPUT_DIR not in path.resolve().parents:
                return self._json({"error": "archivo no encontrado"}, 404)
            data = path.read_bytes()
            return self._send(200, data,
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                              {"Content-Disposition": f'attachment; filename="{path.name}"'})

        if route in ("/api/open", "/api/reveal"):
            # La app corre LOCAL → los Excel ya están en el disco del usuario. En la
            # ventana nativa (pywebview) los "downloads" del navegador no funcionan;
            # acá se ABRE el archivo con su app (Excel) o se MUESTRA la carpeta.
            q = parse_qs(p.query)
            f = unquote((q.get("f") or [""])[0])
            path = Path(f)
            if not path.is_file() or OUTPUT_DIR not in path.resolve().parents:
                return self._json({"error": "archivo no encontrado"}, 404)
            try:
                _open_path(str(path), reveal=(route == "/api/reveal"))
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)}, 500)
            return self._json({"ok": True})

        if route == "/api/template":
            # genera el 'formato de carga' al vuelo (mismo diseño que el Colab)
            tool = (parse_qs(p.query).get("tool") or ["mk7"])[0]
            try:
                from orchestrators import build_template_bytes
                fname, data = build_template_bytes(tool)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)}, 500)
            return self._send(200, data,
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                              {"Content-Disposition": f'attachment; filename="{fname}"'})

        if route == "/api/outputs":
            files = sorted(OUTPUT_DIR.glob("*.xlsx"), key=lambda f: -f.stat().st_mtime)[:20]
            out = []
            for f in files:
                st = f.stat()
                out.append({"name": f.name, "path": str(f), "size": st.st_size,
                            "mtime": int(st.st_mtime * 1000)})  # epoch ms
            return self._json(out)

        return self._json({"error": "not found"}, 404)

    def _file(self, path: Path):
        if not path.is_file():
            return self._json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return self._send(200, path.read_bytes(), ctype)

    def _sse(self, job_id):
        j = JOBS.get(job_id)
        if j is None:
            return self._json({"error": "job desconocido"}, 404)
        q = j["events"]  # la cola ya existe (se creó al lanzar el job)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                try:
                    ev = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")  # evita que el proxy corte
                    self.wfile.flush()
                    continue
                self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
                if ev.get("type") == "eof":
                    break
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ── POST ──
    def do_POST(self):
        p = urlparse(self.path)

        if p.path == "/api/upload":
            # el archivo llega crudo; el nombre va en el header X-Filename
            name = self.headers.get("X-Filename") or "entrada.xlsx"
            dest = UPLOAD_DIR / f"{name}"
            dest.write_bytes(self._body())
            return self._json({"path": str(dest), "name": name})

        if p.path == "/api/delete":
            # borra un Excel generado; sólo dentro de OUTPUT_DIR (mismo guard que download)
            payload = json.loads(self._body() or b"{}")
            path = Path(payload.get("path") or "")
            if not path.is_file() or OUTPUT_DIR not in path.resolve().parents:
                return self._json({"error": "archivo no encontrado"}, 404)
            try:
                path.unlink()
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)}, 500)
            return self._json({"ok": True})

        if p.path == "/api/rename":
            # renombra un Excel generado; sólo dentro de OUTPUT_DIR, conserva .xlsx
            payload = json.loads(self._body() or b"{}")
            src = Path(payload.get("path") or "")
            if not src.is_file() or OUTPUT_DIR not in src.resolve().parents:
                return self._json({"error": "archivo no encontrado"}, 404)
            base = Path(payload.get("name") or "").name  # descarta cualquier ruta
            base = re.sub(r'[<>:"/\\|?*]', "", base).strip()
            if not base:
                return self._json({"error": "nombre inválido"}, 400)
            if not base.lower().endswith(".xlsx"):
                base += ".xlsx"
            dest = src.parent / base
            if dest.exists():
                return self._json({"error": "ya existe un archivo con ese nombre"}, 409)
            try:
                src.rename(dest)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)}, 500)
            return self._json({"ok": True, "path": str(dest), "name": base})

        if p.path == "/api/cancel":
            payload = json.loads(self._body() or b"{}")
            j = JOBS.get(payload.get("job") or "")
            if not j or not j["running"]:
                return self._json({"error": "el proceso no está corriendo"}, 404)
            loop, task = j.get("loop"), j.get("task")
            if loop is not None and task is not None:
                loop.call_soon_threadsafe(task.cancel)  # cancela en el hilo del job
            return self._json({"ok": True})

        if p.path == "/api/run":
            payload = json.loads(self._body() or b"{}")
            tool = payload.get("tool")
            from orchestrators import TOOLS
            if tool not in TOOLS:
                return self._json({"error": f"herramienta desconocida: {tool}"}, 400)
            params = payload.get("params") or {}
            with JOBS_LOCK:
                _gc_jobs()
                if _active_count() >= MAX_CONCURRENT:
                    return self._json(
                        {"error": f"Ya hay {MAX_CONCURRENT} procesos corriendo. "
                                  "Espera a que termine uno."}, 409)
                job_id = uuid.uuid4().hex[:12]
                JOBS[job_id] = {"running": True, "events": queue.Queue(),
                                "result": None, "error": None, "tool": tool,
                                "retailer": params.get("retailer", "sodimac"),
                                "done_at": None}
                # Presupuesto de workers de Fast repartido entre los Fast activos
                # (incluye este job, recién registrado): carga total ~constante.
                # EXPERIMENTAL: además descuenta ~2 workers por cada job CON NAVEGADOR
                # que también le pega a Sodimac, para no sobrecargar la IP al mezclar
                # herramientas (era la causa de los challenges/429). Si molesta, se saca.
                if tool == "fast":
                    n_fast = _active_fast_count()
                    budget = max(2, FAST_WORKER_BUDGET - 2 * _sodimac_browser_jobs())
                    params["_workers"] = max(2, budget // max(1, n_fast))
            threading.Thread(target=_run_job, args=(job_id, tool, params),
                             daemon=True).start()
            return self._json({"ok": True, "job_id": job_id})

        return self._json({"error": "not found"}, 404)


def serve(port=8733):
    _ensure_browser()   # navegador en ruta persistente antes de aceptar pedidos
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    _hide_console_persistently()  # Windows: esconde la consola (la app es la ventana nativa)
    return httpd
