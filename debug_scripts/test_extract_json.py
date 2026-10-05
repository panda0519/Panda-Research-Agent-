import os, sys
sys.path.insert(0, os.path.abspath("."))

from llm.client import extract_json

# Test 1: Standard JSON with fences
t1 = '```json\n{"key": "value", "escaped_quote": "\\"test\\"", "newline": "\\n"}\n```'
res1 = extract_json(t1)
assert res1["key"] == "value"
assert res1["escaped_quote"] == '"test"'
assert res1["newline"] == '\n'
print("Test 1 passed")

# Test 2: Invalid JSON escapes (e.g. LaTeX \alpha or regex \d or Windows path C:\path)
t2 = r'{"formula": "\alpha + \beta", "regex": "\d+\s*", "path": "C:\test\new_dir"}'
res2 = extract_json(t2)
assert res2["formula"] == r"\alpha + \beta"
assert res2["regex"] == r"\d+\s*"
print("Test 2 passed")

# Test 3: List format with stray backslash
t3 = r'["Item 1: \O(n) complexity", "Item 2: 100%"]'
res3 = extract_json(t3)
assert len(res3) == 2
print("Test 3 passed")

print("ALL EXTRACT_JSON TESTS PASSED")
