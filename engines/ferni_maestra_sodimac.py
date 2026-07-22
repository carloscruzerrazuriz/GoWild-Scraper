# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Ferni Maestra Sodimac — recorre el árbol de categorías de Sodimac y extrae
cada producto con la lógica de variantes de Ferni (medidas exactas para puertas
"y más"): productos con selector de medidas se expanden en una fila por medida
con su precio exacto; el resto, una fila normal con 'Medida' vacía.

Reutiliza VERBATIM la maquinaria probada del Maestra Sodimac de producción
(descubrimiento del árbol, set_zone, navegación/paginación, breadcrumb) — la
importa, no la duplica, así no hay riesgo para el Maestra original. Lo único
distinto es la EXTRACCIÓN: en vez de leer el DOM de cada card (que para puertas
da el rango "desde $X"), parsea props.pageProps.results[].variants[] del
__NEXT_DATA__ (igual que engines/ferni_sodimac.py).

Las páginas de categoría traen el mismo __NEXT_DATA__ con variants[] que el
buscador, incluso en page=2+ (verificado 2026-06-02).
"""

import re
from pathlib import Path

import pandas as pd
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from engines import maestra_sodimac as _ms

# Reuso directo de la infraestructura probada del Maestra de producción.
BASE_URL              = _ms.BASE_URL
ALL_STORES            = _ms.ALL_STORES
SELECTORS             = _ms.SELECTORS
MAX_PAGES_PER_SUBCAT  = _ms.MAX_PAGES_PER_SUBCAT
SODIMAC_SELLER_FACET  = _ms.SODIMAC_SELLER_FACET
discover_sections     = _ms.discover_sections
set_zone              = _ms.set_zone
set_zone_with_retry   = _ms.set_zone_with_retry
_safe_goto            = _ms._safe_goto
_detect_breadcrumb    = _ms._detect_breadcrumb

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# ─────────────────────────────────────────  Extracción (variants JSON)  ────

# Lee el __NEXT_DATA__ de la PLP y devuelve UNA fila por medida (productos con
# variantes SIZES) o una fila por producto (sin variantes). Mismo criterio que
# engines/ferni_sodimac.py pero para todos los productos de la página.
_EXTRACT_MAESTRA_VARIANTS_JS = r"""(args) => {
    const section = args.section, subcat = args.subcat;
    const s = document.getElementById('__NEXT_DATA__');
    if (!s) return [];
    let d; try { d = JSON.parse(s.textContent); } catch (e) { return []; }
    const r = d?.props?.pageProps?.results;
    if (!Array.isArray(r)) return [];
    const firstP = (a) => (Array.isArray(a) ? a[0] : a) || '';
    const pickPrice = (prices) => {
        let internet = '', normal = '';
        for (const p of (prices || [])) {
            const v = firstP(p.price);
            if (p.crossed) { if (!normal) normal = v; }
            else { if (!internet) internet = v; }
        }
        return {internet, normal};
    };
    const rows = [];
    for (const p of r) {
        const base = {
            "Sección": section, "Subcategoría": subcat,
            "Marca": p.brand || '', "Vendedor": p.sellerName || '',
            "Descripción Producto": p.displayName || '',
            "product_id": String(p.productId || ''),
        };
        const sz = (p.variants || []).find(v => v.type === 'SIZES');
        const options = sz ? (sz.options || []) : [];
        if (options.length) {
            const allSizes = options
                .map(o => `${o.size || o.value}: $${firstP((o.prices || []).find(x => !x.crossed)?.price)}`)
                .join(' | ');
            for (const o of options) {
                const pr = pickPrice(o.prices);
                rows.push(Object.assign({}, base, {
                    "SKU": String(o.variant), "Medida": o.size || o.value || '',
                    "Precio Normal": pr.normal, "Precio Internet": pr.internet,
                    "Todas las Medidas": allSizes, "URL": (o.url || '').split('?')[0],
                }));
            }
        } else {
            const pr = pickPrice(p.prices);
            rows.push(Object.assign({}, base, {
                "SKU": String(p.skuId || ''), "Medida": '',
                "Precio Normal": pr.normal, "Precio Internet": pr.internet,
                "Todas las Medidas": '', "URL": (p.url || '').split('?')[0],
            }));
        }
    }
    return rows;
}"""

# Mapea cada card (grid-pod) a su productId leyendo el href /articulo/{pid}/...
_CARD_PID_JS = r"""(card) => {
    const a = card.querySelector('a[href*="/articulo/"]');
    if (!a) return '';
    const m = (a.href || '').match(/\/articulo\/(\d+)/);
    return m ? m[1] : '';
}"""


def _price_to_int(s):
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", str(s))
    return int(digits) if digits else None


def _pct_descuento(normal, internet):
    n, i = _price_to_int(normal), _price_to_int(internet)
    if n and i and n > 0 and i < n:
        return f"-{round((1 - i / n) * 100)}%"
    return ""


# ─────────────────────────────────────────  Scrape de una subcategoría  ────

async def scrape_subcat_variants(page, section_name, subcat_name, subcat_url,
                                 *, only_sodimac=True, capture_screenshots=True,
                                 screenshot_dir=None, page_progress_cb=None):
    """Pagina una subcategoría y extrae filas (una por medida) desde el JSON.

    Mantiene la navegación/paginación del Maestra de producción; cambia solo la
    extracción (variants[] en vez de DOM) y captura screenshots por productId
    (porque al expandir medidas hay más filas que cards). Devuelve dict con
    rows/pages/truncated/failed/empty."""
    import json
    result = {"rows": [], "pages": 0, "truncated": False, "failed": False, "empty": False}

    if only_sodimac:
        sep = "&" if "?" in subcat_url else "?"
        subcat_url = f"{subcat_url}{sep}{SODIMAC_SELLER_FACET}"

    if not await _safe_goto(page, subcat_url):
        result["failed"] = True
        return result

    if screenshot_dir:
        screenshot_dir = Path(screenshot_dir)
        screenshot_dir.mkdir(parents=True, exist_ok=True)

    seen_in_subcat = set()
    page_num = 1
    total_pages = None
    base_url = None

    while True:
        try:
            await page.wait_for_selector(
                f'{SELECTORS["card"]}, {SELECTORS["no_results"]}', timeout=15000)
        except Exception:
            if page_num == 1:
                result["empty"] = True
            break

        has_cards = await page.evaluate(
            f"() => document.querySelectorAll({json.dumps(SELECTORS['card'])}).length")
        if not has_cards:
            if page_num == 1:
                result["empty"] = True
            break

        await page.wait_for_timeout(1200)

        # Quitar overlays + lazy-load via scroll (necesario para screenshots).
        await page.evaluate("""() => {
            const r = () => document.querySelectorAll('[data-testid="overlay"], [class*="overlay"], [class*="Modal"], [class*="Tooltip"]').forEach(o => o.remove());
            r(); setTimeout(r, 500);
        }""")
        for _ in range(5):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(250)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(400)

        # Extracción JSON (una evaluate por página).
        try:
            page_rows = await page.evaluate(
                _EXTRACT_MAESTRA_VARIANTS_JS,
                {"section": section_name, "subcat": subcat_name})
        except Exception:
            page_rows = []

        # Screenshots por productId (reusadas para todas las medidas del producto).
        if capture_screenshots and screenshot_dir and page_rows:
            want_pids = {str(d.get("product_id", "")) for d in page_rows if d.get("product_id")}
            pid_to_path = {}
            try:
                cards = await page.query_selector_all(SELECTORS["card"])
            except Exception:
                cards = []
            for card in cards:
                try:
                    pid = (await card.evaluate(_CARD_PID_JS) or "").strip()
                except Exception:
                    pid = ""
                if not pid or pid not in want_pids or pid in pid_to_path:
                    continue
                img_path = screenshot_dir / f"{re.sub(r'[^0-9]', '_', pid)}.jpg"
                if not img_path.exists():
                    try:
                        await card.scroll_into_view_if_needed()
                        await page.wait_for_timeout(100)
                        await card.screenshot(path=str(img_path), type="jpeg", quality=80)
                    except Exception:
                        pass
                if img_path.exists() and img_path.stat().st_size > 0:
                    pid_to_path[pid] = str(img_path)
            for d in page_rows:
                d["Image Path"] = pid_to_path.get(str(d.get("product_id", "")), "")
        else:
            for d in page_rows:
                d["Image Path"] = ""

        if not page_rows:
            break

        new_in_page = 0
        for d in page_rows:
            sku = d.get("SKU")
            if sku and sku not in seen_in_subcat:
                seen_in_subcat.add(sku)
                result["rows"].append(d)
                new_in_page += 1

        result["pages"] = page_num
        if base_url is None:
            try:
                base_url = page.url
            except Exception:
                base_url = subcat_url

        # Detectar total de páginas desde el paginador.
        try:
            await page.evaluate("""() => {
                const p = document.querySelector('[id^="testId-pagination-top-"]');
                if (p) p.scrollIntoView({behavior:'instant', block:'center'});
            }""")
            await page.wait_for_timeout(400)
        except Exception:
            pass
        try:
            detected_total = await page.evaluate("""() => {
                const nodes = document.querySelectorAll('[id^="testId-pagination-"]');
                let max = 1;
                nodes.forEach(n => {
                    const txt = ((n.textContent || '') + ' ' + (n.getAttribute('aria-label') || '')).trim();
                    (txt.match(/\\d+/g) || []).forEach(m => {
                        const num = parseInt(m, 10);
                        if (!isNaN(num) && num > max && num < 1000) max = num;
                    });
                });
                return max;
            }""")
        except Exception:
            detected_total = None
        if detected_total and detected_total > 1:
            if total_pages is None or detected_total > total_pages:
                total_pages = detected_total

        if page_progress_cb is not None:
            try:
                page_progress_cb(page_num, total_pages)
            except Exception:
                pass

        if total_pages and page_num >= total_pages:
            break
        next_page_num = page_num + 1
        if next_page_num > MAX_PAGES_PER_SUBCAT:
            result["truncated"] = True
            break

        navigated = False
        if total_pages and next_page_num <= total_pages and base_url:
            base = re.sub(r"([?&])page=\d+&?", r"\1", base_url).rstrip("?&")
            sep = "&" if "?" in base else "?"
            page_url = f"{base}{sep}page={next_page_num}"
            try:
                if await _safe_goto(page, page_url):
                    navigated = True
            except Exception:
                navigated = False
        if not navigated:
            await page.evaluate("""() => document.querySelectorAll('[data-testid="overlay"], [class*="overlay"]').forEach(o => o.remove())""")
            next_btn = await page.query_selector(f'{SELECTORS["pagination_next"]}:not([disabled])')
            if not next_btn:
                break
            if new_in_page == 0 and not total_pages:
                break
            try:
                await next_btn.click(force=True, timeout=15000)
            except Exception:
                break

        page_num = next_page_num
        await page.wait_for_timeout(1200)
        if page_num > MAX_PAGES_PER_SUBCAT:
            result["truncated"] = True
            break

    return result


# ─────────────────────────────────────────  Warm-up  ───────────────────────

async def _warmup(page):
    try:
        await page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 350)")
            await page.wait_for_timeout(500)
    except Exception:
        pass


# ─────────────────────────────────────────  Orquestador multi-zona  ────────

async def scrape_maestra(
    subcats: list[tuple],
    stores: list[dict],
    *,
    only_sodimac: bool = True,
    headless: bool = True,
    screenshot_dir=None,
    progress_cb=None,
    on_row=None,
    done_keys=None,
):
    """Recorre cada subcategoría en cada zona. `subcats` es lista de
    (section_name, subcat_name, subcat_url). Devuelve list[dict] de filas
    (una por medida) con Tienda/Nombre Tienda + Image Path.

    Eventos de progreso:
      browser_launching / browser_ready / browser_error
      warmup_start / warmup_done {store}
      zone_start {store, n_subcats}
      subcat_start {store, section, subcat, idx, total}
      subcat_page {store, subcat, page, total_pages}
      subcat_done {store, subcat, n_rows, empty, failed, truncated}
      zone_end {store, n_rows, zone_failed}
      complete {rows, stats}
    """
    rows_all: list[dict] = []
    n_subcats = len(subcats)
    done = set(done_keys or ())  # set de (store_id, subcat_url) ya completados

    async def _run_zone(browser, store) -> bool:
        # Si TODA la tienda ya está hecha (resume), saltarla sin abrir contexto.
        if done and all((store["id"], u) in done for (_s, _n, u) in subcats):
            for idx, (section_name, subcat_name, subcat_url) in enumerate(subcats, 1):
                if progress_cb:
                    progress_cb({"event": "subcat_done", "store": store, "subcat": subcat_name,
                                 "subcat_url": subcat_url, "idx": idx, "total": n_subcats,
                                 "n_rows": 0, "skipped": True})
            if progress_cb:
                progress_cb({"event": "zone_end", "store": store, "n_rows": 0,
                             "zone_failed": False, "skipped": True})
            return True
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900}, color_scheme="light",
            user_agent=USER_AGENT)
        page = await ctx.new_page()
        try:
            if progress_cb: progress_cb({"event": "warmup_start", "store": store})
            await _warmup(page)
            if progress_cb: progress_cb({"event": "warmup_done", "store": store})

            ok = await set_zone_with_retry(page, store["region"], store["comuna"])
            if not ok:
                if progress_cb:
                    progress_cb({"event": "zone_end", "store": store,
                                 "n_rows": 0, "zone_failed": True})
                return False

            if progress_cb:
                progress_cb({"event": "zone_start", "store": store, "n_subcats": n_subcats})

            zone_shots = (Path(screenshot_dir) / store["id"]) if screenshot_dir else None
            zone_rows = 0
            for idx, (section_name, subcat_name, subcat_url) in enumerate(subcats, 1):
                # Resume: si esta (tienda, subcategoría) ya está hecha, saltarla.
                if (store["id"], subcat_url) in done:
                    if progress_cb:
                        progress_cb({"event": "subcat_done", "store": store, "subcat": subcat_name,
                                     "subcat_url": subcat_url, "idx": idx, "total": n_subcats,
                                     "n_rows": 0, "skipped": True})
                    continue
                if progress_cb:
                    progress_cb({"event": "subcat_start", "store": store,
                                 "section": section_name, "subcat": subcat_name,
                                 "subcat_url": subcat_url, "idx": idx, "total": n_subcats})

                def _ppcb(pg, tot, _sn=subcat_name):
                    if progress_cb:
                        progress_cb({"event": "subcat_page", "store": store,
                                     "subcat": _sn, "page": pg, "total_pages": tot})

                try:
                    res = await scrape_subcat_variants(
                        page, section_name, subcat_name, subcat_url,
                        only_sodimac=only_sodimac, capture_screenshots=bool(zone_shots),
                        screenshot_dir=zone_shots, page_progress_cb=_ppcb)
                except Exception:
                    res = {"rows": [], "empty": False, "failed": True, "truncated": False}

                for d in res.get("rows", []):
                    # Filtro "solo Sodimac" post-proceso por Vendedor (igual que Maestra).
                    if only_sodimac:
                        v = (d.get("Vendedor") or "").strip().upper()
                        if v and "SODIMAC" not in v:
                            continue
                    row = dict(d, **{"Tienda": store["id"], "Nombre Tienda": store["name"]})
                    row["% Descuento"] = _pct_descuento(d.get("Precio Normal"), d.get("Precio Internet"))
                    rows_all.append(row)
                    if on_row:
                        on_row(row)
                    zone_rows += 1

                if progress_cb:
                    progress_cb({"event": "subcat_done", "store": store,
                                 "subcat": subcat_name, "subcat_url": subcat_url,
                                 "idx": idx, "total": n_subcats,
                                 "n_rows": len(res.get("rows", [])),
                                 "empty": res.get("empty"), "failed": res.get("failed"),
                                 "truncated": res.get("truncated"), "skipped": False})

            if progress_cb:
                progress_cb({"event": "zone_end", "store": store,
                             "n_rows": zone_rows, "zone_failed": False})
            return True
        finally:
            try:
                await ctx.close()
            except Exception:
                pass

    if progress_cb: progress_cb({"event": "browser_launching"})
    launch_args = ["--no-sandbox", "--disable-dev-shm-usage"]
    async with Stealth().use_async(async_playwright()) as pw:
        try:
            browser = await pw.chromium.launch(headless=headless, args=launch_args, timeout=60_000)
        except Exception as e:
            if progress_cb: progress_cb({"event": "browser_error", "stage": "launch", "msg": str(e)})
            return []
        if progress_cb: progress_cb({"event": "browser_ready"})
        failed_stores = []
        for store in stores:
            try:
                ok = await _run_zone(browser, store)
            except Exception:
                ok = False
            if not ok:
                failed_stores.append(store)
        for store in failed_stores:
            try:
                await _run_zone(browser, store)
            except Exception:
                pass
        await browser.close()

    stats = {"total_rows": len(rows_all), "n_zones": len(stores), "n_subcats": n_subcats}
    if progress_cb:
        progress_cb({"event": "complete", "rows": rows_all, "stats": stats})
    return rows_all


# ─────────────────────────────────────────  Excel output  ──────────────────

OUTPUT_COLS = [
    "Tienda", "Nombre Tienda", "Región", "Zona", "Sección", "Subcategoría", "Marca", "SKU",
    "Descripción Producto", "Medida", "Vendedor", "Precio Normal",
    "Precio Internet", "% Descuento", "Todas las Medidas", "URL",
]


def write_excel(rows, output_file, *, with_images=False):
    """1 hoja "Datos" (sin fotos) o, si with_images, 2 hojas "Datos" + "Con fotos"
    (mismos datos + screenshot de la card embebida). Mismo formato que el MK7."""
    from ._excel_utils import write_two_sheets_df
    from . import _locales_easy as _loc
    if rows:
        _loc.enrich_rows(rows)  # Región/Zona por id de tienda
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=OUTPUT_COLS)
    for c in OUTPUT_COLS:
        if c not in df.columns:
            df[c] = ""
    out = df[OUTPUT_COLS].copy()  # sin columna Imagen
    write_two_sheets_df(out, rows or [], output_file, with_images=with_images,
                        text_cols=("SKU",), img_w=170, img_h=200)
    return output_file
