# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""PCFactory — hub con selector de herramienta (un solo Colab).

`boot("pcfactory")` muestra un selector al inicio para elegir el motor:
  - "seccion" → launchers/pcfactory_seccion.py  (Maestra Sección por categoría)
  - "detalle" → launchers/pcfactory_detalle.py   (Ficha Completa por SKU)

Ambas extraen de la API pública de pcfactory.cl (JSON, sin DOM/Playwright).
"""


def run():
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output

    clear_output(wait=True)

    display(HTML("""
    <div style='background:linear-gradient(120deg,#1f5fbf,#3aa0e8);color:white;
    padding:1.2rem 1.5rem;border-radius:12px;margin-bottom:1rem;font-family:sans-serif;'>
      <h2 style='margin:0;color:white;'>🖥️ PCFactory</h2>
      <p style='margin:.3rem 0 0;color:rgba(255,255,255,.92);font-size:.95rem;'>
        Elegí qué herramienta usar. Ambas extraen por API (rápido, sin selector de
        zona — PCFactory tiene precio nacional).
      </p>
    </div>
    """))

    selector = widgets.RadioButtons(
        options=[
            ("🗂️  Maestra Sección — recorre categorías completas y arma el catálogo", "seccion"),
            ("🔍  Ficha Completa por SKU — subís una lista de SKU y extrae TODO de cada uno", "detalle"),
        ],
        value="seccion",
        description="Herramienta:",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="auto"),
    )
    desc = widgets.HTML(
        "<div style='background:#eaf3fc;border:1px solid #aacdf0;padding:.6rem;"
        "border-radius:6px;margin:.4rem 0;font-size:.9em;'>"
        "<b>🗂️ Maestra Sección</b>: querés barrer una sección/categoría entera y "
        "traer todos sus productos con precios.<br>"
        "<b>🔍 Ficha Completa por SKU</b>: ya sabés qué productos querés (subís sus "
        "SKU) y necesitás <b>todo</b>: precios, stock por tienda, especificaciones, "
        "imágenes y video de cada uno.</div>")
    cont_btn = widgets.Button(description="Continuar →", button_style="success",
                              layout=widgets.Layout(width="200px"))

    def _go(_b):
        choice = selector.value
        clear_output(wait=True)
        if choice == "detalle":
            from launchers import pcfactory_detalle
            pcfactory_detalle.run()
        else:
            from launchers import pcfactory_seccion
            pcfactory_seccion.run()

    cont_btn.on_click(_go)
    display(widgets.VBox([selector, desc, cont_btn]))
