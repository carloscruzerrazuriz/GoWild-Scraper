from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import asyncio
import json
import uuid
import pandas as pd
import io
import contextlib

from db import init_db, get_db, ScrapedProduct, SessionLocal
from sodimac_engine import search_skus_mk6, ALL_STORES as SODIMAC_STORES

MAX_CONCURRENT_SCRAPERS = 3
job_queue = asyncio.Queue()
active_jobs = {}
queue_positions = [] # List of job_ids waiting

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start workers
    workers = [asyncio.create_task(worker_process()) for _ in range(MAX_CONCURRENT_SCRAPERS)]
    yield
    # Shutdown: cancel workers
    for w in workers:
        w.cancel()

app = FastAPI(title="Go Wild Scraper API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

async def worker_process():
    while True:
        job = await job_queue.get()
        job_id = job["job_id"]
        
        # Remove from queue_positions
        if job_id in queue_positions:
            queue_positions.remove(job_id)
            
        # Update remaining queue positions
        await _broadcast_queue_updates()
        
        active_jobs[job_id]["status"] = "running"
        await manager.broadcast({"event": "job_started", "job_id": job_id, "type": job["type"]})
        
        # Database session for background task
        db = SessionLocal()
        try:
            await _run_scraper_task(job_id, job["type"], job.get("df"), job.get("url"), db)
        finally:
            db.close()
            job_queue.task_done()
            active_jobs[job_id]["status"] = "finished"

async def _broadcast_queue_updates():
    for i, j_id in enumerate(queue_positions):
        await manager.broadcast({
            "event": "queue_update",
            "job_id": j_id,
            "position": i + 1
        })

async def _run_scraper_task(job_id: str, scraper_type: str, df: pd.DataFrame, url: str, db: Session):
    try:
        def _cb(event_dict):
            event_dict["job_id"] = job_id
            asyncio.create_task(manager.broadcast(event_dict))
            
        results = []
        if scraper_type == "sodimac":
            skus = df["sku"].astype(str).tolist()
            from sodimac_engine import search_skus_mk6, ALL_STORES as SOD_STORES
            results = await search_skus_mk6(skus, SOD_STORES, progress_cb=_cb)
            
        elif scraper_type == "falabella":
            skus_meta = [{"sku": str(row["sku"])} for _, row in df.iterrows()]
            from falabella_engine import search_skus, ALL_STORES as FAL_STORES
            results = await search_skus(skus_meta, zones=FAL_STORES, progress_cb=_cb)
            
        elif scraper_type == "construmart":
            skus_meta = [{"sku": str(row["sku"])} for _, row in df.iterrows()]
            from construmart_engine import search_skus, ALL_STORES as CON_STORES
            results = await search_skus(skus_meta, stores=CON_STORES, progress_cb=_cb)
            
        elif scraper_type in ["maestra_seccion", "precios_mayoristas"]:
            from playwright.async_api import async_playwright
            from maestra_sodimac import scrape_subcat
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                # Mock a simple progress callback compatible with scrape_subcat
                def _prog_cb(count, sku, msg):
                    _cb({"event": "progress", "message": f"{count}: {sku} - {msg}"})
                    
                # We extract the category from the url. Example: url has subcat name.
                cat_name = url.split('/')[-1] if '/' in url else 'Categoria'
                
                res = await scrape_subcat(page, "Sección", cat_name, url, progress=_prog_cb, page_task=None, max_workers=1)
                await browser.close()
                
                results = res
                
        else:
            raise ValueError(f"Scraper '{scraper_type}' no implementado o requiere configuración especial.")
        
        for r in results:
            prod = ScrapedProduct(
                job_id=job_id,
                scraper_type=scraper_type,
                sku=r.get("sku_input") or r.get("sku"),
                store_id=r.get("store_id") or r.get("zone_id"),
                store_name=r.get("store_found") or r.get("zone_name"),
                brand=r.get("marca") or r.get("brand"),
                description=r.get("descripcion") or r.get("desc"),
                price_normal=r.get("precio_normal") or r.get("price_normal"),
                price_internet=r.get("precio_internet") or r.get("price_internet"),
                price_cmr=r.get("precio_cmr") or r.get("price_card"),
                price_wholesale=r.get("precio_mayorista"),
                discount_pct=r.get("pct_descuento") or r.get("discount"),
                url=r.get("url")
            )
            db.add(prod)
        db.commit()
        
        await manager.broadcast({"event": "job_finished", "job_id": job_id, "results_count": len(results)})
    except Exception as e:
        import traceback
        traceback.print_exc()
        await manager.broadcast({"event": "job_error", "job_id": job_id, "error": str(e)})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.post("/api/scrape")
async def start_scraping(
    scraper_type: str = Form(...),
    file: UploadFile = File(None),
    url: str = Form(None)
):
    df = None
    if file:
        contents = await file.read()
        if file.filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            df = pd.read_excel(io.BytesIO(contents))
            
        cols = [c.lower().strip() for c in df.columns]
        df.columns = cols
        
        sku_col = None
        for c in cols:
            if "sku" in c or "cód" in c or "cod" in c:
                sku_col = c
                break
                
        if not sku_col:
            return {"error": "No se detectó columna SKU en el archivo."}
            
        df.rename(columns={sku_col: "sku"}, inplace=True)
    elif not url:
        return {"error": "Se requiere un archivo o una URL de categoría."}
    
    job_id = str(uuid.uuid4())
    active_jobs[job_id] = {"status": "queued", "type": scraper_type}
    
    queue_positions.append(job_id)
    position = len(queue_positions)
    
    await job_queue.put({
        "job_id": job_id,
        "type": scraper_type,
        "df": df,
        "url": url
    })
    
    return {
        "message": "Job queued", 
        "job_id": job_id, 
        "status": "queued",
        "position": position
    }

@app.get("/api/history")
async def get_history(sku: str = None, db: Session = Depends(get_db)):
    query = db.query(ScrapedProduct)
    if sku:
        query = query.filter(ScrapedProduct.sku == sku)
    
    results = query.order_by(ScrapedProduct.scraped_at.desc()).limit(100).all()
    return results

@app.get("/api/check_updates")
async def check_updates():
    import urllib.request
    import json
    import os
    
    # URL de GitHub Raw donde vivirá el version.json maestro
    REMOTE_URL = "https://raw.githubusercontent.com/carloscruzerrazuriz/GoWild-Scraper/main/backend/version.json"
    
    try:
        local_path = os.path.join(os.path.dirname(__file__), "version.json")
        with open(local_path, "r") as f:
            local_version = json.load(f).get("version", "1.0.0")
            
        # Petición real al GitHub
        req = urllib.request.Request(REMOTE_URL)
        with urllib.request.urlopen(req) as response:
            remote_data = json.loads(response.read().decode())
            remote_version = remote_data.get("version")
        
        return {
            "update_available": local_version != remote_version,
            "local_version": local_version,
            "remote_version": remote_version
        }
    except Exception as e:
        return {"update_available": False, "error": str(e)}

@app.post("/api/apply_update")
async def apply_update():
    import subprocess
    import os
    try:
        # Ejecutar git pull
        subprocess.check_call(["git", "pull", "origin", "main"], cwd=os.path.dirname(__file__))
        
        # Iniciar una tarea en segundo plano que matará el servidor para que se reinicie
        async def delayed_restart():
            await asyncio.sleep(2)
            os._exit(0)
            
        asyncio.create_task(delayed_restart())
        return {"status": "ok", "message": "Actualización descargada. Reiniciando el sistema..."}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.get("/api/download/{job_id}")
async def download_results(job_id: str, db: Session = Depends(get_db)):
    from fastapi.responses import StreamingResponse
    import io
    
    query = db.query(ScrapedProduct).filter(ScrapedProduct.job_id == job_id).all()
    if not query:
        return {"error": "No se encontraron resultados para ese trabajo."}
        
    data = []
    for r in query:
        data.append({
            "SKU": r.sku,
            "Tienda": r.store_name,
            "Marca": r.brand,
            "Descripcion": r.description,
            "Precio Normal": r.price_normal,
            "Precio Internet": r.price_internet,
            "Precio CMR": r.price_cmr,
            "Precio Mayorista": r.price_wholesale,
            "Descuento": r.discount_pct,
            "URL": r.url
        })
        
    df = pd.DataFrame(data)
    stream = io.BytesIO()
    with pd.ExcelWriter(stream, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
        
    stream.seek(0)
    headers = {
        'Content-Disposition': f'attachment; filename="Resultados_{job_id[:8]}.xlsx"'
    }
    return StreamingResponse(stream, headers=headers, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
