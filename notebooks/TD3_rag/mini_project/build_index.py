import os
import json
import pandas as pd
import chromadb
from sentence_transformers import SentenceTransformer

DATA_PATH = "../../data/products.csv"
DB_PATH = "./chroma_db"

df = pd.read_csv(DATA_PATH)
df["doc"] = df["name"] + " — " + df["long_description"]

embed_model = SentenceTransformer("all-MiniLM-L6-v2")

# Persistent Chroma DB
client = chromadb.PersistentClient(path=DB_PATH)

# recreate collection cleanly
try:
    client.delete_collection("catalog")
except:
    pass

collection = client.create_collection("catalog")

print("Embedding corpus...")
embeddings = embed_model.encode(df["doc"].tolist(), show_progress_bar=True).tolist()

print("Indexing into Chroma...")

collection.add(
    ids=df["sku"].tolist(),
    embeddings=embeddings,
    documents=df["doc"].tolist(),
    metadatas=[
        {
            "name": r["name"],
            "brand": r["brand"],
            "category": r["category"],
            "price": float(r["price"]),
            "short_description": r["short_description"],
            "long_description": r["long_description"],
            "attributes": r["attributes"],
        }
        for _, r in df.iterrows()
    ],
)

print(f"Done. Indexed {collection.count()} products.")