import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from google import genai
from google.genai import types

gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
response = gemini_client.models.generate_content(
    model="gemini-3.5-flash",
    contents="Reply with exactly one word: OK",
    config=types.GenerateContentConfig(
        system_instruction="You are a terse assistant.",
        temperature=0.2,
        max_output_tokens=1000,
    ),
)
print("response.text with gemini-3.5-flash:", repr(response.text))



