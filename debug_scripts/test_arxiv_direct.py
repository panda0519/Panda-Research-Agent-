import asyncio
import httpx

async def test():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Encoding": "gzip, deflate",
        "Accept": "*/*",
    }
    url = "https://export.arxiv.org/api/query?search_query=all:speech+diarization&start=0&max_results=5"
    async with httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True) as client:
        r = await client.get(url)
        print(f"Status: {r.status_code}, length: {len(r.text)}")
        if r.status_code != 200:
            print(f"Headers: {dict(r.headers)}")
            print(f"Content: {r.text[:300]}")

if __name__ == "__main__":
    asyncio.run(test())
