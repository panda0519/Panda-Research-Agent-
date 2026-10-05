import urllib.request
import httpx
import requests

urls = [
    "http://export.arxiv.org/api/query?search_query=all:speech+diarization&start=0&max_results=3",
    "https://export.arxiv.org/api/query?search_query=all:speech+diarization&start=0&max_results=3",
    "http://api.arxiv.org/query?search_query=all:speech+diarization&start=0&max_results=3",
    "https://api.arxiv.org/query?search_query=all:speech+diarization&start=0&max_results=3",
]

print("--- URLLIB ---")
for u in urls:
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"urllib {u} -> Status: {resp.status}, Len: {len(resp.read())}")
    except Exception as e:
        print(f"urllib {u} -> Error: {e}")

print("\n--- REQUESTS ---")
for u in urls:
    try:
        r = requests.get(u, timeout=5)
        print(f"requests {u} -> Status: {r.status_code}, Len: {len(r.text)}")
    except Exception as e:
        print(f"requests {u} -> Error: {e}")
