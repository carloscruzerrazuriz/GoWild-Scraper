# Nota sobre protección de IP (histórico)

> **Estado: plan descartado.** Este archivo documentaba un plan de protección de
> propiedad intelectual basado en **dos repositorios** (uno privado con el código fuente
> y uno público con solo bytecode `.pyc`, sincronizados vía GitHub Actions y consumidos
> en Colab con sparse-checkout). Ese plan fue **evaluado y NO adoptado.**

## Qué se hace en su lugar

La protección de IP del proyecto es una **capa legal/social**, no técnica:

1. **`LICENSE`** "All Rights Reserved" en la raíz del repo (prohíbe redistribución,
   modificación, reverse engineering y uso comercial; GitHub etiqueta el repo como *Proprietary*).
2. **Header de copyright** en cada archivo `.py` (viaja con el archivo si se copia suelto).
3. **Watermark** "Carlos Cruz E." al pie de la UI de cada herramienta.

Se descartó la ofuscación técnica (PyArmor: trial de 32 días / licencia paga) y el esquema
two-repo por su costo de mantenimiento y porque rompería la distribución actual (notebooks
delgados que se auto-actualizan con `git pull` desde este repo público). Si en el futuro la
amenaza cambia (extracción técnica activa o monetización real), reconsiderar repo privado + PAT
o migración a un servidor con API.

---

*El detalle completo de la arquitectura, herramientas y decisiones del proyecto vive en el
documento de contexto general del mantenedor (fuera de este repo).*

*Copyright (c) 2026 Carlos Cruz Errazuriz · All rights reserved · Proprietary.*
