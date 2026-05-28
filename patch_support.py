import chromadb
import os

db_path = os.path.join(os.getcwd(), "memory_core_db")
client = chromadb.PersistentClient(path=db_path)
support_kb = client.get_or_create_collection(name="support_knowledge_base")

# Adding the exact fix for the error you just saw
support_kb.add(
    documents=["401 Unauthorized: API Key check failed"],
    metadatas=[{
        "solution": "Check your .env file. You are likely using Paper Keys with a Live URL. Use https://paper-api.alpaca.markets for paper trading."
    }],
    ids=["err_401_detailed"]
)

print("--- [BRAIN UPDATED] Sentinel now knows the 401 fix ---")