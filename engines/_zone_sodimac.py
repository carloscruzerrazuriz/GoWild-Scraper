# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
# === Sistema ÚNICO de seteo de zona para Sodimac (compartido) ===

"""Módulo único de zona para todas las herramientas Sodimac.

Antes cada engine (MK7 `sodimac_engine`, Sección `maestra_sodimac`, Ferni
`ferni_sodimac`) tenía su PROPIA copia de `set_zone`/`_type_autocomplete`/
`warmup_session`, y habían DIVERGIDO:
  - MK7 verificaba que la zona quedó fijada (label "Entrega en {comuna}") →
    reportaba FAIL honesto, pero podía dar falso-negativo si Sodimac cambiaba
    la clase CSS del label.
  - Sección NO verificaba: hacía click en Guardar y devolvía True a ciegas →
    podía scrapear con la zona equivocada (la default) sin avisar. Además NO
    hacía warmup → en Colab la IP de Google recibe el challenge de Cloudflare
    y set_zone falla en cadena (lección v2.11.3).

Este módulo unifica todo en UNA implementación robusta que:
  1. **Warmup integrado** (anti-Cloudflare) al inicio de cada set_zone →
     ya no depende de que el caller lo haga.
  2. **Autocomplete con backspace-retry** (fix "Calama": Sodimac esconde la
     opción correcta si tipeás el nombre completo) y SIN caer a la 1ª
     sugerencia (evita elegir la comuna equivocada).
  3. **Verificación robusta doble**: (a) el label muestra la comuna pedida
     (acento/NBSP-insensible), o (b) fallback por COOKIE — Sodimac fija
     `IS_ZONE_SELECTED=true` + `priceGroupId` + `zoneData` al confirmar, señal
     inmune a cambios de HTML/CSS. Si ninguna confirma → FAIL honesto (el
     orquestador reintenta con otra zona/contexto en vez de scrapear mal).

Contrato público (idéntico al que ya usaban los engines):
    warmup_session(page)                                  -> None
    set_zone(page, region, comuna, *, warmup=True)        -> bool
    set_zone_with_retry(page, region, comuna, retries=2)  -> bool
"""

import urllib.parse

BASE_URL = "https://www.sodimac.cl/sodimac-cl"


# ─────────────────────────────────────────  Warm-up  ───────────────────────

async def warmup_session(page) -> None:
    """Visita la home y scrollea para que Sodimac fije los tokens de sesión.

    Sin esto, /buscar?Ntt=... desde un Chromium frío devuelve la home en vez
    de la grilla (heurística anti-bot), y en Colab set_zone falla por el
    challenge de Cloudflare que este warmup limpia (lección v2.11.3).
    """
    await page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3500)
    for _ in range(3):
        await page.evaluate("window.scrollBy(0, 350)")
        await page.wait_for_timeout(700)


# ─────────────────────────────────────  Autocomplete  ──────────────────────

async def _type_autocomplete(page, placeholder: str, value: str) -> bool:
    """Tipea `value` en el input `placeholder` y elige la sugerencia correcta.

    Estrategia (la más robusta, ex-MK7): match exacto → endsWith → contains.
    Si no aparece, va borrando caracteres del final (las sugerencias se
    relistan con menos filtro) hasta encontrar el target real. NO cae a la
    primera sugerencia (eso elegía la comuna equivocada en Sección).
    """
    sel = f'input[placeholder="{placeholder}"]'
    for _ in range(20):
        st = await page.evaluate(
            """(s) => { const i = document.querySelector(s);
                return i ? {present: true, disabled: i.disabled, hidden: i.offsetHeight === 0} : {present: false}; }""",
            sel,
        )
        if st.get("present") and not st.get("disabled") and not st.get("hidden"):
            break
        await page.wait_for_timeout(500)
    else:
        return False
    inp = page.locator(sel).first
    # Remover banners de cookies/consentimiento que interceptan el click en headless (Colab).
    await page.evaluate("""() => {
        document.querySelectorAll(
            '[id*="onetrust"], [class*="onetrust"], '
            + '[id^="cookie"], [class^="cookie"], '
            + '#CybotCookiebotDialog, [class*="CookieConsent"]'
        ).forEach(e => { try { e.remove(); } catch (_) {} });
    }""")
    try:
        await inp.click(timeout=5000)
    except Exception:
        try:
            await inp.click(force=True, timeout=5000)
        except Exception:
            await page.evaluate("(s) => { const el = document.querySelector(s); if (el) el.focus(); }", sel)
    try:
        await inp.fill("", timeout=5000)
    except Exception:
        await page.evaluate("(s) => { const el = document.querySelector(s); if (el) el.value = ''; }", sel)
    await page.keyboard.type(value, delay=60)

    PICK_JS = """(target) => {
        const lis = [...document.querySelectorAll('li[class*="Autocomplete-module_suggestion"]')]
            .filter(e => e.offsetHeight > 0 && (e.innerText || '').trim());
        const norm = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
        const t = norm(target);
        const exact = lis.find(e => norm(e.innerText.trim()) === t);
        const endsWith = lis.find(e => {
            const x = norm(e.innerText.trim());
            return x === t || x.endsWith(" - " + t);
        });
        const contains = lis.find(e => norm(e.innerText.trim()).includes(t));
        const pick = exact || endsWith || contains;
        if (!pick) return null;
        const fire = (type) => pick.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
        fire('mousedown'); fire('mouseup'); fire('click');
        return pick.innerText.trim();
    }"""

    picked = None
    chars_left = len(value)
    while chars_left >= 3:
        for _ in range(12):
            await page.wait_for_timeout(250)
            has = await page.evaluate(
                """() => [...document.querySelectorAll('li[class*="Autocomplete-module_suggestion"]')]
                        .some(e => e.offsetHeight > 0 && (e.innerText||'').trim())"""
            )
            if has:
                break
        picked = await page.evaluate(PICK_JS, value)
        if picked:
            break
        await page.keyboard.press("Backspace")
        chars_left -= 1
        await page.wait_for_timeout(400)

    if picked:
        await page.wait_for_timeout(700)
        return True
    return False


# ─────────────────────────────────────  Verificación  ──────────────────────

# Lee el estado de zona desde el DOM (label) — tolerante a varios selectores.
_LABEL_JS = r"""() => {
    const small = e => e.offsetHeight > 0 && e.children.length <= 2;
    let label = "";
    const p = document.querySelector('p[class*="Zone-module"]');
    if (p && p.offsetHeight > 0) label = p.innerText || "";
    if (!label) {
        const el = [...document.querySelectorAll('*')].find(e =>
            small(e) && /^(entrega en|despacha|env[ií]a a|retira)/i.test((e.innerText||'').trim()));
        if (el) label = el.innerText || "";
    }
    const placeholderPresent = [...document.querySelectorAll('*')].some(e =>
        e.offsetHeight > 0 && (e.innerText||'').trim() === 'Ingresa tu ubicación');
    return {label: (label||'').trim(), placeholderPresent};
}"""


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace(" ", " ").lower().strip()


async def _zone_cookies(page) -> dict:
    try:
        cks = await page.context.cookies()
    except Exception:
        return {}
    return {c["name"]: c.get("value", "") for c in cks}


async def _verify_zone(page, comuna: str, before: dict) -> bool:
    """True si la zona `comuna` quedó REALMENTE fijada. Poll ~7s.

    Doble señal (basta una): (a) el label muestra la comuna pedida; (b) el
    modal se cerró (placeholder ausente) Y una cookie de zona cambió en ESTA
    llamada (priceGroupId/zoneData distinto al snapshot `before`) — robusto a
    cambios de CSS y correcto en contexto reutilizado (Sección hace varias
    zonas en la misma página).
    """
    target = _norm(comuna)
    for _ in range(14):  # 14 * 500ms = 7s
        await page.wait_for_timeout(500)
        try:
            st = await page.evaluate(_LABEL_JS)
        except Exception:
            st = {"label": "", "placeholderPresent": False}
        ck = await _zone_cookies(page)
        committed = ck.get("IS_ZONE_SELECTED") == "true"
        label = _norm(st.get("label", ""))
        geo = _norm(urllib.parse.unquote(ck.get("GEOFINDER_INFO", "")))

        # (a) confirmación por comuna (la más fuerte / correcta por-zona)
        if committed and (target in label or target in geo):
            return True

        # (b) fallback anti-CSS-change: modal confirmó algo en ESTA llamada
        if committed and not st.get("placeholderPresent"):
            changed = (
                ck.get("priceGroupId") and ck.get("priceGroupId") != before.get("priceGroupId")
            ) or (
                ck.get("zoneData") and ck.get("zoneData") != before.get("zoneData")
            )
            # sólo si el label NO muestra OTRA comuna distinta (evita aceptar zona vieja)
            if changed and not label:
                return True
    return False


# ─────────────────────────────────────────  set_zone  ──────────────────────

async def set_zone(page, region: str, comuna: str, *, warmup: bool = True) -> bool:
    """Fija la zona (region, comuna) en Sodimac y VERIFICA que quedó fijada.

    `warmup=True` (default) hace el warmup anti-Cloudflare antes de abrir el
    modal → toda herramienta queda protegida sin depender del caller. Pasar
    `warmup=False` si el caller ya llamó `warmup_session` (evita doble carga).
    """
    if warmup:
        await warmup_session(page)
    else:
        await page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)

    # Descartar banners de cookies/consentimiento que tapan el botón de ubicación.
    await page.evaluate("""() => {
        const btns = [...document.querySelectorAll('button, a')];
        const acc = btns.find(b => /acept|entend|de acuerdo|cerrar/i.test((b.innerText||'').trim()) && b.offsetHeight > 0);
        if (acc) { try { acc.click(); } catch(e){} }
        document.querySelectorAll('#onetrust-banner-sdk, [class*="cookie"], [class*="Modal"], [class*="overlay"], [data-testid="overlay"]')
            .forEach(o => { try { o.remove(); } catch(e){} });
    }""")

    # Abrir el modal de ubicación. Poll ~10s (VM lenta / latencia). Selector
    # nuevo 2026 (p Zone-module) + fallback por texto con 4 variantes.
    opened = False
    for _ in range(20):
        opened = await page.evaluate("""() => {
            const p = document.querySelector('p[class*="Zone-module_zone-lable"]');
            if (p && p.offsetHeight > 0) { p.click(); return true; }
            const el = [...document.querySelectorAll('*')].find(e => {
                const t = (e.innerText || '').trim();
                return e.offsetHeight > 0 && (
                    t === 'Ingresa tu ubicación'
                    || /^Entrega en/.test(t)
                    || /^Despacha en/.test(t)
                    || /^Envía a/.test(t)
                );
            });
            if (el) { el.click(); return true; } return false;
        }""")
        if opened:
            break
        await page.wait_for_timeout(500)
    if not opened:
        return False

    # Snapshot de cookies de zona ANTES de confirmar (para el fallback anti-CSS).
    before = await _zone_cookies(page)

    await page.wait_for_timeout(1500)
    if not await _type_autocomplete(page, "Ingresa una Región", region):
        return False
    if not await _type_autocomplete(page, "Ingresa una Comuna", comuna):
        return False
    clicked = await page.evaluate("""() => {
        const btn = [...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Guardar' && !b.disabled);
        if (btn) { btn.click(); return true; } return false;
    }""")
    if not clicked:
        return False

    return await _verify_zone(page, comuna, before)


async def set_zone_with_retry(page, region: str, comuna: str, retries: int = 2) -> bool:
    """set_zone con N reintentos. Devuelve True si alguno tuvo éxito."""
    for attempt in range(retries + 1):
        try:
            ok = await set_zone(page, region, comuna)
        except Exception:
            ok = False
        if ok:
            return True
        if attempt < retries:
            await page.wait_for_timeout(1500 * (attempt + 1))
    return False
