# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Helpers compartidos para el formato de los Excel de salida.

Lo que ofrece:
  - filter_and_reorder(df, columns): filtra el DataFrame a las columnas especificadas
    en ese orden. Columnas faltantes en df se crean vacías.
  - apply_url_truncation(ws, url_col_idx, next_col_idx): le da a la columna URL
    el estilo "texto clipeado" (no wrap, no shrink, no overflow). Para que Excel
    no derrame el texto a la columna siguiente, escribe " " en cualquier celda
    contigua que esté vacía.
  - download_once(path, files_module): dispara files.download() evitando descargas
    duplicadas del mismo archivo dentro de una ventana de debounce (Colab a veces
    re-dispara el JS de descarga al re-renderizar un Output widget).
"""
from __future__ import annotations

import time as _time

import openpyxl
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter


# path -> timestamp de la última descarga disparada
_LAST_DOWNLOADS: dict[str, float] = {}


def download_once(path, files_module, *, debounce_secs: float = 6.0) -> bool:
    """Dispara files_module.download(path) una sola vez por ventana de debounce.

    Devuelve True si disparó la descarga, False si la omitió por duplicado.
    El botón "descargar de nuevo" funciona igual porque el click manual ocurre
    bien después de la ventana de debounce.
    """
    if files_module is None:
        return False
    p = str(path)
    now = _time.time()
    last = _LAST_DOWNLOADS.get(p, 0.0)
    if now - last < debounce_secs:
        return False
    _LAST_DOWNLOADS[p] = now
    files_module.download(p)
    return True


def filter_and_reorder(df, columns: list[str]):
    """Devuelve df solo con las columnas dadas, en ese orden. Crea vacías las faltantes."""
    for c in columns:
        if c not in df.columns:
            df[c] = ""
    return df[columns].copy()


def apply_url_truncation(ws, url_col_idx: int, next_col_idx: int | None, *,
                         url_width: int = 40, total_rows: int | None = None) -> None:
    """Aplica el estilo de texto clipeado a la columna URL.

    - url_col_idx, next_col_idx: 1-based.
    - url_width: ancho de la columna URL (en unidades de Excel).
    - Si next_col_idx está dado, escribe " " en celdas vacías de esa columna
      para evitar overflow visual de URL.
    """
    align = Alignment(horizontal="left", vertical="center", wrap_text=False, shrink_to_fit=False)
    ws.column_dimensions[get_column_letter(url_col_idx)].width = url_width

    if total_rows is None:
        total_rows = ws.max_row

    for ri in range(2, total_rows + 1):
        ws.cell(row=ri, column=url_col_idx).alignment = align
        if next_col_idx is not None:
            nxt = ws.cell(row=ri, column=next_col_idx)
            if nxt.value is None or nxt.value == "":
                nxt.value = " "
