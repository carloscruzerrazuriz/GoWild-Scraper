# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""PCFactory — Ficha Completa por SKU.

Al estilo del MK7, el usuario sube una lista de SKU (= el id de PCFactory) y esta
herramienta NO lee la card: entra al detalle de cada producto vía la API pública
y extrae TODO lo que la ficha muestra:

  - precios (efectivo/transferencia, débito, normal, referencia/tachado, BancoEstado)
    + vigencia de la promoción + % de descuento.
  - stock POR TIENDA (las ~29 sucursales, con retiro/despacho/cerrada por sucursal).
  - especificaciones técnicas completas (grupos → nombre/valor); el set de specs
    varía por categoría, por eso van en formato LARGO (una fila por especificación).
  - galería de imágenes (varios tamaños) + video de YouTube (si la ficha lo trae).
  - garantía, part number, breadcrumb de categorías, flags digital/mayorista.

Por cada SKU se consultan 4 endpoints (detalle, precio, stock, imágenes) en
paralelo; y los productos de la lista también se resuelven en paralelo (hilos).
Salida = workbook multi-hoja (Productos / Especificaciones / Stock por tienda /
Imágenes), pensado para que las dimensiones "ragged" (specs y stock) no rompan
una tabla plana.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from engines import pcf_base as base

RETAILER_NAME = "PCFactory"

_CATALOGO = f"{base.API_BASE}/pcfactory-services-catalogo/v1/catalogo"
_IFRAME_RE = re.compile(r'<iframe[^>]*src=["\']([^"\']+)', re.I)

# ─── Columnas de cada hoja ───────────────────────────────────────────────────
PRODUCTO_COLS = [
    "Tienda", "SKU", "Desc. Carga", "Nombre", "Marca", "Part Number",
    "Categoría", "Categoría 2", "Categoría 3",
    "Precio Efectivo", "Precio Débito", "Precio Normal", "Precio Referencia",
    "Precio BancoEstado", "% Descuento", "Promo Inicio", "Promo Término",
    "Stock Total", "Stock Internet", "N° Tiendas c/Stock",
    "Garantía (meses)", "Garantía Acuerdo", "Digital", "Mayorista",
    "N° Imágenes", "Video", "Imagen Principal", "URL",
]
SPEC_COLS = ["SKU", "Nombre", "Grupo", "Especificación", "Valor"]
STOCK_COLS = ["SKU", "Nombre", "Zona", "Sucursal", "Cantidad",
              "Retiro", "Despacho", "Cerrada"]
IMG_COLS = ["SKU", "Nombre", "#", "URL"]


def _f(x):
    """Castea a float; '' si no se puede (los precios vienen como string)."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return ""


def _flag(x):
    """Normaliza booleanos que la API entrega como bool o como 'True'/'False'."""
    return "Sí" if str(x) == "True" or x is True else ""


def _video_url(html):
    """Primer iframe de YouTube/Vimeo embebido en la descripción HTML ('' si no hay)."""
    if not html:
        return ""
    for src in _IFRAME_RE.findall(html):
        low = src.lower()
        if any(k in low for k in ("youtube", "youtu.be", "vimeo", "/embed/")):
            return src
    return ""


def _best_image(sizes):
    """URL de mejor calidad razonable de un dict de tamaños (1000 → 500 → original)."""
    sizes = sizes or {}
    return sizes.get("1000") or sizes.get("500") or sizes.get("0") or ""


def _safe_json(url):
    try:
        return base.http_json(url)
    except Exception:
        return None


def fetch_product(pid):
    """Trae los 4 endpoints de un producto en paralelo. Valores None si fallan."""
    eps = {
        "detalle":  f"{_CATALOGO}/productos/{pid}",
        "precio":   f"{_CATALOGO}/productos/{pid}/precio",
        "stock":    f"{_CATALOGO}/productos/{pid}/stock",
        "imagenes": f"{_CATALOGO}/productos/{pid}/imagenes",
    }
    out = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(_safe_json, u): k for k, u in eps.items()}
        for fut in as_completed(futs):
            out[futs[fut]] = fut.result()
    return out


def _build(pid, desc, data):
    """Arma el registro estructurado de un producto. None si no existe (sin detalle)."""
    det = data.get("detalle") or {}
    if not det or not det.get("nombre"):
        return None
    nombre = det.get("nombre", "")
    pre = (data.get("precio") or {}).get("precio") or {}
    disp = (data.get("stock") or {}).get("disponibilidad") or []
    imgs = (data.get("imagenes") or {}).get("imagenes") or []

    efectivo = _f(pre.get("efectivo"))
    normal = _f(pre.get("normal"))
    debito = _f(pre.get("debito"))
    referencia = _f(pre.get("referencia"))
    bancoestado = _f(pre.get("bancoEstado"))
    base_price = referencia if referencia not in ("", 0, 0.0) else normal
    promo = pre.get("promocion") or {}

    # Stock por tienda (formato largo) + métricas resumidas.
    stock_rows, n_with, stock_internet = [], 0, ""
    for z in disp:
        zona = z.get("zona", "")
        for s in z.get("sucursales") or []:
            apr = str(s.get("aproximado", "0"))
            if s.get("nombre") == "Internet":
                stock_internet = apr
            if apr not in ("0", "None", ""):
                n_with += 1
            stock_rows.append({
                "SKU": pid, "Nombre": nombre, "Zona": zona,
                "Sucursal": s.get("nombre", ""), "Cantidad": apr,
                "Retiro": _flag(s.get("retiro")), "Despacho": _flag(s.get("despacho")),
                "Cerrada": _flag(s.get("cerrada")),
            })

    # Especificaciones (formato largo).
    spec_rows = []
    for g in det.get("especificaciones") or []:
        grupo = g.get("grupo", "")
        for it in g.get("detalle") or []:
            spec_rows.append({
                "SKU": pid, "Nombre": nombre, "Grupo": grupo,
                "Especificación": it.get("nombre", ""), "Valor": it.get("valor", ""),
            })

    # Imágenes (galería) + thumbnail para embeber.
    img_rows, main_img = [], ""
    for i, im in enumerate(imgs):
        u = _best_image(im.get("sizes"))
        if i == 0:
            main_img = u
        img_rows.append({"SKU": pid, "Nombre": nombre, "#": i + 1, "URL": u})
    embed_img = ((imgs[0].get("sizes") or {}).get("200") or main_img) if imgs else ""

    gar = det.get("garantia") or {}

    def _cat(c):
        c = c or {}
        return c.get("nombre", "") if str(c.get("id")) not in ("None", "") else ""

    producto = {
        "Tienda": "PCFactory", "SKU": pid, "Desc. Carga": desc or "",
        "Nombre": nombre, "Marca": (det.get("marca") or {}).get("nombre", ""),
        "Part Number": det.get("partNumber", "") or "",
        "Categoría": _cat(det.get("categoria")),
        "Categoría 2": _cat(det.get("categoria2")),
        "Categoría 3": _cat(det.get("categoria3")),
        "Precio Efectivo": efectivo, "Precio Débito": debito,
        "Precio Normal": normal, "Precio Referencia": referencia,
        "Precio BancoEstado": bancoestado,
        "% Descuento": base.pct_discount(base_price, efectivo),
        "Promo Inicio": (promo.get("inicio") or "")[:16] if promo.get("inicio") else "",
        "Promo Término": (promo.get("termino") or "")[:16] if promo.get("termino") else "",
        "Stock Total": (det.get("stock") or {}).get("aproximado", ""),
        "Stock Internet": stock_internet, "N° Tiendas c/Stock": n_with,
        "Garantía (meses)": gar.get("mesesDuracion", "") or "",
        "Garantía Acuerdo": gar.get("acuerdo", "") or "",
        "Digital": _flag(det.get("digital")), "Mayorista": _flag(det.get("mayorista")),
        "N° Imágenes": len(imgs), "Video": _video_url(det.get("descripcion", "")),
        "Imagen Principal": main_img, "URL": base.product_url(det.get("slug")),
        "_img": embed_img,
    }
    return {"producto": producto, "especificaciones": spec_rows,
            "stock": stock_rows, "imagenes": img_rows}


def scrape_skus(skus, *, on_product=None, progress_cb=None, max_workers=6):
    """Resuelve la ficha completa de cada SKU (en paralelo).

    `skus`: lista de (sku_id, desc). `progress_cb(ev)`: eventos
    'product' (done/total/sku/ok) y 'complete' (ok/notfound). Devuelve un dict con
    las 4 colecciones + la lista de no encontrados.

    Los SKU se normalizan (str + strip) y se **deduplican** conservando el primer
    `desc` (un SKU repetido en el Excel no duplica filas en la salida).
    """
    seen, deduped = set(), []
    for s, d in skus:
        sid = str(s).strip()
        if sid and sid not in seen:
            seen.add(sid)
            deduped.append((sid, d))
    skus = deduped
    results = [None] * len(skus)

    def work(i):
        pid, desc = skus[i]
        return i, _build(pid, desc, fetch_product(pid))

    done, total = 0, len(skus)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(work, i) for i in range(len(skus))]
        for fut in as_completed(futs):
            i, rec = fut.result()
            results[i] = rec
            done += 1
            if progress_cb:
                progress_cb({"event": "product", "done": done, "total": total,
                             "sku": skus[i][0], "ok": rec is not None})

    out = {"productos": [], "especificaciones": [], "stock": [], "imagenes": [], "notfound": []}
    for i, rec in enumerate(results):
        if rec is None:
            out["notfound"].append(skus[i][0])
            continue
        out["productos"].append(rec["producto"])
        out["especificaciones"].extend(rec["especificaciones"])
        out["stock"].extend(rec["stock"])
        out["imagenes"].extend(rec["imagenes"])
        if on_product:
            on_product(rec["producto"])
    if progress_cb:
        progress_cb({"event": "complete", "total": total,
                     "ok": len(out["productos"]), "notfound": out["notfound"]})
    return out


def write_excel(data, path, *, with_images=False):
    """Escribe el workbook multi-hoja con la estética unificada del proyecto."""
    import openpyxl
    from engines._excel_utils import apply_clean_style

    wb = openpyxl.Workbook()

    # Hoja 1 — Productos (1 fila por producto).
    ws = wb.active
    ws.title = "Productos"
    cols = list(PRODUCTO_COLS) + (["Imagen"] if with_images else [])
    ws.append(cols)
    for r in data["productos"]:
        ws.append([r.get(c, "") for c in cols])
    apply_clean_style(ws)
    if with_images:
        base._embed_images(ws, data["productos"], len(cols))

    # Hojas largas — Especificaciones / Stock por tienda / Imágenes.
    for title, sheet_cols, key in (
        ("Especificaciones", SPEC_COLS, "especificaciones"),
        ("Stock por tienda", STOCK_COLS, "stock"),
        ("Imágenes", IMG_COLS, "imagenes"),
    ):
        wsx = wb.create_sheet(title)
        wsx.append(sheet_cols)
        for r in data[key]:
            wsx.append([r.get(c, "") for c in sheet_cols])
        apply_clean_style(wsx)

    wb.save(path)
