import os
from dotenv import load_dotenv
load_dotenv("static/.env")

key = os.getenv("GEMINI_API_KEY", "").strip().strip('"').strip("'")
print(f"API Key cargada: {key[:20]}...")

from google import genai
client = genai.Client(api_key=key)

print("\nModelos de embedding disponibles:")
for m in client.models.list():
    if "embed" in m.name.lower():
        print(f"  - {m.name}")

print("\nTodos los modelos disponibles:")
for m in client.models.list():
    print(f"  - {m.name}")
