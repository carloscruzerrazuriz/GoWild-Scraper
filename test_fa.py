import asyncio
import json
from engines.falabella_engine import search_skus, ALL_STORES

async def main():
    skus = ["110284026", "110314082", "5726197"] # adding some random sku
    stores = [s for s in ALL_STORES if s["id"] == "E502"]
    
    def on_progress(p):
        print("PROGRESS:", p)
        
    print(f"Testing MK7 Falabella with SKUs: {skus} for store E502")
    res = await search_skus(skus, stores, progress_cb=on_progress)
    print("RESULTS:")
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
