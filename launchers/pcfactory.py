# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""PCFactory — hub con selector de herramienta (un solo Colab).

`boot("pcfactory")` muestra un selector para elegir el motor:
  - "seccion"         → launchers/pcfactory_seccion.py          (Section catalog)
  - "detalle"         → launchers/pcfactory_detalle.py           (Full detail by SKU)
  - "seccion_detalle" → launchers/pcfactory_seccion_detalle.py   (Section → Full detail)

UI EN INGLÉS (requerimiento del cliente). Todas extraen de la API pública de
pcfactory.cl (JSON, sin DOM/Playwright).
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
        Choose a tool. All of them extract via API (fast, no zone selector —
        PCFactory has nationwide pricing).
      </p>
    </div>
    """))

    selector = widgets.RadioButtons(
        options=[
            ("🗂️  Section catalog — browse full categories and list their products", "seccion"),
            ("🔍  Full detail by SKU — upload a SKU list and pull EVERYTHING per product", "detalle"),
            ("🗂️🔍  Section → Full detail — pick a section, get the full detail of every product", "seccion_detalle"),
        ],
        value="seccion",
        description="Tool:",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="auto"),
    )
    desc = widgets.HTML(
        "<div style='background:#eaf3fc;border:1px solid #aacdf0;padding:.6rem;"
        "border-radius:6px;margin:.4rem 0;font-size:.9em;'>"
        "<b>🗂️ Section catalog</b>: sweep a whole section/category and list its products with prices.<br>"
        "<b>🔍 Full detail by SKU</b>: you already know which products you want (upload their SKU) and "
        "need <b>everything</b>: prices, stock by store, specifications, images and video.<br>"
        "<b>🗂️🔍 Section → Full detail</b>: pick a section and get the full detail of every product in it "
        "(counts the products and asks for confirmation first).</div>")
    cont_btn = widgets.Button(description="Continue →", button_style="success",
                              layout=widgets.Layout(width="200px"))

    def _go(_b):
        choice = selector.value
        clear_output(wait=True)
        if choice == "detalle":
            from launchers import pcfactory_detalle
            pcfactory_detalle.run()
        elif choice == "seccion_detalle":
            from launchers import pcfactory_seccion_detalle
            pcfactory_seccion_detalle.run()
        else:
            from launchers import pcfactory_seccion
            pcfactory_seccion.run()

    cont_btn.on_click(_go)
    display(widgets.VBox([selector, desc, cont_btn]))
