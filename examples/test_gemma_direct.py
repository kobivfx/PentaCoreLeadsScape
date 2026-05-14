#!/usr/bin/env python
"""Test Gemma-4 direct inference to debug the prefilter issue."""
import sys
from llama_cpp import Llama

MODEL_PATH = r"C:\Users\anhdd\Downloads\gemma-4-E4B.i1-Q6_K.gguf"

print(f"Loading model: {MODEL_PATH}")
llm = Llama(
    model_path=MODEL_PATH,
    n_ctx=8192,
    n_gpu_layers=-1,
    verbose=False,
)
print("✅ Model loaded\n")

# Test 1: Raw completion API
print("=" * 60)
print("TEST 1: Raw Completion (text)")
print("=" * 60)
prompt1 = """Does this content describe a company or project seeking 3D animation, cinematic, or visual effects outsourcing services? Answer Yes or No only.

Content:
Studio XYZ announces a partnership with an outsourcing vendor for 3D cinematics.

Answer (Yes or No):"""

resp1 = llm(
    prompt1,
    max_tokens=16,
    temperature=0.1,
    top_p=0.95,
    stop=["\n"],
)
raw1 = resp1["choices"][0]["text"]
print(f"Raw: {repr(raw1)}")
print(f"Stripped: {raw1.strip()}\n")

# Test 2: Chat completion API
print("=" * 60)
print("TEST 2: Chat Completion API")
print("=" * 60)
resp2 = llm.create_chat_completion(
    messages=[{"role": "user", "content": "Does this content describe a company or project seeking 3D animation, cinematic, or visual effects outsourcing services? Answer Yes or No only.\n\nContent:\nStudio XYZ announces a partnership with an outsourcing vendor for 3D cinematics.\n\nAnswer (Yes or No):"}],
    max_tokens=16,
    temperature=0.1,
    top_p=0.95,
)
raw2 = resp2["choices"][0]["message"]["content"]
print(f"Raw: {repr(raw2)}")
print(f"Stripped: {raw2.strip()}\n")

# Test 3: Simpler prompt with higher max_tokens
print("=" * 60)
print("TEST 3: Simple Question (max_tokens=32)")
print("=" * 60)
prompt3 = "Answer Yes or No: Does this text mention 3D animation outsourcing?\n\nStudio XYZ announces a partnership with an outsourcing vendor for 3D cinematics.\n\nAnswer:"
resp3 = llm(
    prompt3,
    max_tokens=32,
    temperature=0.1,
    top_p=0.95,
)
raw3 = resp3["choices"][0]["text"]
print(f"Raw: {repr(raw3)}")
print(f"Stripped: {raw3.strip()}\n")

# Test 4: Even simpler - just Yes/No
print("=" * 60)
print("TEST 4: Minimal Question (max_tokens=32)")
print("=" * 60)
prompt4 = "Question: Is this about 3D animation outsourcing? Yes or No.\nText: Studio XYZ announces partnership for 3D cinematics.\nAnswer:"
resp4 = llm(
    prompt4,
    max_tokens=32,
    temperature=0.1,
    top_p=0.95,
)
raw4 = resp4["choices"][0]["text"]
print(f"Raw: {repr(raw4)}")
print(f"Stripped: {raw4.strip()}\n")
