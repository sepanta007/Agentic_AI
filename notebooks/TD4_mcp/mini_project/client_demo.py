"""Tiny stdio MCP client: spawns pim_server.py as a subprocess and calls every tool.

This is the out-of-process boundary the notebook's in-memory transport hid: this
script never imports pim_server's functions -- it discovers and calls them purely
over the MCP protocol, exactly like Claude Desktop will.

Run:
    python client_demo.py
"""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_PATH = Path(__file__).resolve().parent / "pim_server.py"


def parse_one(result):
    """Tools that return a dict send it as a single content block."""
    return json.loads(result.content[0].text)


def parse_many(result):
    """Tools that return a list send ONE content block per item."""
    return [json.loads(c.text) for c in result.content]


async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER_PATH)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            print("Discovered tools:", [t.name for t in listed.tools])

            tree = parse_one(await session.call_tool("get_category_tree", {}))
            print("\nCategory tree:", tree)

            attrs = parse_one(await session.call_tool("get_category_attributes", {"category": "Headphones"}))
            print("\nHeadphones attributes:", attrs)

            hits = parse_many(await session.call_tool("search_products", {"query": "noise cancelling headphones", "k": 3}))
            print("\nsearch_products hits:")
            for h in hits:
                print(f"  - {h['sku']}  {h['name']}  ({h['category']}, EUR {h['price']:.0f})")

            created = parse_one(await session.call_tool("create_product", {
                "name": "Aria Studio Buds",
                "brand": "Aria",
                "category": "Wireless Earbuds",
                "price": 129.0,
                "short_description": "Compact earbuds with active noise cancellation.",
                "long_description": "Aria Studio Buds pack active noise cancellation and 8 hours "
                                     "of battery life into a lightweight, sweat-resistant design.",
                "attributes": {
                    "color": "White", "noise_cancellation": "Yes",
                    "battery_life_hours": 8, "water_resistance": "IPX4",
                    "case_charging": "USB-C",
                },
            }))
            print("\ncreate_product ->", created)

            fetched = parse_one(await session.call_tool("get_product", {"sku": created["sku"]}))
            print("get_product(new sku) ->", fetched)

            fresh_hits = parse_many(await session.call_tool("search_products", {"query": "Aria Studio Buds", "k": 1}))
            print("\nsearch_products finds the new product immediately:", fresh_hits[0]["sku"], fresh_hits[0]["name"])


if __name__ == "__main__":
    asyncio.run(main())
