# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Ferni — hub con selector de herramienta (se lanza desde un solo Colab).

`boot("ferni")` muestra un selector al inicio para elegir el motor:
  - "sku"     → launchers/ferni_sku.py     (Buscador de Puertas por SKU)
  - "maestra" → launchers/ferni_maestra.py (Maestra Sección Sodimac por categoría)

Ambos comparten la lógica de variantes (medidas exactas para puertas "y más").
"""


def run():
    import nest_asyncio
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output

    nest_asyncio.apply()
    clear_output(wait=True)

    display(HTML("""
    <div style='background:linear-gradient(120deg,#2E86C1,#5DADE2);color:white;
    padding:1.2rem 1.5rem;border-radius:12px;margin-bottom:1rem;font-family:sans-serif;'>
      <h2 style='margin:0;color:white;'>🚪 Ferni — Sodimac (puertas y más)</h2>
      <p style='margin:.3rem 0 0;color:rgba(255,255,255,.92);font-size:.95rem;'>
        Elegí qué herramienta usar. Ambas resuelven el selector de medidas
        (medida + precio exacto por variante).
      </p>
    </div>
    """))

    selector = widgets.RadioButtons(
        options=[
            ("🔍  Buscador por SKU — subís un Excel con SKUs de puertas", "sku"),
            ("🗂️  Maestra Sección — recorre categorías completas de Sodimac", "maestra"),
        ],
        value="sku",
        description="Herramienta:",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="auto"),
    )
    desc = widgets.HTML(
        "<div style='background:#eaf4fb;border:1px solid #aed6f1;padding:.6rem;"
        "border-radius:6px;margin:.4rem 0;font-size:.9em;'>"
        "<b>🔍 Buscador por SKU</b>: ya sabés qué puertas querés (subís sus SKU).<br>"
        "<b>🗂️ Maestra Sección</b>: querés barrer una sección entera (ej. Puertas) "
        "y traer todo con sus medidas y precios.</div>")
    cont_btn = widgets.Button(description="Continuar →", button_style="success",
                              layout=widgets.Layout(width="200px"))

    def _go(_b):
        choice = selector.value
        clear_output(wait=True)
        if choice == "maestra":
            from launchers import ferni_maestra
            ferni_maestra.run()
        else:
            from launchers import ferni_sku
            ferni_sku.run()

    cont_btn.on_click(_go)
    display(widgets.VBox([selector, desc, cont_btn]))
