# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Sube filas de producto Sodimac a la Maestra (Google Sheet auto-actualizada).

Cada engine Sodimac (MK7 / Maestra Sección / Fast) llama `post_maestra(rows, fuente)`
tras un scrape exitoso. El Apps Script dedicado hace UPSERT por (SKU × Tienda):
la última corrida gana. Esquema = UNIÓN de columnas de las 3 fuentes; cada una
llena lo que tiene y el resto queda en blanco. SIN imágenes.

Acepta tanto las filas ya "canónicas" (Maestra/Fast, con keys OUTPUT_COLS) como las
crudas del MK7 (keys tipo store_id / precio_normal / SKU Sodimac) → mapeo con
fallbacks + enriquecimiento Región/Zona por id de tienda.

Defensivo por diseño: NUNCA lanza. Un fallo al consolidar no debe voltear un scrape.
Sólo stdlib (urllib) → funciona en Colab y en el desktop.
"""
from __future__ import annotations

import json
import ssl
import time as _t
import urllib.request

from . import _locales_easy as _loc

# ── Configuración ───────────────────────────────────────────────────────────
# URL del Web App dedicado (apps_script/Maestra_Sodimac.gs). Vacía = no-op seguro
# hasta que el titular despliegue el Apps Script y se pegue acá la URL /exec.
_MAESTRA_URL = ""
_TOKEN = "mS7_kR2vQ9xL4pN8wYtZ-bF3hGcE6uA1"  # mismo secreto que el Apps Script
_CHUNK = 400  # filas por request (mantiene cada POST bajo los límites de Apps Script)

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _first(r, *keys):
    for k in keys:
        v = r.get(k)
        if v not in (None, ""):
            return v
    return ""


def _master_row(r, fuente, ts):
    """Normaliza una fila de cualquier fuente al esquema de la maestra."""
    tienda = str(_first(r, "Tienda", "store_id")).strip()
    region = _first(r, "Región")
    zona = _first(r, "Zona")
    if not region or not zona:
        rz = _loc.region_zona(tienda)
        region = region or rz[0]
        zona = zona or rz[1]
    return {
        "SKU": str(_first(r, "SKU", "SKU Sodimac", "sku")).strip(),
        "Tienda": tienda,
        "SKU Easy": _first(r, "SKU Easy"),
        "Nombre Tienda": _first(r, "Nombre Tienda", "store_found"),
        "Región": region,
        "Zona": zona,
        "Sección": _first(r, "Sección"),
        "Subcategoría": _first(r, "Subcategoría"),
        "Marca": _first(r, "Marca", "marca"),
        "Descripción": _first(r, "Descripción Producto", "descripcion", "Desc. Producto"),
        "Vendedor": _first(r, "Vendedor", "vendedor"),
        "Precio Normal": _first(r, "Precio Normal", "precio_normal"),
        "Precio Internet": _first(r, "Precio Internet", "precio_internet"),
        "% Descuento": _first(r, "% Descuento", "pct_descuento"),
        "Precio Mayorista": _first(r, "Precio Mayorista", "precio_mayorista"),
        "Descuento Mayorista": _first(r, "Descuento Mayorista", "descuento_mayorista"),
        "Todos los Precios": _first(r, "Todos los Precios", "todos_los_precios"),
        "URL": _first(r, "URL", "url"),
        "Fuente": fuente,
        "Última Actualización": ts,
    }


def post_maestra(rows, fuente, *, url=None):
    """Sube `rows` a la Maestra (upsert por SKU×Tienda). `fuente` = 'MK7'/'Maestra'/'Fast'.

    Devuelve dict con {ok, sent} o {ok:False, ...}. NUNCA lanza.
    """
    url = url or _MAESTRA_URL
    if not url or not rows:
        return {"ok": False, "skipped": True}
    try:
        ts = _t.strftime("%Y-%m-%d %H:%M:%S")
        mapped = [_master_row(r, fuente, ts) for r in rows]
        mapped = [m for m in mapped if m["SKU"] and m["Tienda"]]  # sólo llaves válidas
        sent = 0
        for i in range(0, len(mapped), _CHUNK):
            chunk = mapped[i:i + _CHUNK]
            body = json.dumps({"type": "maestra_sodimac", "token": _TOKEN,
                               "fuente": fuente, "rows": chunk}).encode("utf-8")
            req = urllib.request.Request(url, data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90, context=_CTX) as resp:
                resp.read()
            sent += len(chunk)
        return {"ok": True, "sent": sent}
    except Exception as e:  # noqa: BLE001 — defensivo: no romper el scrape
        return {"ok": False, "error": str(e)[:120]}
