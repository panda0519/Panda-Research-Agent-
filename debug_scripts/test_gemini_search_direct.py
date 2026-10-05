import asyncio
import os
import sys
sys.path.insert(0, os.path.abspath("."))
from dotenv import load_dotenv
load_dotenv()

from search.adapters.gemini_adapter import GeminiSearchAdapter

async def main():
    adapter = GeminiSearchAdapter()
    query = "Python async await tutorial"
    print("Adapter initialized:", adapter._client is not None)
    results = await adapter.search(query, max_results=3)
    print("Results:", results)
    
    # Also test calling client directly to see response.text
    model_name = os.getenv("GEMINI_MODEL", "models/gemini-flash-latest")
    prompt = f"""Search Google for technical information on the query: '{query}'.
Return ONLY a valid JSON array of objects with keys: "url", "title", "snippet".
Limit to 3 top results.
"""
    try:
        resp = adapter._client.models.generate_content(model=model_name, contents=prompt)
        print("Direct response.text:\n", resp.text)
    except Exception as e:
        print("Direct call error:", e)

asyncio.run(main())

