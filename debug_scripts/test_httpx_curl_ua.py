import asyncio
import httpx

async def test():
    headers = {
        "User-Agent": "curl/8.21.0",
        "Accept": "*/*",
    }
    url = "https://export.arxiv.org/api/query?search_query=all:speech+diarization&start=0&max_results=3"
    async with httpx.AsyncClient(headers=headers, timeout=10.0) as client:
        r = await client.get(url)
        print(f"Status: {r.status_code}, Length: {len(r.text)}")

asyncio.run(test())
