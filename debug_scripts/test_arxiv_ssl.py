import ssl
import urllib.request

ctx = ssl.create_default_context()
ctx.set_ciphers('DEFAULT@SECLEVEL=1')

url = "https://export.arxiv.org/api/query?id_list=2101.09884"
req = urllib.request.Request(
    url,
    headers={
        "User-Agent": "curl/8.21.0",
        "Accept": "*/*",
    }
)

try:
    with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
        print("Status:", r.status)
        print("Read len:", len(r.read()))
except Exception as e:
    print("Error:", e)
