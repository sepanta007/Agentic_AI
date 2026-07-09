"""PIM Copilot -- FastAPI backend.

One process: `POST /chat` runs the agent's reason -> act -> observe loop (agent.py) and
returns the assistant's reply plus the tool-call trace; the same process also serves the
Vue chat UI (`../web/`), the same pattern as the Light PIM visualizer next door.

Human-in-the-loop: `POST /chat` may come back with `status: "pending_confirmation"` instead
of a final reply -- the agent drafted a `create_product` call but paused before running it.
`POST /confirm` approves or rejects that ONE pending draft and resumes the loop.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import AgentRuntime

WEB_DIR = Path(__file__).resolve().parents[1] / "web"

runtime = AgentRuntime()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await runtime.start()
    print(f"PIM Copilot ready -- {len(runtime.anthropic_tools)} tools from the TD4 stdio server.")
    yield
    await runtime.stop()


app = FastAPI(title="PIM Copilot", lifespan=lifespan)


class ChatBody(BaseModel):
    message: str


class ConfirmBody(BaseModel):
    approve: bool


@app.post("/chat")
async def chat(body: ChatBody):
    return await runtime.chat(body.message)


@app.post("/confirm")
async def confirm(body: ConfirmBody):
    return await runtime.resolve(body.approve)


@app.post("/reset")
async def reset():
    runtime.reset()
    return {"status": "reset"}


# -- static frontend (mounted last so /chat and /reset win) -----------------------------
@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/", StaticFiles(directory=WEB_DIR), name="web")
