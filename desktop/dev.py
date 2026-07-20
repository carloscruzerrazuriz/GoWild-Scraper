# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved. Proprietary.
"""Arranque de DESARROLLO: usa el código del repo local, sin bajar de GitHub."""
import sys, threading, webbrowser
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "desktop"))
import server
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8733
httpd = server.serve(port)
print(f"DEV en http://127.0.0.1:{port}/  · salidas: {server.OUTPUT_DIR}", flush=True)
if "--open" in sys.argv:
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
httpd.serve_forever()
