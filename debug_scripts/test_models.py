import os
import time
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

prompt = "Return a JSON object: {\"message\": \"hello world\"}"

def call_gemini(prompt: str):
    gemini_model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    for candidate in [gemini_model_name, "gemini-3.5-flash", "gemini-3.6-flash"]:
        for attempt in range(3):
            try:
                model_inst = genai.GenerativeModel(candidate)
                response = model_inst.generate_content(
                    prompt,
                    generation_config={"temperature": 0.2},
                )
                return response.text
            except Exception as exc:
                err_str = str(exc)
                if "429" in err_str or "quota" in err_str.lower():
                    if attempt < 2:
                        time.sleep(5)
                        continue
                if "is no longer available" in err_str or "not found" in err_str.lower() or "404" in err_str:
                    break
                if attempt == 2:
                    raise
    raise RuntimeError("All Gemini model candidates failed.")

print("Calling Gemini...")
res = call_gemini(prompt)
print("Result:", res)
