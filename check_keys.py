import os
from dotenv import load_dotenv
load_dotenv()
for k in ["ANTHROPIC_API_KEY", "TAVILY_API_KEY", "GEMINI_API_KEY", "VOYAGE_API_KEY", "GOOGLE_API_KEY"]:
    v = os.getenv(k)
    print(k, "SET (len=%d)" % len(v) if v else "MISSING")