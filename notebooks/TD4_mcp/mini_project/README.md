# PIM MCP server — mini-project

A standalone **stdio** MCP server exposing the PIM catalog as five tools, spawnable by
Claude Desktop (or any MCP client) as a subprocess. This is the out-of-process
counterpart to the in-memory server built in `TD4_mcp.ipynb`.

The **persistent ChromaDB index** (`./chroma_db/`) is the source of truth for products:
built once from `../../data/products.csv`, then read *and written* through the tools.

## Tools exposed

| Tool | Description |
|---|---|
| `search_products(query, k=3)` | Semantic search over the persistent ChromaDB index (the TD3 RAG, as a tool). |
| `get_product(sku)` | Read one product back from ChromaDB by its id. |
| `get_category_tree()` | Top categories → leaf categories, from `taxonomy.json`. |
| `get_category_attributes(category)` | A leaf category's applicable attribute schema, from `taxonomy.json`. |
| `create_product(...)` | Embed a new product with MiniLM and add it to ChromaDB — immediately searchable, no reindexing. |

No API key is used anywhere in this server — Claude Desktop brings its own model.

## Setup

```bash
cd notebooks/TD4_mcp/mini_project
pip install -r requirements.txt
```

### Build the index

The server builds `./chroma_db/` automatically on first run if it's empty, but you can
also build (or force-rebuild, e.g. after editing `products.csv`) it explicitly:

```bash
python build_index.py
```

### Sanity-check over stdio (optional, no Claude Desktop needed)

Spawns `pim_server.py` as a subprocess and calls every tool purely over the MCP
protocol, the way Claude Desktop will:

```bash
python client_demo.py
```

## Connect to Claude Desktop

1. Install [Claude Desktop](https://claude.ai/download) and sign in.
2. **Settings → Developer → Edit Config** to open (or create) `claude_desktop_config.json`
   (on Linux: `~/.config/Claude/claude_desktop_config.json`).
3. Register the server, using **absolute paths** for both `command` and `args`:

```json
{
  "mcpServers": {
    "pim": {
      "command": "/home/sepanta/Agentic_AI/.venv/bin/python",
      "args": ["/home/sepanta/Agentic_AI/notebooks/TD4_mcp/mini_project/pim_server.py"]
    }
  }
}
```

   Adjust both paths if your checkout or virtualenv live elsewhere.

4. **Fully quit and reopen Claude Desktop** (MCP servers are only read at startup).
5. In a new chat, open the tools / MCP menu (🛠️ icon) and confirm the **`pim`** server
   lists `search_products`, `get_product`, `get_category_tree`, `get_category_attributes`,
   `create_product`.

## Questions to try in Claude Desktop

- *"What noise-cancelling headphones do we carry under €300?"* → calls `search_products`.
- *"What's the attribute schema for Wireless Earbuds?"* → calls `get_category_attributes`.
- *"Add this product, then find it: a lightweight white wireless earbud with active noise
  cancellation, 8h battery, IPX4 water resistance, USB-C charging case, €129."* → calls
  `create_product`, then `search_products` — the new item comes back seconds later, no
  reindexing.

## Files

- `pim_server.py` — the stdio MCP server (all 5 tools).
- `build_index.py` — (re)builds `./chroma_db/` from `products.csv`.
- `client_demo.py` — tiny stdio client that discovers and calls every tool, no Claude Desktop needed.
- `requirements.txt`
