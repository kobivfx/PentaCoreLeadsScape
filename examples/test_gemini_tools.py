"""Quick standalone test: Gemini API with urlContext + googleSearch tools.

Usage:
    set GEMINI_API_KEY=your-key-here
    python test_gemini_tools.py
"""
import json
import os
import httpx

API_KEY = "AIzaSyAXJGHKh9gwkIeqrt_j6snJMGajdcwUzFs"
MODEL = "gemini-flash-lite-latest"
URL = "https://generativelanguage.googleapis.com/v1beta"

if not API_KEY:
    print("Set GEMINI_API_KEY env var first!")
    raise SystemExit(1)

payload = {
    "contents": [
        {
            "role": "user",
            "parts": [
                {"text": "What is this post about? https://x.com/NakamotoGames/status/2042920599392055591"}
            ],
        }
    ],
    "generationConfig": {
        "responseMimeType": "text/plain",
    },
    "tools": [
        {"urlContext": {}},
        {"googleSearch": {}},
    ],
}

print(f"Model: {MODEL}")
print(f"Payload:\n{json.dumps(payload, indent=2)}\n")

endpoint = f"{URL}/models/{MODEL}:generateContent?key={API_KEY}"
print(f"Endpoint: {endpoint[:80]}...")

with httpx.Client(timeout=120) as client:
    resp = client.post(
        endpoint,
        json=payload,
        headers={"Content-Type": "application/json"},
    )

print(f"\nStatus: {resp.status_code}")
data = resp.json()

# Print full response for debugging
print(f"\nFull response:\n{json.dumps(data, indent=2, ensure_ascii=False)[:5000]}")

# Check candidates
candidates = data.get("candidates", [])
if candidates:
    cand = candidates[0]
    print(f"\nCandidate keys: {list(cand.keys())}")

    # Text
    parts = cand.get("content", {}).get("parts", [])
    for p in parts:
        if "text" in p:
            print(f"\nText: {p['text'][:500]}")

    # URL context metadata
    url_ctx = cand.get("urlContextMetadata") or cand.get("url_context_metadata")
    if url_ctx:
        print(f"\nURL Context Metadata: {json.dumps(url_ctx, indent=2)}")
    else:
        print("\n⚠ No urlContextMetadata in response!")

    # Grounding metadata
    grounding = cand.get("groundingMetadata") or cand.get("grounding_metadata")
    if grounding:
        print(f"\nGrounding Metadata: {json.dumps(grounding, indent=2)[:1000]}")
    else:
        print("\n⚠ No groundingMetadata in response!")
else:
    print("\n❌ No candidates in response!")
    print(f"promptFeedback: {data.get('promptFeedback')}")
