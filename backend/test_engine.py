import asyncio
import json
import logging
from maestra_sodimac import discover_sections as discover_sections_sodimac
from sodimac_engine import search_skus_mk6, ALL_STORES
from playwright.async_api import async_playwright

async def test():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        
        print("\n--- TEST: Sodimac Discovery (Cache) ---")
        try:
            sections = await discover_sections_sodimac(page)
            print(f"✅ Discovered {len(sections)} sections in Sodimac")
            if sections:
                print(f"Sample: {sections[0][0]} -> {len(sections[0][1])} subcats")
        except Exception as e:
            print("❌ Sodimac discovery failed:", e)
            
        print("\n--- TEST: Sodimac MK6 Batch Search ---")
        try:
            # Test with a mix of known SKUs (guards) and maybe one fake one to check false negatives
            test_skus = ["110038221", "130607328", "999999999999"]
            print(f"Searching SKUs: {test_skus}")
            store = [s for s in ALL_STORES if s["id"] == "E510"][0]  # Florida
            
            def cb(event_dict):
                print(f"  [Callback] {event_dict['event']}")
                
            results = await search_skus_mk6(test_skus, [store], progress_cb=cb)
            
            print(f"✅ Search complete. Results count: {len(results)}")
            for r in results:
                print(f"   - SKU {r.get('sku_input')}: {r.get('descripcion', 'No desc')} (Stock: {r.get('Stock', '?')})")
                
            # Verify false positive logic
            found_skus = {r.get('sku_input') for r in results}
            for sku in test_skus:
                if sku == "999999999999" and sku in found_skus:
                    print(f"❌ False positive detected for fake SKU {sku}!")
                elif sku != "999999999999" and sku not in found_skus:
                    print(f"❌ False negative? Known SKU {sku} not found.")
                    
        except Exception as e:
            print("❌ Sodimac MK6 search failed:", e)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test())
