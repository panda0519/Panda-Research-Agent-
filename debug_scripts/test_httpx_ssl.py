import asyncio
import ssl
import httpx

async def test_httpx_ssl():
    ctx = ssl.create_default_context()
    ctx.set_ciphers('DEFAULT@SECLEVEL=1')
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }
    url = "https://export.arxiv.org/api/query?search_query=all:speech+diarization&start=0&max_results=3"
    
    async with httpx.AsyncClient(verify=ctx, headers=headers, timeout=15.0) as client:
        r = await client.get(url)
        print("httpx with custom SSL context -> Status:", r.status_code, "Len:", len(r.text))

asyncio.run(test_httpx_ssl())
