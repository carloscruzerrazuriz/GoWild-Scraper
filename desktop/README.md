# GoWild Desktop

App de escritorio que corre los scrapers **en el PC del usuario** en vez de Colab.

## Por qué

| | Colab | Desktop |
|---|---|---|
| IP | Datacenter de Google (Cloudflare hostil) | Residencial |
| Sesión | Se corta (de ahí los checkpoints) | Sin límite |
| Paralelismo | Conservador | Agresivo |
| Archivos | Descarga manual | Directo a `Documentos/GoWild` |

## Herramientas

- **MK7** — buscador por SKU
- **Sección** — catálogo por categoría
- **Fast** — precios por mayor (browserless, el más rápido)
- **Ferni · Puertas por SKU** — 1 fila por medida
- **Ferni · Sección** — puertas y más, por categoría

## Cómo se actualiza (igual que los Colab)

El ejecutable es un **shell delgado**: en cada arranque descarga la última
versión del código desde GitHub (`main`) y la ejecuta desde ahí. Motores,
orquestadores y UI vienen del repo.

**`git push` = todos actualizados al siguiente doble clic.** Sólo hay que
reconstruir el .exe si cambian las dependencias (equivalente al `launcher_schema`).

## Desarrollo (local, sin bajar de GitHub)

```bash
python3 desktop/dev.py 8799 --open
```

## Estructura

```
desktop/
├── shell.py          # entrypoint del .exe: auto-update + server + navegador
├── dev.py            # arranque de desarrollo (usa el repo local)
├── server.py         # HTTP local + SSE de progreso (sólo stdlib)
├── orchestrators.py  # puente a los engines (reusa engines/ tal cual)
└── ui/               # frontend (index.html, style.css, app.js)
```
