# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Competidores · Prodalam (Laravel + Angular SPA).

Es el más difícil (Tier C): la API de catálogo (`/api/products`) es **privada**
(devuelve 401 sin la sesión Angular) y el listado de categoría se hidrata por
JavaScript, así que NO sirve urllib. Solución: **navegador headless (Playwright)**
que renderiza la página y se extrae del DOM ya hidratado — el mismo patrón que la
Maestra de producción, pero encapsulado dentro del engine para que la UI común de
Competidores (síncrona) lo use sin saber que hay un browser detrás.

  - Árbol: del mega-menú (`categorias/{id}/{slug}`). Departamentos = ids de 1 dígito
    (1–9); sus hijos cuelgan del panel `ul.menu-multilevel` del menú.
  - Productos (PLP): cards `a[href*="/productos/"]` con `.brand`, `h6.product-title`
    y el precio; paginación `?page=N`.

Playwright async se ejecuta en un hilo con su propio event loop (`_run_async`) para
funcionar tanto en Colab (que ya tiene un loop corriendo) como fuera de él.
Precio único nacional → sin selector de zona.
"""
from __future__ import annotations

import re

from engines import comp_base as _b

write_excel = _b.write_excel    # re-export del contrato uniforme
OUTPUT_COLS = _b.OUTPUT_COLS

RETAILER_NAME = "Prodalam"
USES_BROWSER = True
BASE = "https://www.prodalam.cl"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_MAX_PAGES = 60       # tope de seguridad por subcategoría
_NAV_TIMEOUT = 60000


# ─── Runner async-en-hilo (funciona dentro y fuera de un event loop) ─────────
def _run_async(coro):
    """Corre una corutina en un hilo con event loop propio y devuelve el resultado.

    Evita el choque con el loop ya corriendo en Colab/Jupyter (donde asyncio.run
    y el sync API de Playwright fallan).
    """
    import asyncio
    import threading
    box = {}

    def _worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            box["result"] = loop.run_until_complete(coro)
        except Exception as e:   # noqa: BLE001
            box["error"] = e
        finally:
            loop.close()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _soup(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


async def _new_browser(pw):
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(user_agent=_UA)
    return browser, ctx


async def _render(page, url):
    """Navega y espera a que el contenido Angular esté hidratado."""
    await page.goto(url, wait_until="networkidle", timeout=_NAV_TIMEOUT)
    # Esperar a que aparezcan cards de producto (o agotar un margen corto).
    try:
        await page.wait_for_selector("a[href*='/productos/']", timeout=8000)
    except Exception:
        pass
    await page.wait_for_timeout(800)
    return await page.content()


async def _first_href(page):
    """href del primer producto visible (para detectar el cambio de página)."""
    try:
        return await page.eval_on_selector(
            "a[href*='/productos/']", "el => el.getAttribute('href')")
    except Exception:
        return None


async def _go_next(page, prev_first):
    """Clickea la flecha 'siguiente' de la paginación (Angular: sólo por click; el
    parámetro ?page=N en la URL NO funciona en navegación directa).

    Devuelve True si avanzó (el primer producto cambió), False si no hay siguiente.
    """
    clicked = await page.evaluate(
        """() => {
            const items = [...document.querySelectorAll('ul.pagination li.page-item')];
            for (const li of items) {
                if (li.querySelector('i.fa-angle-right')) {       // flecha simple 'next'
                    if (li.classList.contains('disabled')) return false;
                    const a = li.querySelector('a'); if (a) { a.click(); return true; }
                }
            }
            return false;
        }""")
    if not clicked:
        return False
    # Esperar a que el primer producto cambie (la grilla se re-renderizó).
    for _ in range(30):
        await page.wait_for_timeout(300)
        cur = await _first_href(page)
        if cur and cur != prev_first:
            await page.wait_for_timeout(400)
            return True
    return False


# ─── Discovery ───────────────────────────────────────────────────────────────
async def _discover_async(progress_cb):
    from playwright.async_api import async_playwright
    if progress_cb:
        progress_cb({"event": "discover", "phase": "scan", "done": 0, "total": 1})
    async with async_playwright() as pw:
        browser, ctx = await _new_browser(pw)
        try:
            page = await ctx.new_page()
            html = await _render(page, f"{BASE}/")
        finally:
            await browser.close()
    soup = _soup(html)

    def _info(a):
        m = re.search(r"/categorias/(\d+)/([^/?#]+)", a.get("href") or "")
        if not m:
            return None
        return m.group(1), a.get_text(strip=True), f"categorias/{m.group(1)}/{m.group(2)}"

    # Departamentos = categorías de id de 1 dígito (1–9). La página de cada
    # departamento pagina y agrupa TODOS sus productos (roll-up de sus hijos), así
    # que con "Todo el departamento" se cubre el catálogo completo. (El mega-menú
    # sólo hidrata las subcategorías al hacer hover → no es confiable en el DOM
    # estático; por eso no se intenta listar subcategorías individuales acá.)
    depts = {}
    for a in soup.find_all("a", href=re.compile(r"/categorias/\d/")):
        info = _info(a)
        if info and len(info[0]) == 1 and info[1]:
            depts.setdefault(info[0], (info[1], info[2]))

    out = []
    for did, (name, ref) in depts.items():
        out.append((name, [("▸ Todo el departamento", ref)]))
    out.sort(key=lambda x: x[0])
    if progress_cb:
        progress_cb({"event": "discover", "phase": "done", "done": 1, "total": 1})
    return out


def discover_sections(progress_cb=None):
    return _run_async(_discover_async(progress_cb))


# ─── Extracción ──────────────────────────────────────────────────────────────
def _money(txt):
    m = re.search(r"\$\s?([\d\.]+)", txt or "")
    if not m:
        return ""
    try:
        return float(m.group(1).replace(".", ""))
    except ValueError:
        return ""


def _extract(card, seccion, subcat):
    url = card.get("href") or ""
    if url and url.startswith("/"):
        url = BASE + url
    sku = ""
    m = re.search(r"/productos/([^/?#]+)", url)
    if m:
        sku = m.group(1)
    name_el = card.select_one("h6.product-title, .product-title")
    name = name_el.get_text(" ", strip=True) if name_el else ""
    brand_el = card.select_one(".brand")
    brand = brand_el.get_text(strip=True) if brand_el else ""
    amounts = sorted({v for v in (_money(t) for t in
                      re.findall(r"\$\s?[\d\.]+", card.get_text(" "))) if v != "" and v > 0})
    if len(amounts) >= 2:
        internet, normal = amounts[0], amounts[-1]
    elif amounts:
        internet = normal = amounts[0]
    else:
        internet = normal = ""
    img_el = card.select_one("img")
    img = ""
    if img_el:
        img = img_el.get("src") or img_el.get("data-src") or ""
        if img and img.startswith("/"):
            img = BASE + img
    return _b.make_row(
        tienda=RETAILER_NAME, seccion=seccion, subcat=subcat,
        marca=brand, sku=sku, descripcion=name,
        precio_normal=normal, precio_internet=internet,
        url=url, img=img,
    )


def _cards(soup):
    """Cards de producto: el `<a>` contenedor con un h6.product-title y href a /productos/."""
    out = []
    seen = set()
    for a in soup.select("a[href*='/productos/']"):
        if not a.select_one("h6.product-title, .product-title"):
            continue
        href = (a.get("href") or "").split("?")[0]
        if href in seen:
            continue
        seen.add(href)
        out.append(a)
    return out


# ─── Scrape ──────────────────────────────────────────────────────────────────
async def _scrape_async(subcats, on_row, progress_cb, limit):
    from playwright.async_api import async_playwright
    rows = []
    total = len(subcats)
    async with async_playwright() as pw:
        browser, ctx = await _new_browser(pw)
        try:
            page = await ctx.new_page()
            for idx, (seccion, subcat, ref) in enumerate(subcats, 1):
                if progress_cb:
                    progress_cb({"event": "subcat_start", "section": seccion,
                                 "subcat": subcat, "idx": idx, "total": total})
                pnum = 1
                seen = 0
                seen_skus = set()
                try:
                    await _render(page, f"{BASE}/{ref}")
                except Exception:
                    if progress_cb:
                        progress_cb({"event": "subcat_done", "section": seccion,
                                     "subcat": subcat, "idx": idx, "total": total, "n_rows": 0})
                    continue
                while pnum <= _MAX_PAGES:
                    prev_first = await _first_href(page)
                    cards = _cards(_soup(await page.content()))
                    if not cards:
                        break
                    added = 0
                    for c in cards:
                        r = _extract(c, seccion, subcat)
                        key = r["SKU"] or r["URL"]
                        if key in seen_skus:
                            continue
                        seen_skus.add(key)
                        rows.append(r); seen += 1; added += 1
                        if on_row:
                            on_row(r)
                        if limit and seen >= limit:
                            break
                    if progress_cb:
                        progress_cb({"event": "subcat_page", "section": seccion,
                                     "subcat": subcat, "page": pnum, "n_rows": len(rows)})
                    if (limit and seen >= limit) or added == 0:
                        break
                    if not await _go_next(page, prev_first):
                        break
                    pnum += 1
                if progress_cb:
                    progress_cb({"event": "subcat_done", "section": seccion, "subcat": subcat,
                                 "idx": idx, "total": total, "n_rows": seen})
        finally:
            await browser.close()
    if progress_cb:
        progress_cb({"event": "complete", "n_rows": len(rows)})
    return rows


def scrape_section(subcats, *, on_row=None, progress_cb=None, limit=None, zone=None):
    """subcats: [(sección, subcategoría, ref), ...]. `zone` se ignora (precio único)."""
    return _run_async(_scrape_async(subcats, on_row, progress_cb, limit))
