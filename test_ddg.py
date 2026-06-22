from ddgs import AsyncDDGS
import asyncio
import json

async def main():
    try:
        async with AsyncDDGS() as ddgs:
            results = await ddgs.atext("Apple", max_results=3)
            print("RESULTS", json.dumps(results, indent=2))
    except Exception as e:
        print("ERROR", e)

asyncio.run(main())
