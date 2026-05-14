from llama_cpp import Llama

llm = Llama(
    model_path="E:\\Pentacore\\Tool\\model\\gemma-4-E4B.Q4_K_M.gguf",
    n_ctx=4096,
    n_gpu_layers=-1,
    verbose=True
)

prompt = """You are a strict classifier.

Answer ONLY "Yes" or "No".

Question:
Is this a game studio hiring for a new project?

Content:
This studio is hiring Unreal Engine developers for a new RPG.

Answer:"""

output = llm(
    prompt,
    max_tokens=10,
    temperature=0,
    stop=["\n"]
)

print("RAW OUTPUT:")
print(output)
print("TEXT:")
print(output["choices"][0]["text"])