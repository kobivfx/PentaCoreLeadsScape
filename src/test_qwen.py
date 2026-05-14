#!/usr/bin/env python
"""Test Gemma-4 direct inference to debug the prefilter issue."""
import sys
from llama_cpp import Llama

MODEL_PATH = r"C:\\Users\\anhdd\Downloads\\Qwen3.5-9B-BF16.gguf"

print(f"Loading model: {MODEL_PATH}")
llm = Llama(
    model_path=MODEL_PATH,
    n_ctx=8192,
    n_gpu_layers=-1,
    verbose=False,
)
print("✅ Model loaded\n")
# Test 1: Chat completion API
print("=" * 60)
print("TEST 1: Chat Completion API")
print("=" * 60)
resp1 = llm.create_chat_completion(
    messages=[{"role": "user", "content": "Does this content describe a game will release soon? Answer Yes or No only.\n\nContent:\nStudio XYZ announces a partnership with an outsourcing vendor for 3D cinematics for their new game trailer.\n\nAnswer (Yes or No):"}],
    max_tokens=32,
    temperature=1.0,
    top_p=0.95,
)
raw1 = resp1["choices"][0]["message"]["content"]
print(f"Raw: {repr(raw1)}")
print(f"Stripped: {raw1.strip()}\n")

# Test 2: Chat completion API
print("=" * 60)
print("TEST 2: Chat Completion API")
print("=" * 60)
resp2 = llm.create_chat_completion(
    messages=[{"role": "user", "content": "Does this content describe a company or project seeking 3D animation, cinematic, or visual effects outsourcing services? Answer Yes or No only.\n\nContent:\nneed a studio to make a 3D cinematics for their new game trailer.\n\nAnswer (Yes or No):"}],
    max_tokens=32,
    temperature=1.0,
    top_p=0.95,
)
raw2 = resp2["choices"][0]["message"]["content"]
print(f"Raw: {repr(raw2)}")
print(f"Stripped: {raw2.strip()}\n")

# Test 3: Chat completion API
print("=" * 60)
print("TEST 3: Chat Completion API")
print("=" * 60)
resp3 = llm.create_chat_completion(
    messages=[{"role": "user", "content": "Does this content describe a company or project seeking 3D animation, cinematic, or visual effects outsourcing services? Answer Yes or No only.\n\nContent:\nStudio XYZ announces new game.\n\nAnswer (Yes or No):"}],
    max_tokens=32,
    temperature=1.0,
    top_p=0.95,
)
raw3 = resp3["choices"][0]["message"]["content"]
print(f"Raw: {repr(raw3)}")
print(f"Stripped: {raw3.strip()}\n")
