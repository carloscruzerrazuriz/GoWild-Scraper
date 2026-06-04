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

# ─── Columnas de cada hoja (EN INGLÉS — requerimiento del cliente) ───────────
PRODUCTO_COLS = [
    "Store", "SKU", "Upload Desc.", "Name", "Brand", "Part Number",
    "Category", "Category 2", "Category 3",
    "Transfer Price", "Debit Price", "Card Price", "Reference Price",
    "BancoEstado Price", "Discount %", "Promo Start", "Promo End",
    "Total Stock", "Internet Stock", "Stores w/ Stock",
    "Warranty (months)", "Warranty Agreement", "Digital", "Wholesale",
    "Images", "Video", "Main Image", "URL",
]
SPEC_COLS = ["SKU", "Name", "Group", "Specification", "Value"]
STOCK_COLS = ["SKU", "Name", "Zone", "Store", "Quantity",
              "Pickup", "Shipping", "Closed"]
IMG_COLS = ["SKU", "Name", "#", "URL"]


def _f(x):
    """Castea a float; '' si no se puede (los precios vienen como string)."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return ""


def _flag(x):
    """Normaliza booleanos que la API entrega como bool o como 'True'/'False'."""
    return "Yes" if str(x) == "True" or x is True else ""


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
                "SKU": pid, "Name": nombre, "Zone": zona,
                "Store": s.get("nombre", ""), "Quantity": apr,
                "Pickup": _flag(s.get("retiro")), "Shipping": _flag(s.get("despacho")),
                "Closed": _flag(s.get("cerrada")),
            })

    # Especificaciones (formato largo).
    spec_rows = []
    for g in det.get("especificaciones") or []:
        grupo = g.get("grupo", "")
        for it in g.get("detalle") or []:
            spec_rows.append({
                "SKU": pid, "Name": nombre, "Group": grupo,
                "Specification": it.get("nombre", ""), "Value": it.get("valor", ""),
            })

    # Imágenes (galería) + thumbnail para embeber.
    img_rows, main_img = [], ""
    for i, im in enumerate(imgs):
        u = _best_image(im.get("sizes"))
        if i == 0:
            main_img = u
        img_rows.append({"SKU": pid, "Name": nombre, "#": i + 1, "URL": u})
    embed_img = ((imgs[0].get("sizes") or {}).get("200") or main_img) if imgs else ""

    gar = det.get("garantia") or {}

    def _cat(c):
        c = c or {}
        return c.get("nombre", "") if str(c.get("id")) not in ("None", "") else ""

    producto = {
        "Store": "PCFactory", "SKU": pid, "Upload Desc.": desc or "",
        "Name": nombre, "Brand": (det.get("marca") or {}).get("nombre", ""),
        "Part Number": det.get("partNumber", "") or "",
        "Category": _cat(det.get("categoria")),
        "Category 2": _cat(det.get("categoria2")),
        "Category 3": _cat(det.get("categoria3")),
        "Transfer Price": efectivo, "Debit Price": debito,
        "Card Price": normal, "Reference Price": referencia,
        "BancoEstado Price": bancoestado,
        "Discount %": base.pct_discount(base_price, efectivo),
        "Promo Start": (promo.get("inicio") or "")[:16] if promo.get("inicio") else "",
        "Promo End": (promo.get("termino") or "")[:16] if promo.get("termino") else "",
        "Total Stock": (det.get("stock") or {}).get("aproximado", ""),
        "Internet Stock": stock_internet, "Stores w/ Stock": n_with,
        "Warranty (months)": gar.get("mesesDuracion", "") or "",
        "Warranty Agreement": gar.get("acuerdo", "") or "",
        "Digital": _flag(det.get("digital")), "Wholesale": _flag(det.get("mayorista")),
        "Images": len(imgs), "Video": _video_url(det.get("descripcion", "")),
        "Main Image": main_img, "URL": base.product_url(det.get("slug")),
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

    # Hoja 1 — Products (1 fila por producto).
    ws = wb.active
    ws.title = "Products"
    cols = list(PRODUCTO_COLS) + (["Image"] if with_images else [])
    ws.append(cols)
    for r in data["productos"]:
        ws.append([r.get(c, "") for c in cols])
    apply_clean_style(ws, skip_width=("URL", "Image", "Main Image"))
    if with_images:
        base._embed_images(ws, data["productos"], len(cols))

    # Hojas largas — Specifications / Stock by store / Images.
    for title, sheet_cols, key in (
        ("Specifications", SPEC_COLS, "especificaciones"),
        ("Stock by store", STOCK_COLS, "stock"),
        ("Images", IMG_COLS, "imagenes"),
    ):
        wsx = wb.create_sheet(title)
        wsx.append(sheet_cols)
        for r in data[key]:
            wsx.append([r.get(c, "") for c in sheet_cols])
        apply_clean_style(wsx, skip_width=("URL", "Image", "Main Image"))

    wb.save(path)
