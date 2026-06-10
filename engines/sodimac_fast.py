# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Sodimac Fast — scraper híbrido browserless (mucho más rápido que MK7/Maestra).

Idea (estilo PCFactory): el `/buscar` y las páginas de categoría de Sodimac son
SSR y embeben `__NEXT_DATA__` con los productos y precios YA contextualizados por
zona. La zona se fija con cookies. Entonces:

  1. Se usa Playwright UNA sola vez por zona para `set_zone` y capturar el jar de
     cookies (y una vez para descubrir el árbol de secciones).
  2. TODO el resto (las queries /buscar y la paginación de categorías) se hace por
     HTTP plano (urllib) leyendo el `__NEXT_DATA__` → sin render, sin screenshots,
     sin extracción por card. Verificado en vivo 2026-06-09.

Único modo (experimental): scrape_sections(...) — "Maestra Sección" (recorre
categorías). El modo "Buscador por SKU" (estilo MK7) fue descartado (2026-06-10):
para búsqueda por SKU se usa el MK7 de producción.

Trade-off vs los engines con navegador: NO trae Precio CMR / Mayorista / Precios
Congelados ni fotos (esos sólo salen del DOM). Sí trae precio normal/internet,
% descuento, vendedor, marca, descripción y URL — rápido.
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.request

from engines import sodimac_engine as _se
from engines import maestra_sodimac as _ms

BASE_URL = "https://www.sodimac.cl/sodimac-cl"
USER_AGENT = _se.USER_AGENT
ALL_STORES = _se.ALL_STORES
DEFAULT_GUARD_SKUS = _se.DEFAULT_GUARD_SKUS
DEFAULT_BATCH_SIZE = 24          # sin render → podemos pedir más por query
MAX_PAGES_PER_SUBCAT = 60
SELLER_FACET = _ms.SODIMAC_SELLER_FACET

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

# Columnas de salida (mismas convenciones que la Maestra de producción).
SECCION_COLS = [
    "Tienda", "Nombre Tienda", "Sección", "Subcategoría", "Vendedor", "Marca",
    "SKU", "Descripción Producto", "Precio Normal", "Precio Internet",
    "% Descuento", "En Oferta", "Precio Mayorista", "Promos", "URL",
]


# ── HTTP + parsing ──────────────────────────────────────────────────────────
def _cookie_header(cookies) -> str:
    """Convierte el jar de Playwright (list de dicts) a header 'Cookie'."""
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


def _fetch_results(url, cookie, *, retries=3):
    """GET `url` con la cookie de zona y devuelve results[] del __NEXT_DATA__ ([] si nada)."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT, "Cookie": cookie,
                "Accept": "text/html,application/xhtml+xml",
            })
            with urllib.request.urlopen(req, timeout=40, context=_CTX) as r:
                html = r.read().decode("utf-8", "replace")
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
            if not m:
                last = "no __NEXT_DATA__"
                continue
            return _find_results(json.loads(m.group(1))) or []
        except Exception as e:  # noqa: BLE001
            last = e
    return []


def _find_results(obj):
    """Busca recursivamente la lista `results` dentro del __NEXT_DATA__."""
    if isinstance(obj, dict):
        if isinstance(obj.get("results"), list):
            return obj["results"]
        for v in obj.values():
            r = _find_results(v)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for x in obj:
            r = _find_results(x)
            if r is not None:
                return r
    return None


def _num(price_str):
    """'$ 21.990' -> 21990.0 (o None)."""
    if not price_str:
        return None
    digits = re.sub(r"[^\d]", "", str(price_str))
    return float(digits) if digits else None


def _discounts(r):
    """Analiza prices[] + promotions[] y devuelve la info de descuento.

    Distingue lo que en la web es "está en oferta" (precio tachado `crossed` en
    prices[]) de las promociones CONDICIONALES de promotions[] (campañas de
    evento tipo CES, descuento empleado, envío gratis, precio mayorista PRO).
    Devuelve dict: pct (oferta de vitrina), en_oferta, mayorista, promos.
    """
    internet, normal = _se._prices_from_json(r.get("prices"))
    # % de vitrina: precio tachado (normal) vs internet — coincide con el badge web.
    pct = ""
    n, i = _num(normal), _num(internet)
    if n and i and i < n:
        pct = f"-{round(100 * (n - i) / n)}%"
    en_oferta = "Sí" if pct else ""

    mayorista = ""
    promos = []
    for pr in (r.get("promotions") or []):
        camp = (pr.get("campaignName") or "").strip()
        desc = (pr.get("description") or "").strip()
        dp = (pr.get("metadata") or {}).get("discountPercent")
        pp = pr.get("prices") or []
        pprice = f"$ {pp[0]['price'][0]}" if (pp and pp[0].get("price")) else ""
        blob = f"{camp} {desc}".upper()
        # Ignorar condicionales que NO son oferta pública de precio:
        if camp == "ENVIO_PLUS" or "COLABORADOR" in blob or "EMPLEAD" in blob:
            continue
        if camp == "PRECIO+PRO" or "MAYORISTA" in blob:
            mayorista = mayorista or pprice
            continue
        if dp:
            tag = camp or desc or "Promo"
            promos.append(f"{tag} -{int(dp)}%" + (f" {pprice}" if pprice else ""))
    return {"internet": internet, "normal": normal, "pct": pct,
            "en_oferta": en_oferta, "mayorista": mayorista,
            "promos": " | ".join(promos)}


def _raw(r):
    """Normaliza un result del JSON a campos crudos comunes a ambos modos."""
    d = _discounts(r)
    b = r.get("brand")
    marca = b.get("brandName") if isinstance(b, dict) else (b or "")
    url = r.get("url") or ""
    if url.startswith("/"):
        url = f"https://www.sodimac.cl{url}"
    return {
        "sku": str(r.get("skuId", "")).strip(),
        "vendedor": r.get("sellerName") or "",
        "marca": marca or "",
        "descripcion": r.get("displayName") or "",
        "precio_internet": d["internet"],
        "precio_normal": d["normal"],
        "pct_descuento": d["pct"],
        "en_oferta": d["en_oferta"],
        "precio_mayorista": d["mayorista"],
        "promos": d["promos"],
        "url": url,
        "is_sodimac": "SODIMAC" in (r.get("sellerId", "") or r.get("sellerName", "") or "").upper(),
    }


# ── Handshake de zona (único uso del navegador) ─────────────────────────────
async def fetch_zone_cookie(store, *, headless=True, browser=None):
    """Abre (o reusa) un browser, hace warmup + set_zone y devuelve el header Cookie.

    Devuelve "" si set_zone falla (la zona se saltea, igual que el MK7).
    """
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    async def _do(b):
        ctx = await b.new_context(user_agent=USER_AGENT)
        pg = await ctx.new_page()
        try:
            # warmup ANTES de set_zone: en Colab la IP de Google recibe el
            # challenge de Cloudflare y warmup_session lo limpia + fija tokens de
            # sesión. Sin warmup, set_zone falla en TODAS las zonas en Colab (sí
            # funciona desde IP local, por eso el bug se coló). Igual que el MK7/
            # Maestra de producción. (2026-06-09)
            await _se.warmup_session(pg)
            ok = await _se.set_zone(pg, store["region"], store["comuna"])
            if not ok:
                ok = await _se.set_zone(pg, store["region"], store["comuna"])
            if not ok:
                return ""
            return _cookie_header(await ctx.cookies())
        finally:
            await ctx.close()

    if browser is not None:
        return await _do(browser)
    async with Stealth().use_async(async_playwright()) as pw:
        b = await pw.chromium.launch(headless=headless,
                                     args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            return await _do(b)
        finally:
            await b.close()


async def discover_sections(*, headless=True):
    """Descubre el árbol de secciones (browser, una vez). [(sección,[(subcat,url)])]."""
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth
    async with Stealth().use_async(async_playwright()) as pw:
        b = await pw.chromium.launch(headless=headless,
                                     args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            ctx = await b.new_context(user_agent=USER_AGENT)
            pg = await ctx.new_page()
            await _se.warmup_session(pg)
            return await _ms.discover_sections(pg)
        finally:
            await b.close()


# ── Maestra Sección (recorre categorías) — ÚNICO modo de Sodimac Fast ────────
# NOTA: el modo "Buscador por SKU" (estilo MK7) fue DESCARTADO (2026-06-10). Para
# búsqueda por SKU se usa el MK7 de producción; Sodimac Fast es sólo experimental
# para Sección.
async def scrape_sections(subcats, stores, *, headless=True, progress_cb=None,
                          on_row=None, only_sodimac=True):
    """Recorre las subcategorías elegidas en cada zona vía urllib (paginando JSON).

    `subcats`: lista de ((seccion, subcat), subcat_url). Devuelve rows (SECCION_COLS).
    Eventos: zone_start, subcat_start, subcat_page, subcat_done, zone_done, complete.
    """
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    rows = []
    facet = SELLER_FACET if only_sodimac else None

    async with Stealth().use_async(async_playwright()) as pw:
        b = await pw.chromium.launch(headless=headless,
                                     args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            for store in stores:
                if progress_cb:
                    progress_cb({"event": "zone_start", "store": store, "n_subcats": len(subcats)})
                cookie = await fetch_zone_cookie(store, browser=b)
                if not cookie:
                    if progress_cb:
                        progress_cb({"event": "zone_done", "store": store, "zone_failed": True})
                    continue
                for idx, (label, sub_url) in enumerate(subcats, start=1):
                    seccion, subcat = label if isinstance(label, (tuple, list)) else ("", label)
                    if progress_cb:
                        progress_cb({"event": "subcat_start", "store": store,
                                     "section": seccion, "subcat": subcat,
                                     "idx": idx, "total": len(subcats)})
                    seen = set()
                    page_n, stale = 1, 0
                    while page_n <= MAX_PAGES_PER_SUBCAT:
                        sep = "&" if "?" in sub_url else "?"
                        url = sub_url + sep + (f"{facet}&" if facet else "") + f"page={page_n}"
                        res = _fetch_results(url, cookie)
                        new = 0
                        for r in res:
                            d = _raw(r)
                            if not d["sku"] or d["sku"] in seen:
                                continue
                            seen.add(d["sku"])
                            new += 1
                            if only_sodimac and not d["is_sodimac"]:
                                continue
                            rows.append({
                                "Tienda": store["id"], "Nombre Tienda": store["name"],
                                "Sección": seccion, "Subcategoría": subcat,
                                "Vendedor": d["vendedor"], "Marca": d["marca"],
                                "SKU": d["sku"], "Descripción Producto": d["descripcion"],
                                "Precio Normal": d["precio_normal"],
                                "Precio Internet": d["precio_internet"],
                                "% Descuento": d["pct_descuento"], "En Oferta": d["en_oferta"],
                                "Precio Mayorista": d["precio_mayorista"], "Promos": d["promos"],
                                "URL": d["url"],
                            })
                            if on_row:
                                on_row(rows[-1])
                        if progress_cb:
                            progress_cb({"event": "subcat_page", "store": store,
                                         "subcat": subcat, "page": page_n, "n_new": new})
                        # Cortar cuando una página no aporta SKUs nuevos (2 seguidas).
                        if new == 0:
                            stale += 1
                            if stale >= 1:
                                break
                        else:
                            stale = 0
                        page_n += 1
                    if progress_cb:
                        progress_cb({"event": "subcat_done", "store": store,
                                     "subcat": subcat, "idx": idx, "total": len(subcats)})
                if progress_cb:
                    progress_cb({"event": "zone_done", "store": store, "zone_failed": False})
        finally:
            await b.close()
    if progress_cb:
        progress_cb({"event": "complete", "n_rows": len(rows)})
    return rows


# ── Excel (1 hoja; browserless = sin fotos) ─────────────────────────────────
def write_excel(rows, output_file, *, columns=None):
    """Escribe 1 hoja 'Datos' con la estética unificada (sin fotos: es browserless)."""
    import pandas as pd
    from engines._excel_utils import apply_clean_style, apply_url_truncation
    import openpyxl

    if not rows:
        return False
    cols = columns or SECCION_COLS
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    df = df[cols]
    df.to_excel(output_file, index=False, sheet_name="Datos")
    try:
        wb = openpyxl.load_workbook(output_file)
        ws = wb["Datos"]
        if "URL" in cols:
            uc = cols.index("URL") + 1
            apply_url_truncation(ws, uc, uc + 1, url_width=40, total_rows=len(df) + 1)
        apply_clean_style(ws)
        wb.save(output_file)
    except Exception:
        pass
    return True
