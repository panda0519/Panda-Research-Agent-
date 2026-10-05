import asyncio
import httpx

headers_variants = [
    {"name": "standard browser", "headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Accept": "*/*"}},
    {"name": "no accept header", "headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}},
    {"name": "python-requests style", "headers": {"User-Agent": "python-requests/2.31.0", "Accept-Encoding": "gzip, deflate", "Accept": "*/*", "Connection": "keep-alive"}},
    {"name": "curl style", "headers": {"User-Agent": "curl/7.68.0", "Accept": "*/*"}},
    {"name": "arxiv recommended", "headers": {"User-Agent": "MyResearchAgent/1.0 (mailto:test@example.com)"}},
    {"name": "explicit xml", "headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/atom+xml, application/xml, text/xml, */*"}},
]

async def run_tests():
    url = "https://export.arxiv.org/api/query?search_query=all:speech+diarization&start=0&max_results=3"
    for item in headers_variants:
        try:
            async with httpx.AsyncClient(headers=item["headers"], timeout=10.0) as client:
                r = await client.get(url)
                print(f"[{item['name']}] -> Status: {r.status_code}, Length: {len(r.text)}")
        except Exception as e:
            print(f"[{item['name']}] -> Exception: {e}")
        await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(run_tests())



