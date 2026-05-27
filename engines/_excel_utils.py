"""Helpers compartidos para el formato de los Excel de salida.

Lo que ofrece:
  - filter_and_reorder(df, columns): filtra el DataFrame a las columnas especificadas
    en ese orden. Columnas faltantes en df se crean vacías.
  - apply_url_truncation(ws, url_col_idx, next_col_idx): le da a la columna URL
    el estilo "texto clipeado" (no wrap, no shrink, no overflow). Para que Excel
    no derrame el texto a la columna siguiente, escribe " " en cualquier celda
    contigua que esté vacía.
"""
from __future__ import annotations

import openpyxl
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter


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
