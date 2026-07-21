# -*- mode: python ; coding: utf-8 -*-
# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved. Proprietary.
"""PyInstaller spec de Cruzer (Windows).

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

# Paquetes "pesados" que usa el código descargado: hay que RECOLECTARLOS COMPLETOS
# (submódulos + binarios + datos), no basta listarlos como hiddenimport. numpy 2.x
# en particular carga extensiones C (numpy._core._multiarray_umath, _exceptions…)
# que sólo aparecen con collect_all; sin esto pandas/numpy revientan en runtime
# con "Importing the numpy C-extensions failed" (bug real de la v6 en Windows).
# playwright además arrastra su driver Node.
for pkg in ("playwright", "playwright_stealth", "numpy", "pandas",
            "openpyxl", "bs4", "PIL"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# Stdlib que el bootstrap/servidor usan (por si el análisis no las detecta).
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
    # Recortes: nada de GUI ni notebooks (la interfaz es el navegador).
    excludes=["tkinter", "matplotlib", "IPython", "ipywidgets", "notebook",
              "jupyter", "pytest", "PyQt5", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="Cruzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,          # el shell informa estado y hay que dejarla abierta
    disable_windowed_traceback=False,
    icon="cruzer.ico",     # ícono del .exe (horneado; cambiarlo obliga a recompilar)
)
