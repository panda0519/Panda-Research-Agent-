import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

model_name = os.getenv("GEMINI_MODEL", "models/gemini-flash-lite-latest")
print(f"Testing direct call to GEMINI_MODEL: {model_name}...")
try:
    response = client.models.generate_content(
        model=model_name,
        contents="Reply with exactly one word: OK",
    )
    print("RAW RESPONSE TEXT:", repr(response.text))
    print(f"SUCCESS with model: {model_name}")
except Exception as e:
    print(f"FAILED {model_name}: {e}")
    print("\nListing available generateContent models...")
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" in actions and "flash" in m.name.lower():
            print(f" - {m.name}")


