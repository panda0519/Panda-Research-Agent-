import asyncio
import urllib.parse
import httpx
import urllib.request

query = "transformer attention mechanism"
encoded_q = urllib.parse.quote_plus(query)

url_https = f"https://export.arxiv.org/api/query?search_query=all:{encoded_q}&start=0&max_results=3"
url_http = f"http://export.arxiv.org/api/query?search_query=all:{encoded_q}&start=0&max_results=3"

print("--- 1. urllib GET https ---")
try:
    req = urllib.request.Request(url_https, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        print("urllib https:", resp.status, len(resp.read()))
except Exception as e:
    print("urllib https error:", e)

print("--- 2. urllib GET http ---")
try:
    req = urllib.request.Request(url_http, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        print("urllib http:", resp.status, len(resp.read()))
except Exception as e:
    print("urllib http error:", e)

async def test_httpx():
    print("--- 3. httpx default https ---")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url_https)
            print("httpx https default status:", resp.status_code)
    except Exception as e:
        print("httpx https default error:", e)

    print("--- 4. httpx with custom UA and Accept: */* https ---")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }
    try:
        async with httpx.AsyncClient(headers=headers, timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url_https)
            print("httpx https Chrome UA status:", resp.status_code, "len:", len(resp.text))
    except Exception as e:
        print("httpx https Chrome UA error:", e)

    print("--- 5. httpx with http url ---")
    try:
        async with httpx.AsyncClient(headers=headers, timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url_http)
            print("httpx http Chrome UA status:", resp.status_code, "len:", len(resp.text))
    except Exception as e:
        print("httpx http Chrome UA error:", e)

    print("--- 6. httpx with default client headers inspected ---")
    async with httpx.AsyncClient(headers=headers) as client:
        req = client.build_request("GET", url_https)
        print("Headers sent by httpx:", dict(req.headers))

asyncio.run(test_httpx())
