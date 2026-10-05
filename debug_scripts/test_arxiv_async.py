import asyncio
import httpx

async def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Encoding": "gzip, deflate",
        "Accept": "*/*",
    }
    async with httpx.AsyncClient(http1=True, http2=False, headers=headers, timeout=30.0, follow_redirects=True) as client:
        r = await client.get("https://export.arxiv.org/api/query?search_query=all:On-device+real-time+speech+diarization&start=0&max_results=5")
        print("Status:", r.status_code, "Length:", len(r.text))

asyncio.run(main())
