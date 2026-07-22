import asyncio
import json
from engines.sodimac_engine import search_skus_mk6, ALL_STORES

async def main():
    skus = ["110284026", "110314082"]
    stores = [s for s in ALL_STORES if s["id"] == "E522"]
    
    def on_progress(p):
        print("PROGRESS:", p)
        
    print(f"Testing MK7 Sodimac with SKUs: {skus} for store E522")
    res = await search_skus_mk6(skus, stores, progress_cb=on_progress, headless=True)
    print("RESULTS:")
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
