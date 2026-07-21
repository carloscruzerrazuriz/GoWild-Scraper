# -*- mode: python ; coding: utf-8 -*-
# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved. Proprietary.
"""PyInstaller spec de Vulpex (Windows).

CLAVE: el .exe NO empaqueta el código del proyecto (engines/, desktop/server.py,
la UI…). Sólo lleva el runtime de Python, las librerías de terceros y el shell.
Todo lo demás se descarga desde GitHub en cada arranque, a una carpeta temporal
que se borra al cerrar.

Consecuencia práctica: **este ejecutable casi nunca hay que reconstruirlo**. Sólo
si cambian las dependencias — el equivalente al `launcher_schema` de los
notebooks. Un cambio de motores, de UI o de lógica sale por `git push`.

Como el shell no importa las librerías directamente (lo hace el código
descargado), PyInstaller no puede detectarlas solo → van en `hiddenimports`.
"""
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []

# Playwright trae un driver Node que hay que arrastrar entero.
for pkg in ("playwright", "playwright_stealth"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# Librerías que sólo usa el código descargado en runtime.
hiddenimports += [
    "pandas", "numpy",
    "openpyxl", "openpyxl.styles", "openpyxl.drawing.image", "openpyxl.utils",
    "bs4", "PIL", "PIL.Image",
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
    # Recortes: nada de GUI ni notebooks (la interfaz es el navegador).
    excludes=["tkinter", "matplotlib", "IPython", "ipywidgets", "notebook",
              "jupyter", "pytest", "PyQt5", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="Vulpex",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,          # el shell informa estado y hay que dejarla abierta
    disable_windowed_traceback=False,
    icon="vulpex.ico",     # ícono del .exe (horneado; cambiarlo obliga a recompilar)
)
