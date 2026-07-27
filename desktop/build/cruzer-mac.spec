# -*- mode: python ; coding: utf-8 -*-
# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved. Proprietary.
"""PyInstaller spec de Cruzer para macOS → produce dist/Cruzer.app.

MISMO espíritu que cruzer.spec (Windows): el bundle NO empaqueta el código del
proyecto (engines/, server, UI); sólo el runtime de Python, las libs y el shell.
Todo lo demás se baja de GitHub al arrancar (thin-shell). Casi nunca hay que
reconstruirlo: sólo si cambian las dependencias o el shell.

⚠️ PyInstaller NO cross-compila: este spec debe construirse EN UN MAC (local o el
runner `macos-latest` del CI). arm64 (Apple Silicon) por defecto.
"""
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []

# Igual que en Windows: recolectar COMPLETOS los paquetes pesados que usa el
# código descargado (numpy 2.x carga extensiones C que sólo aparecen con
# collect_all; playwright arrastra su driver Node).
for pkg in ("playwright", "playwright_stealth", "numpy", "pandas",
            "openpyxl", "bs4", "PIL"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

hiddenimports += [
    "asyncio", "queue", "http.server", "socketserver",
    "urllib.request", "zipfile", "json", "csv", "sqlite3",
]

a = Analysis(
    ["../shell.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "ipywidgets", "notebook",
              "jupyter", "pytest", "PyQt5", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)

# .app = bundle de directorio → onedir (exclude_binaries + COLLECT + BUNDLE),
# que es lo más estable para macOS.
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Cruzer",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # sin ventana de terminal (nativo de macOS)
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Cruzer")
app = BUNDLE(
    coll,
    name="Cruzer.app",
    icon="cruzer.icns",
    bundle_identifier="cl.gowild.cruzer",
    info_plist={
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    },
)
