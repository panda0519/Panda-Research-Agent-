import os
import sys
from dotenv import load_dotenv

# Ensure workspace root is on sys.path and load env
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from llm.client import LLMClient

client = LLMClient()
result = client.generate(
    prompt="Reply with exactly one word: OK",
    system_prompt="You are a terse assistant.",
    temperature=0.2,
    max_tokens=50,
)
print("TYPE:", type(result))
print("VALUE:", repr(result))


