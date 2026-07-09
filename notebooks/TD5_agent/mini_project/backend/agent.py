"""The PIM Copilot's agent: the TD5 reason -> act -> observe loop, kept alive as a
long-running MCP stdio client instead of the notebook's short-lived in-memory session.

Reuses the TD4 mini-project server AS-IS, over stdio: we never import its tools, we
just spawn `pim_server.py` as a subprocess (venv python + absolute path) and speak
MCP over its stdin/stdout, exactly like the notebook's in-memory transport did --
only the transport changed. Its persistent `chroma_db` on disk is what makes the
PIM Copilot -> Light PIM round-trip work: whatever the agent creates here, the
visualizer sees a moment later.
"""
import asyncio
import json
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BACKEND_DIR = Path(__file__).resolve().parent
NOTEBOOKS_DIR = BACKEND_DIR.parents[2]        # backend -> mini_project -> TD5_agent -> notebooks
REPO_ROOT = NOTEBOOKS_DIR.parent

TD4_SERVER = NOTEBOOKS_DIR / "TD4_mcp" / "mini_project" / "pim_server.py"
SKILL_PATH = NOTEBOOKS_DIR / "data" / "skills" / "add_product" / "SKILL.md"

load_dotenv(REPO_ROOT / ".env")  # ANTHROPIC_API_KEY lives at the project root, never in code

MODEL = "claude-haiku-4-5"
MAX_ITERS = 12

# The one WRITE tool -- every call to it pauses the loop for the manager's confirmation
# before it actually runs. Every other tool (search_products, get_category_tree, ...) is a
# read and executes immediately, same as before.
CONFIRM_BEFORE = {"create_product"}


class AgentRuntime:
    """Owns one persistent MCP stdio session to the TD4 server, the Anthropic client, the
    add_product skill, and the running conversation -- i.e. everything `run_agent` needed
    in the notebook, minus the in-memory MCP transport.

    Adds the mini-project's human-in-the-loop stretch goal: when the model requests a
    CONFIRM_BEFORE tool, the loop PAUSES instead of executing it -- `chat()` returns a
    `pending_confirmation` draft for the UI to show, and nothing is written until the
    manager calls `resolve(approve=True/False)`.
    """

    def __init__(self):
        if not TD4_SERVER.exists():
            raise RuntimeError(f"TD4 server not found at {TD4_SERVER} -- build it first (TD4 mini-project).")
        self.skill = SKILL_PATH.read_text()
        self.client = anthropic.Anthropic()
        self.messages = []
        self.anthropic_tools = []
        self._session: ClientSession | None = None
        self._stack = AsyncExitStack()
        self._pending = None  # {"block": tool_use_block, "tool_results": [...]} while awaiting confirmation

    async def start(self):
        """Spawn the TD4 stdio server (venv python + absolute path) and discover its tools."""
        params = StdioServerParameters(command=sys.executable, args=[str(TD4_SERVER)])
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        listed = await self._session.list_tools()
        self.anthropic_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.inputSchema}
            for t in listed.tools
        ]

    async def stop(self):
        await self._stack.aclose()

    def reset(self):
        """Drop the conversation so far; the MCP session and catalog are untouched."""
        self.messages = []
        self._pending = None

    async def chat(self, user_text, max_iters=MAX_ITERS):
        """Run the reason -> act -> observe loop for `user_text` until it produces a final
        answer OR hits a write tool that needs confirmation. Returns a dict:
          {"status": "done", "reply": str, "trace": [...]}
          {"status": "pending_confirmation", "draft": dict, "trace": [...]}
          {"status": "error", "reply": str}  -- e.g. a confirmation is already pending
        """
        if self._pending is not None:
            return {"status": "error",
                    "reply": "A product draft is still awaiting your confirmation -- resolve it first."}
        self.messages.append({"role": "user", "content": user_text})
        return await self._run_loop(max_iters, trace=[])

    async def resolve(self, approve: bool, max_iters=MAX_ITERS):
        """Confirm or reject the pending write, then resume the loop. On reject, the tool is
        never called -- the model is told so, and can revise or stop instead."""
        if self._pending is None:
            return {"status": "error", "reply": "Nothing is awaiting confirmation."}

        pending = self._pending
        self._pending = None
        block = pending["block"]
        tool_results = pending["tool_results"]
        trace = []

        if approve:
            out = await self._session.call_tool(block.name, block.input)
            result_text = "\n".join(c.text for c in out.content)
        else:
            result_text = ("The manager REJECTED this action -- it was NOT applied to the catalog. "
                            "Ask what should change, or acknowledge the cancellation.")
        trace.append({"tool": block.name, "input": block.input, "output": result_text, "confirmed": approve})
        tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_text})
        self.messages.append({"role": "user", "content": tool_results})

        return await self._run_loop(max_iters, trace)

    async def _run_loop(self, max_iters, trace):
        """The TD5 run_agent loop, generalized to pause on a CONFIRM_BEFORE tool_use block
        instead of executing it. `trace` is appended to in place and returned in the result."""
        for _ in range(max_iters):
            resp = await asyncio.to_thread(
                self.client.messages.create,
                model=MODEL, max_tokens=1024, system=self.skill,
                tools=self.anthropic_tools, messages=self.messages,
            )

            if resp.stop_reason != "tool_use":
                reply = "".join(block.text for block in resp.content if block.type == "text")
                self.messages.append({"role": "assistant", "content": resp.content})
                return {"status": "done", "reply": reply, "trace": trace}

            self.messages.append({"role": "assistant", "content": resp.content})

            tool_results = []
            pending_block = None
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                if block.name in CONFIRM_BEFORE and pending_block is None:
                    pending_block = block  # hold this one -- don't call it yet
                    continue
                out = await self._session.call_tool(block.name, block.input)
                result_text = "\n".join(c.text for c in out.content)
                trace.append({"tool": block.name, "input": block.input, "output": result_text})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })

            if pending_block is not None:
                self._pending = {"block": pending_block, "tool_results": tool_results}
                return {"status": "pending_confirmation", "draft": pending_block.input, "trace": trace}

            self.messages.append({"role": "user", "content": tool_results})

        reply = f"Stopped after {max_iters} tool calls without a final answer -- try rephrasing your request."
        return {"status": "done", "reply": reply, "trace": trace}
