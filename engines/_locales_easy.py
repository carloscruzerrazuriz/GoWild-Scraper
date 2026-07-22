# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Región y Zona por tienda Easy — fuente única para el output de los engines.

Datos de "Locales y Zonas" (42 tiendas Easy). La 'Zona' es el código comercial
(CA, CB, …) del maestro de locales. Se usa para agregar las columnas 'Región' y
'Zona' al output de las herramientas Sodimac, justo después de 'Nombre Tienda'.

Las filas de los engines ya traen 'Tienda' (id Easy, ej. E522); con eso se
resuelve Región/Zona sin tocar la lógica de scraping.
"""
from __future__ import annotations

# id Easy -> (Región nombre completo, Zona código)
LOCALES = {
    "E502": ("Región Metropolitana", "CA"),
    "E503": ("Región Metropolitana", "CA"),
    "E504": ("Región Ohiggins", "CC"),
    "E506": ("Región Araucanía", "CF"),
    "E507": ("Región de los Lagos", "CG"),
    "E508": ("Región Valparaíso", "CB"),
    "E510": ("Región Metropolitana", "CA"),
    "E511": ("Región Metropolitana", "CA"),
    "E512": ("Región Metropolitana", "CA"),
    "E513": ("Región Metropolitana", "CA"),
    "E514": ("Región Metropolitana", "CA"),
    "E517": ("Región Araucanía", "CF"),
    "E518": ("Región Metropolitana", "CA"),
    "E520": ("Región Valparaíso", "CB"),
    "E521": ("Región Coquimbo", "CJ"),
    "E522": ("Región Metropolitana", "CA"),
    "E524": ("Región Del Maule", "CD"),
    "E525": ("Región Ñuble", "CE"),
    "E529": ("Región Bio Bio", "CE"),
    "E534": ("Región Antofagasta", "CH"),
    "E585": ("Región de los Lagos", "CG"),
    "E591": ("Región Del Maule", "CD"),
    "E592": ("Región Del Maule", "CD"),
    "E614": ("Región Antofagasta", "CH"),
    "E619": ("Región Arica", "CL"),
    "E633": ("Región Bio Bio", "CK"),
    "E643": ("Región Metropolitana", "CA"),
    "E646": ("Región Valparaíso", "CB"),
    "E655": ("Región Metropolitana", "CA"),
    "E659": ("Región Metropolitana", "CA"),
    "E744": ("Región de los Lagos", "E744"),
    "E748": ("Región de los Lagos", "E748"),
    "E760": ("Región Atacama", "CI"),
    "E775": ("Región Metropolitana", "CA"),
    "E781": ("Región Valparaíso", "CB"),
    "E830": ("Región de los Lagos", "E830"),
    "E843": ("Región Metropolitana", "CA"),
    "E874": ("Región Metropolitana", "CA"),
    "E900": ("Región Metropolitana", "CA"),
    "E983": ("Región Bio Bio", "CK"),
    "E988": ("Región Metropolitana", "CA"),
    "E990": ("Región Bio Bio", "CK"),
}

# Nuevas columnas de salida (van INMEDIATAMENTE después de 'Nombre Tienda').
COLS = ["Región", "Zona"]


def region_zona(store_id):
    """(Región, Zona) para un id Easy; ('', '') si no está en el maestro."""
    return LOCALES.get(str(store_id or "").strip(), ("", ""))


def enrich_rows(rows, id_key="Tienda"):
    """Agrega 'Región' y 'Zona' a cada dict-fila según su id de tienda. In-place."""
    for r in rows:
        reg, zona = region_zona(r.get(id_key))
        r["Región"], r["Zona"] = reg, zona
    return rows


def insert_after(columns, anchor="Nombre Tienda"):
    """Devuelve `columns` con Región/Zona insertadas justo después de `anchor`.
    Si `anchor` no está, las agrega al final. Idempotente (no duplica)."""
    cols = [c for c in columns if c not in COLS]
    if anchor in cols:
        i = cols.index(anchor) + 1
        return cols[:i] + list(COLS) + cols[i:]
    return cols + list(COLS)
