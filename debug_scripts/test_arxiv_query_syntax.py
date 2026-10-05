import urllib.request
import urllib.parse

queries = [
    'search_query=all:"speech diarization"',
    'search_query=all:speech+AND+all:diarization',
    'search_query=ti:"speech diarization"',
    'search_query=speech+diarization',
    'search_query=all:electron',
    'id_list=2101.09884',
]

for q in queries:
    url = f"https://export.arxiv.org/api/query?{q}&max_results=2"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"Query [{q}] -> Status: {resp.status}, Len: {len(resp.read())}")
    except Exception as e:
        print(f"Query [{q}] -> Error: {e}")
