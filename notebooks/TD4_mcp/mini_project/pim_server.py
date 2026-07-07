"""Standalone stdio MCP server exposing the PIM catalog as tools.

Spawnable by Claude Desktop (or any MCP client) over stdio:
    python pim_server.py

The persistent ChromaDB index (./chroma_db) is the source of truth for products.
It is built once from ../../data/products.csv and then read AND written through
the tools below -- `create_product` embeds and adds straight into it, so new
products are immediately searchable by `search_products`, no reindexing needed.
"""
import json
from pathlib import Path

import chromadb
import pandas as pd
from mcp.server.fastmcp import FastMCP
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent.parent / "data"
CHROMA_DIR = BASE_DIR / "chroma_db"

mcp_server = FastMCP("pim")

with open(DATA_DIR / "taxonomy.json") as f:
    taxonomy = json.load(f)

_chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
_collection = _chroma_client.get_or_create_collection("catalog")

_embed_model = None


def get_embed_model():
    """Lazily load the shared MiniLM model (same one used in TD1 -> TD3 -> TD4)."""
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model


def build_index():
    """(Re)build the persistent ChromaDB index from products.csv, from scratch."""
    global _collection
    if "catalog" in [c.name for c in _chroma_client.list_collections()]:
        _chroma_client.delete_collection("catalog")
    _collection = _chroma_client.create_collection("catalog")

    df = pd.read_csv(DATA_DIR / "products.csv")
    df["doc"] = df["name"] + " — " + df["long_description"]
    embeddings = get_embed_model().encode(df["doc"].tolist(), show_progress_bar=False)
    _collection.add(
        ids=df["sku"].tolist(),
        embeddings=embeddings.tolist(),
        documents=df["doc"].tolist(),
        metadatas=[
            {
                "name": r["name"], "brand": r["brand"], "category": r["category"],
                "price": float(r["price"]), "short_description": r["short_description"],
                "long_description": r["long_description"], "attributes": r["attributes"],
            }
            for _, r in df.iterrows()
        ],
    )
    return _collection.count()


if _collection.count() == 0:
    build_index()


def _hit_from(sku, meta):
    hit = {"sku": sku, **meta}
    if isinstance(hit.get("attributes"), str):  # stored as a JSON string -> parse back to a dict
        hit["attributes"] = json.loads(hit["attributes"])
    return hit


@mcp_server.tool()
def search_products(query: str, k: int = 3) -> list:
    """Semantic search over the product catalog; returns up to k products most similar to the query."""
    q_vec = get_embed_model().encode(query).tolist()
    res = _collection.query(query_embeddings=[q_vec], n_results=k)
    return [_hit_from(sku, meta) for sku, meta in zip(res["ids"][0], res["metadatas"][0])]


@mcp_server.tool()
def get_product(sku: str) -> dict:
    """Return one product by its SKU (full stored metadata), or {} if no product has that SKU."""
    res = _collection.get(ids=[sku])
    if not res["ids"]:
        return {}
    return _hit_from(res["ids"][0], res["metadatas"][0])


@mcp_server.tool()
def get_category_tree() -> dict:
    """Return the catalog category tree as {top_category: [leaf_category, ...]}."""
    return {
        cat["name"]: [sub["name"] for sub in cat["subcategories"]]
        for cat in taxonomy["categories"]
    }


@mcp_server.tool()
def get_category_attributes(category: str) -> dict:
    """Return the applicable attribute schema for a leaf category, or {} if the category is unknown."""
    for top in taxonomy["categories"]:
        for leaf in top["subcategories"]:
            if leaf["name"] == category:
                schema = {}
                for attr in leaf["category_attributes"]:
                    if "values" in attr:
                        schema[attr["name"]] = attr["values"]
                    elif "unit" in attr:
                        schema[attr["name"]] = f'{attr["type"]} ({attr["unit"]})'
                    else:
                        schema[attr["name"]] = attr["type"]
                return schema
    return {}


@mcp_server.tool()
def create_product(
    name: str,
    brand: str,
    category: str,
    price: float,
    short_description: str,
    long_description: str,
    attributes: dict,
    sku: str = "",
) -> dict:
    """Create a new product and add it to the ChromaDB index so it's immediately searchable.

    `attributes` should match the schema returned by get_category_attributes for `category`.
    If `sku` is omitted, one is generated. Returns the created product (with its sku).
    """
    if not sku:
        existing = [s for s in _collection.get()["ids"] if s.startswith("SKU-")]
        nums = [int(s.split("-")[-1]) for s in existing]
        sku = f"SKU-{(max(nums) + 1) if nums else 1:04d}"

    doc = f"{name} — {long_description}"
    metadata = {
        "name": name, "brand": brand, "category": category, "price": float(price),
        "short_description": short_description, "long_description": long_description,
        "attributes": json.dumps(attributes),
    }
    _collection.add(
        ids=[sku],
        embeddings=[get_embed_model().encode(doc).tolist()],
        documents=[doc],
        metadatas=[metadata],
    )
    return _hit_from(sku, metadata)


if __name__ == "__main__":
    mcp_server.run(transport="stdio")
