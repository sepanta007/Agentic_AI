# PIM Copilot — mini-project

A small chat web-app for a Fnac catalog manager — *your own Claude Desktop, but for the PIM*.
Paste a messy supplier blurb → the agent categorizes it, writes an on-brand entry, fills every
attribute (`null` where unknown), routes leftovers to `extra`, and **drafts** the product for your
review → you **confirm or reject** → only then is it created, instantly searchable and visible in
the [Light PIM visualizer](../../pim-prod/). You can also just ask it questions about the catalog.

This is the TD5 `run_agent` reason → act → observe loop (from `../TD5_agent.ipynb`), wrapped in
one HTTP endpoint, with a Vue chat UI on top.

## How it's wired

```
┌─────────────┐   POST /chat    ┌──────────────────┐   MCP / stdio    ┌──────────────────┐
│  Vue chat   │ ───────────────▶│  FastAPI backend  │ ───────────────▶│  TD4 pim_server   │
│  (web/)     │◀─────────────── │  (backend/)       │◀─────────────── │  (subprocess)     │
└─────────────┘  reply + trace  └──────────────────┘   list/call_tool └────────┬─────────┘
                                  Haiku + add_product skill                     │
                                                                        ┌───────▼────────┐
                                                                        │ chroma_db/      │
                                                                        │ (persistent,    │
                                                                        │  on disk)       │
                                                                        └───────┬────────┘
                                                                                │ same folder
                                                                        ┌───────▼────────┐
                                                                        │ Light PIM       │
                                                                        │ visualizer      │
                                                                        └────────────────┘
```

- **`backend/`** — the agent. `agent.py` holds `AgentRuntime`: it spawns
  `../../TD4_mcp/mini_project/pim_server.py` as a subprocess over **stdio** (`mcp.client.stdio`
  + `StdioServerParameters`) — the exact same server TD4's mini-project already built, unmodified
  in its logic, just reused as a subprocess instead of a Claude Desktop tool. `main.py` exposes it
  as `POST /chat` / `POST /confirm` (FastAPI) and serves `web/` as the static frontend, one process.
- **`web/`** — the chat UI (Vue 3, vendored — no build step, no npm). Renders the conversation and,
  for every assistant turn, the **tool-call trace** (`-> call: tool_name({...})`, expandable to see
  the tool's raw output) — the reason → act → observe loop, visible — plus the **draft review card**
  whenever the agent wants to write.
- **Human-in-the-loop, not just a trace.** The loop **pauses** the instant the model requests
  `create_product`: it does **not** call the tool. `POST /chat` comes back with
  `status: "pending_confirmation"` and the drafted product instead of a final reply; the UI renders
  it as a card with **Confirm** / **Reject** buttons. Nothing is written until the manager clicks
  Confirm (`POST /confirm {"approve": true}`) — Reject (`{"approve": false}`) tells the model it was
  turned down (without ever calling the tool) so it can revise or stop. Every other tool
  (`search_products`, `get_category_tree`, `get_category_attributes`) is a read and still executes
  immediately — only the one write is gated.
- We **don't** re-implement or import the TD4 tools; the backend only knows the server's file path.
  Because that server's index (`../TD4_mcp/mini_project/chroma_db/`) is **persistent**, whatever the
  copilot creates is immediately visible to the [Light PIM visualizer](../../pim-prod/) pointed at
  the same folder — no reindexing, no restart.

## Setup

Uses the **same virtualenv as the rest of the course** (the TD4 server subprocess needs
`chromadb` / `sentence-transformers` / `mcp`, already installed for TD1–TD4).

```bash
cd notebooks/TD5_agent/mini_project
pip install -r backend/requirements.txt
```

The frontend has **zero dependencies** — `web/vendor/vue.global.prod.js` is the same vendored
Vue 3 build the Light PIM visualizer uses, loaded straight from a `<script>` tag.

### 1. Build the TD4 index (if you haven't already)

The copilot's tool source is the TD4 mini-project server; make sure its persistent index exists:

```bash
cd ../../TD4_mcp/mini_project
python build_index.py   # builds ./chroma_db from ../../data/products.csv
```

`create_product` there now also accepts and round-trips an `extra` dict (supplier leftovers —
wholesale price, MOQ, warranty…), added specifically for this mini-project.

### 2. API key

No key in code — `backend/agent.py` loads `ANTHROPIC_API_KEY` from the **project-root `.env`**
(the same one every other TD uses). Nothing to configure if you already have it.

### 3. Run the backend (spawns the TD4 server itself — nothing else to start)

```bash
cd notebooks/TD5_agent/mini_project
uvicorn backend.main:app --reload --app-dir . --port 8001
```

Open **http://localhost:8001** — that's the chat UI, served by the same process.

### 4. Run the Light PIM visualizer, pointed at the SAME index

In another terminal (see [`../../pim-prod/README.md`](../../pim-prod/README.md) for details):

```bash
cd notebooks/pim-prod
pip install -r app/requirements.txt
PIM_INDEX_DIR=$(realpath ../TD4_mcp/mini_project/chroma_db) uvicorn app.main:app --reload --app-dir . --port 8000
```

Open **http://localhost:8000** — or use its **Index** picker and pick
`TD4_mcp/mini_project/chroma_db` from the dropdown.

### 5. The payoff loop

1. In the chat (http://localhost:8001), paste a supplier blurb (or click the suggestion chip) and
   send it.
2. Watch the trace: `get_category_tree` → `get_category_attributes` → `search_products` — then a
   **draft card** appears instead of `create_product` firing right away.
3. Click **Confirm & create** (or **Reject** to send it back for revision, without writing anything).
4. Refresh the Light PIM (http://localhost:8000) — the new product is there, fully attributed,
   `null`s flagged, `extra` preserved.

You can also just ask questions — *"what ANC headphones under €300 do we carry?"* — the agent
answers with `search_products` directly, no draft, no write involved.

## API

| Method | Route | |
|---|---|---|
| POST | `/chat` `{message}` | Runs the reason → act → observe loop (as many read-tool calls as needed) and returns one of:<br>`{status: "done", reply, trace}` — final answer, nothing pending;<br>`{status: "pending_confirmation", draft, trace}` — the agent wants to `create_product`; `draft` is its full input, `trace` covers the reads that led up to it;<br>`{status: "error", reply}` — e.g. a draft is already awaiting confirmation. `trace` is `[{tool, input, output}, ...]` in call order. Conversation state lives in the backend process (single-user POC). |
| POST | `/confirm` `{approve}` | Resolves the one pending draft: `approve: true` actually calls `create_product` and resumes the loop; `approve: false` tells the model it was rejected (the tool is **never** called) and resumes. Returns the same `{status, reply\|draft, trace}` shape as `/chat`. |
| POST | `/reset` | Clears the running conversation **and** any pending draft (the catalog itself is untouched). |

## Notes / scope

- **Haiku only**, per the course's `MODEL = "claude-haiku-4-5"` — same as the notebook.
- **Human-in-the-loop is implemented** (the *going further* stretch): the agent drafts, the manager
  confirms or rejects, only then does the write happen — see `CONFIRM_BEFORE` in `agent.py` (today
  just `create_product`; add more write tools there if you add them).
- **Single conversation, single process** — this is a POC, not a multi-tenant app: the backend
  keeps one conversation (and at most one pending draft) in memory, reset with the "New
  conversation" button (or `POST /reset`). The composer is disabled while a draft is pending — one
  thing to resolve at a time, in call order.
- The backend never touches ChromaDB or MiniLM directly — every catalog read/write goes through
  the TD4 server's MCP tools, over stdio, exactly like Claude Desktop would.

## Files

```
mini_project/
├── backend/
│   ├── agent.py          # AgentRuntime: MCP stdio session + Haiku loop (the TD5 run_agent, persisted)
│   ├── main.py            # FastAPI app: POST /chat, POST /reset, serves web/
│   └── requirements.txt
└── web/
    ├── index.html · app.js · styles.css   # Vue 3 chat UI (no build step)
    └── vendor/vue.global.prod.js
```
