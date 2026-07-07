"""Build (or rebuild) the persistent ChromaDB index used by pim_server.py.

Run once before first use:
    python build_index.py

pim_server.py also builds the index automatically on first run if it's empty,
so this script is mostly useful to force a rebuild (e.g. after editing
products.csv) -- delete chroma_db/ first, or call build_index() directly.
"""
from pim_server import build_index

if __name__ == "__main__":
    count = build_index()
    print(f"Indexed {count} products into ChromaDB (./chroma_db).")
