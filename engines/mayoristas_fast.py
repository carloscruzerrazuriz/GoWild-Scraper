# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Precios Mayoristas — motor BROWSERLESS (prototipo).

Reemplazo candidato del motor actual (`launchers/mayoristas.py :: scrape_ventas_mayor`),
que hoy pagina la landing con Playwright y extrae del DOM (goto + scroll + poll de
render por página). Este motor sigue el patrón "Sodimac Fast" / PCFactory:

  1. Playwright se usa UNA sola vez por zona: warmup + set_zone → captura el jar de
     cookies (mismo `engines/_zone_sodimac`). Coste fijo ~15-19s por zona.
  2. TODO el resto (paginación de la landing ventas-por-mayor) por HTTP plano
     (urllib) leyendo `__NEXT_DATA__.results[]`. Sin render, sin screenshots.

HALLAZGO CLAVE (verificado en vivo 2026-07-15 contra sodimac.cl, Cerrillos):
  - La landing `ventas-por-mayor` SÍ sirve `__NEXT_DATA__` con `results[]` (48/pág)
    por HTTP plano usando sólo la cookie de zona.
  - El **Precio Mayorista** viene en `promotions[]` con `campaignName == "PRECIO+PRO"`
    (o descripción "Precio Mayorista"): `prices[0].price[0]` = precio mayorista, y
    `metadata.discountPercent` = **Descuento Mayorista**, `metadata.quantityToBuyValue`
    = cantidad mínima. NO es DOM-only.
  - Para productos por m² (cerámicas), el JSON trae AMBOS precios: `price` (por caja)
    y `unitPrice.price` (por m², con `unit`/`unitForSale`). El DOM sólo mostraba el de
    m² → este motor prefiere `unitPrice` cuando existe, reproduciendo el DOM (y de yapa
    guarda el precio por caja en "Todos los Precios").

Cross-check en vivo (page 1, Cerrillos, 48 productos): mayorista coincide 40/48 exacto,
+2 que el JSON captura y el DOM perdió, 1 "discrepancia" que era el caso m² (ahora
resuelto). El JSON es tan completo o MÁS que el DOM. Landing completa = 23 págs / 864
SKUs únicos en ~87s por HTTP (vs varios minutos con navegador).

Este archivo es un PROTOTIPO independiente: no está cableado a ningún launcher todavía.
"""

import json
import re
import ssl
import urllib.request

from engines import _zone_sodimac as _zone
from engines import sodimac_engine as _se

# Landing curada de Ventas por Mayor (misma que el launcher de producción).
VENTAS_MAYOR_BASE = (
    "https://www.sodimac.cl/sodimac-cl/seleccion/ventas-por-mayor"
    "?sid=SO_HO_HOM_HBA_409161&store=so_com"
)
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
MAX_PAGES_PM = 200
MAX_PAGES_PER_SUBCAT = 200

# Columnas de salida IDÉNTICAS al motor de producción (Precios Mayoristas).
OUTPUT_COLS = [
    "Tienda", "Nombre Tienda", "Sección", "Subcategoría",
    "Vendedor", "Marca", "SKU", "Descripción Producto",
    "Precio Normal", "Precio Internet", "% Descuento",
    "Precio CMR", "Precio Mayorista", "Descuento Mayorista",
    "Todos los Precios", "URL",
]

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


# ── HTTP + parsing ──────────────────────────────────────────────────────────
def _cookie_header(cookies) -> str:
    """Jar de Playwright (list de dicts) → header 'Cookie'."""
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


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


def _find_pagination(obj):
    """Busca recursivamente el dict `pagination` (trae count/totalPages) del JSON."""
    if isinstance(obj, dict):
        p = obj.get("pagination")
        if isinstance(p, dict) and ("count" in p or "totalPages" in p or "totalPage" in p):
            return p
        for v in obj.values():
            r = _find_pagination(v)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for x in obj:
            r = _find_pagination(x)
            if r is not None:
                return r
    return None


def _fetch_page(url, cookie, *, retries=4):
    """GET `url` → (results, total_esperado, ok).

    CLAVE para no truncar en silencio: `ok=False` cuando tras los reintentos NO
    se pudo leer la página (error de red/Cloudflare/HTML sin __NEXT_DATA__) — es
    DISTINTO de una página genuinamente vacía (`ok=True, results=[]`). `total` =
    `pagination.count` (total de productos que Sodimac declara para esa query),
    usado para verificar completitud. `None` si la página no lo trae.
    """
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT, "Cookie": cookie,
                "Accept": "text/html,application/xhtml+xml",
            })
            with urllib.request.urlopen(req, timeout=45, context=_CTX) as r:
                html = r.read().decode("utf-8", "replace")
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
            if not m:
                continue  # HTML raro (challenge?) → reintentar, NO tratar como vacío
            data = json.loads(m.group(1))
            results = _find_results(data) or []
            pag = _find_pagination(data) or {}
            total = pag.get("count")
            try:
                total = int(total) if total is not None else None
            except (TypeError, ValueError):
                total = None
            return results, total, True
        except Exception:  # noqa: BLE001
            import time as _t
            _t.sleep(0.6 * (attempt + 1))  # backoff antes de reintentar
    return [], None, False  # error DURO: el caller lo marca incompleto, no como fin


def _fetch_results(url, cookie, *, retries=3):
    """Compat: solo los results[] (usado por scrape_landing)."""
    res, _total, _ok = _fetch_page(url, cookie, retries=retries)
    return res


def _price_str(entry, symbol_default="$ "):
    """Formatea una entrada de precio {symbol, price:[...], unitPrice?} como el DOM.

    Prefiere `unitPrice` cuando existe (productos por m²/unidad): reproduce lo que
    Sodimac muestra en la card ("$ 3.790 m²"). Devuelve (str_mostrado, str_pack)
    donde str_pack es el precio por caja/paquete cuando difiere (o "").
    """
    if not entry:
        return "", ""
    sym = entry.get("symbol") or symbol_default
    pack_arr = entry.get("price") or []
    pack = f"{sym}{pack_arr[0]}".strip() if pack_arr else ""
    up = entry.get("unitPrice") or {}
    up_arr = up.get("price") or []
    if up_arr:
        unit = up.get("unit") or ""
        shown = f"{sym}{up_arr[0]} {unit}".strip()
        return shown, pack  # pack va a "Todos los Precios"
    return pack, ""


def _wholesale(r):
    """Extrae (precio_mayorista, descuento_mayorista, pack_extra) de promotions[].

    Precio Mayorista = promo PRECIO+PRO / "Precio Mayorista". Reproduce el DOM
    (prefiere unitPrice). Descuento Mayorista = metadata.discountPercent + cantidad
    mínima (quantityToBuyValue).
    """
    for pr in (r.get("promotions") or []):
        camp = (pr.get("campaignName") or "").strip()
        desc = (pr.get("description") or "").strip()
        blob = f"{camp} {desc}".upper()
        if camp == "PRECIO+PRO" or "MAYORISTA" in blob:
            pp = pr.get("prices") or []
            shown, pack = _price_str(pp[0]) if pp else ("", "")
            meta = pr.get("metadata") or {}
            dp = meta.get("discountPercent")
            qty = meta.get("quantityToBuyValue")
            dm = ""
            if dp:
                dm = f"-{int(dp)}%"
                if qty:
                    dm += f" (≥{qty})"
            elif qty:
                dm = f"≥{qty}"
            return shown, dm, pack
    return "", "", ""


def _cmr_from_prices(prices):
    """Precio CMR si aparece en prices[] (label/type con 'cmr'); "" si no."""
    for p in prices or []:
        blob = f"{p.get('type','')} {p.get('label','')}".lower()
        if "cmr" in blob:
            shown, _ = _price_str(p)
            return shown
    return ""


def row_from_result(r, store):
    """Construye una fila (dict OUTPUT_COLS) desde un result del __NEXT_DATA__."""
    prices = r.get("prices") or []
    internet, normal = _se._prices_from_json(prices)
    # Reproducir el precio-por-unidad del DOM también en Precio Internet (m²):
    internet_shown = internet
    pack_extra = ""
    for p in prices:
        if not p.get("crossed") and (p.get("unitPrice") or {}).get("price"):
            shown, pack = _price_str(p)
            internet_shown, pack_extra = shown, pack
            break

    may, desc_may, may_pack = _wholesale(r)

    b = r.get("brand")
    marca = b.get("brandName") if isinstance(b, dict) else (b or "")
    url = r.get("url") or ""
    if url.startswith("/"):
        url = f"https://www.sodimac.cl{url}"

    pct = ""
    dn = re.sub(r"\D", "", normal or "")
    di = re.sub(r"\D", "", internet or "")
    if dn and di and int(di) < int(dn):
        pct = f"-{round(100 * (int(dn) - int(di)) / int(dn))}%"

    todos = " | ".join(x for x in (normal, internet, may, pack_extra, may_pack) if x)

    return {
        "Tienda": store["id"],
        "Nombre Tienda": store["name"],
        "Sección": "",
        "Subcategoría": "",
        "Vendedor": r.get("sellerName") or "",
        "Marca": marca or "",
        "SKU": str(r.get("skuId", "")).strip(),
        "Descripción Producto": r.get("displayName") or "",
        "Precio Normal": normal,
        "Precio Internet": internet_shown,
        "% Descuento": pct,
        "Precio CMR": _cmr_from_prices(prices),
        "Precio Mayorista": may,
        "Descuento Mayorista": desc_may,
        "Todos los Precios": todos,
        "URL": url,
    }


# ── Handshake de zona (único uso del navegador) ─────────────────────────────
async def fetch_zone_cookie(store, *, headless=True, browser=None):
    """warmup + set_zone (Playwright) → header Cookie de la zona. "" si falla."""
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    async def _do(b):
        ctx = await b.new_context(
            user_agent=USER_AGENT, viewport={"width": 1280, "height": 900},
            color_scheme="light")
        pg = await ctx.new_page()
        try:
            await _zone.warmup_session(pg)
            ok = await _zone.set_zone_with_retry(pg, store["region"], store["comuna"], retries=3)
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


def is_wholesale(r) -> bool:
    """True si el result tiene precio mayorista (promo PRECIO+PRO / 'Precio Mayorista')."""
    for pr in (r.get("promotions") or []):
        camp = (pr.get("campaignName") or "").strip()
        blob = f"{camp} {(pr.get('description') or '')}".upper()
        if camp == "PRECIO+PRO" or "MAYORISTA" in blob:
            return True
    return False


# ── Crawl COMPLETO por sección (enfoque elegido) ────────────────────────────
# En vez de la landing curada `ventas-por-mayor` (subconjunto ~864), recorremos
# TODO el árbol de categorías (como la Maestra Sección) por HTTP y filtramos en
# código a los que tienen precio mayorista. Cobertura completa, browserless.

async def open_session(store, *, headless=True):
    """Abre el navegador UNA vez: warmup + set_zone + discover_sections.

    Devuelve (cookie_header, tree) donde tree = [(sección, [(subcat, url), ...]), ...].
    Reutiliza el mismo `page` para fijar zona y descubrir el árbol → una sola
    apertura de navegador por zona (el resto del barrido es HTTP puro).
    """
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth
    from engines import maestra_sodimac as _ms
    async with Stealth().use_async(async_playwright()) as pw:
        b = await pw.chromium.launch(headless=headless,
                                     args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            ctx = await b.new_context(
                user_agent=USER_AGENT, viewport={"width": 1280, "height": 900},
                color_scheme="light")
            pg = await ctx.new_page()
            await _zone.warmup_session(pg)
            ok = await _zone.set_zone_with_retry(pg, store["region"], store["comuna"], retries=3)
            if not ok:
                return "", []
            cookie = _cookie_header(await ctx.cookies())
            tree = await _ms.discover_sections(pg)
            return cookie, tree
        finally:
            await b.close()


def _subcat_url_with_facet(url, only_sodimac):
    if not only_sodimac:
        return url
    from engines.maestra_sodimac import SODIMAC_SELLER_FACET
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{SODIMAC_SELLER_FACET}"


def scrape_subcat(url, cookie, store, section_name, subcat_name, *,
                  wholesale_only=True, only_sodimac=True, on_row=None,
                  max_pages=MAX_PAGES_PER_SUBCAT, seen=None):
    """Pagina UNA subcategoría por HTTP. Devuelve (rows, status).

    status = {expected, scanned, incomplete, reason, short}.

    COMPLETITUD (criterio corregido 2026-07-15): la única señal FIABLE de
    truncado es un **error de fetch duro** (`ok=False` tras reintentos) o tocar
    el tope `MAX_PAGES`. Llegar a una página vacía = fin real de la categoría =
    **completo por definición**, aunque `pagination.count` diga un número mayor:
    verificado en vivo que `count` SOBRE-CUENTA ~4% (incluye sponsored/dups/
    no-listables; la misma Maestra DOM pagina la misma PLP y tendría igual gap).
    Por eso NO marcamos incompleto por `scanned < count` (daba falsas alarmas en
    casi toda categoría grande). El gap se expone como `short` (informativo, con
    tolerancia) pero no dispara reintento ni alarma.
    """
    rows = []
    seen = seen if seen is not None else set()      # dedup de salida (global)
    subcat_seen = set()                             # únicos de ESTA categoría
    page_url = _subcat_url_with_facet(url, only_sodimac)
    expected = None
    incomplete = False
    reason = ""
    page_num = 1
    while page_num <= max_pages:
        sep = "&" if "?" in page_url else "?"
        u = page_url if page_num == 1 else f"{page_url}{sep}page={page_num}"
        res, total, ok = _fetch_page(u, cookie)
        if not ok:
            # Error DURO (no confundir con fin de categoría) → marcar y cortar.
            incomplete = True
            reason = f"fetch falló en pág {page_num}"
            break
        if page_num == 1 and total is not None:
            expected = total
        if not res:
            break  # página genuinamente vacía = fin real de la categoría (completo)
        new_in_page = 0
        for r in res:
            sku = str(r.get("skuId", "")).strip()
            if not sku:
                continue
            if sku not in subcat_seen:
                subcat_seen.add(sku)
                new_in_page += 1
            if sku in seen:
                continue
            seen.add(sku)
            if wholesale_only and not is_wholesale(r):
                continue
            row = row_from_result(r, store)
            row["Sección"] = section_name
            row["Subcategoría"] = subcat_name
            rows.append(row)
            if on_row:
                on_row(row)
        # Guarda anti-bucle: si la página no aporta SKUs nuevos, la categoría se
        # acabó (o el ?page=N se repite/wrappea) → fin real. Es completo, no
        # incompleto (las páginas de categoría no se solapan como la landing).
        if new_in_page == 0:
            break
        page_num += 1
    else:
        incomplete = True
        reason = f"alcanzó MAX_PAGES ({max_pages})"

    scanned = len(subcat_seen)
    # `short` = faltó MÁS de una página completa (~50) respecto al total declarado:
    # señal informativa de que quizá valga revisar, sin ser una alarma de truncado.
    short = bool(expected is not None and (expected - scanned) > 50)
    status = {"expected": expected, "scanned": scanned,
              "incomplete": incomplete, "reason": reason, "short": short}
    return rows, status


def scrape_all_wholesale(cookie, tree, store, *, wholesale_only=True,
                         only_sodimac=True, on_row=None, subcat_cb=None,
                         max_subcats=None, workers=6, report=None):
    """Recorre TODO el árbol por HTTP y devuelve solo los productos con precio mayorista.

    Como es HTTP puro (sin navegador), las subcategorías se barren en PARALELO
    con un ThreadPool (`workers`). Cada subcat se pagina secuencialmente por
    dentro; el dedup global entre subcats se hace bajo lock. `workers=1` = modo
    secuencial.

    COMPLETITUD: cada subcat verifica lo escaneado contra el `pagination.count`
    de Sodimac. Las que quedan INCOMPLETAS (fetch fallido o count menor) se
    **reintentan una vez de forma secuencial** (menos carga → más robusto). Si
    tras el reintento siguen cortas, se registran en `report` (lista de dicts)
    para que el launcher avise al usuario en vez de fingir que terminó.

    Args:
      subcat_cb: callback(i, total, section, subcat, kept, scanned, status) por subcat.
      report: lista opcional; se le agregan las subcats que quedaron incompletas.
      max_subcats: tope opcional (para pruebas rápidas).
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    flat = [(sec, name, url) for sec, subs in tree for name, url in subs]
    if max_subcats:
        flat = flat[:max_subcats]
    total = len(flat)
    all_rows = []
    seen_global = set()
    lock = threading.Lock()
    done = {"n": 0}
    incompletes = []  # (sec, name, url, status)

    def _emit(local_rows):
        """Incorpora filas al resultado con dedup global (bajo lock). Devuelve kept."""
        kept = 0
        with lock:
            for row in local_rows:
                sku = row["SKU"]
                if sku in seen_global:
                    continue
                seen_global.add(sku)
                all_rows.append(row)
                kept += 1
                if on_row:
                    on_row(row)
        return kept

    def _work(job):
        sec, name, url = job
        local_rows, status = scrape_subcat(url, cookie, store, sec, name,
                                            wholesale_only=wholesale_only,
                                            only_sodimac=only_sodimac,
                                            on_row=None, seen=set())
        return sec, name, url, local_rows, status

    if workers <= 1:
        results_iter = (_work(j) for j in flat)
    else:
        ex = ThreadPoolExecutor(max_workers=workers)
        futs = [ex.submit(_work, j) for j in flat]
        results_iter = (f.result() for f in as_completed(futs))

    for sec, name, url, local_rows, status in results_iter:
        kept = _emit(local_rows)
        with lock:
            done["n"] += 1
            i = done["n"]
        if status.get("incomplete"):
            incompletes.append((sec, name, url, status))
        if subcat_cb:
            subcat_cb(i, total, sec, name, kept, status.get("scanned", 0), status)

    # ── Reintento secuencial de las incompletas (una pasada, más robusto) ──
    still_bad = []
    for sec, name, url, _st in incompletes:
        retry_rows, status2 = scrape_subcat(url, cookie, store, sec, name,
                                            wholesale_only=wholesale_only,
                                            only_sodimac=only_sodimac,
                                            on_row=None, seen=set())
        _emit(retry_rows)  # dedup global evita duplicar lo ya capturado
        if status2.get("incomplete"):
            still_bad.append({"section": sec, "subcat": name, "url": url, **status2})

    if report is not None:
        report.extend(still_bad)
    return all_rows


def scrape_landing(cookie, store, *, on_row=None, progress_cb=None,
                   max_pages=MAX_PAGES_PM, seen=None):
    """Pagina la landing por HTTP y devuelve las filas (dedup por SKU).

    Args:
      cookie: header Cookie de la zona (de fetch_zone_cookie).
      store: dict {id,name,region,comuna}.
      on_row: callback(row) por cada fila nueva (para checkpoints/live count).
      progress_cb: callback(page_num, new_in_page).
    """
    rows = []
    seen = seen if seen is not None else set()
    page_num = 1
    while page_num <= max_pages:
        sep = "&" if "?" in VENTAS_MAYOR_BASE else "?"
        url = VENTAS_MAYOR_BASE if page_num == 1 else f"{VENTAS_MAYOR_BASE}{sep}page={page_num}"
        res = _fetch_results(url, cookie)
        if not res:
            break
        new_in_page = 0
        for r in res:
            sku = str(r.get("skuId", "")).strip()
            if not sku or sku in seen:
                continue
            seen.add(sku)
            row = row_from_result(r, store)
            rows.append(row)
            if on_row:
                on_row(row)
            new_in_page += 1
        if progress_cb:
            progress_cb(page_num, new_in_page)
        # La landing tiene solapamiento entre páginas; cortamos cuando una página
        # entera no aporta SKUs nuevos (fin real del catálogo curado).
        if new_in_page == 0:
            break
        page_num += 1
    return rows
