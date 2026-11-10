# mcp_hub.py
"""TRON as a universal MCP client: any MCP server (Slack, Notion, GitHub, Home Assistant, a filesystem, your
own) becomes TRON's tools, for both brains, under TRON's own safety rules.

config.json:
    "mcp_servers": {
        "notion": {"command": "npx", "args": ["-y", "@notionhq/notion-mcp-server"],
                   "env": {"NOTION_TOKEN": "..."}},
        "home":   {"url": "http://homeassistant.local:8123/mcp_server/sse"}     <- or any streamable-HTTP URL
    }

Each server's tools appear as "<server>__<tool>". A tool its server marks read-only runs freely; every other
one needs the user's spoken yes (brain.Guard), because TRON can't know what an unknown tool changes. Text that
comes back is content, never instructions. A server that fails to start is skipped and logged; the rest work.
"""
import asyncio
import re
import threading

import config

_loop = None
_sessions: dict = {}     # server name -> ClientSession
_errors: dict = {}       # server name -> why it isn't connected


def _tool_name(server: str, tool: str) -> str:
    # Gemini's rule for function names: letters, digits, underscores, at most 64 characters
    return re.sub(r"[^A-Za-z0-9_]", "_", f"{server}__{tool}")[:64]


async def _serve(name: str, spec: dict, ready: asyncio.Event, register) -> None:
    from mcp import ClientSession, StdioServerParameters
    try:
        if spec.get("url"):
            from mcp.client.streamable_http import streamable_http_client
            transport = streamable_http_client(spec["url"])
        else:
            from mcp.client.stdio import stdio_client
            transport = stdio_client(StdioServerParameters(command=spec["command"], args=spec.get("args", []),
                                                           env=spec.get("env")))
        async with transport as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                listed = await session.list_tools()
                _sessions[name] = session
                for tool in listed.tools:
                    register(name, tool)
                ready.set()
                await asyncio.Event().wait()     # keep the connection open while TRON runs
    except Exception as exc:
        _errors[name] = f"{type(exc).__name__}: {exc}"
        ready.set()


def _text(result) -> str:
    parts = [getattr(c, "text", None) or f"[{getattr(c, 'type', 'content')}]" for c in (result.content or [])]
    body = "\n".join(parts)[:4000] or "(no output)"
    return ("the tool reported an error: " if result.is_error else "") + body


def call(server: str, tool: str, args: dict) -> str:
    session = _sessions.get(server)
    if session is None:
        return f"the {server} connection isn't available: {_errors.get(server, 'not connected')}"
    future = asyncio.run_coroutine_threadsafe(session.call_tool(tool, args or {}, read_timeout_seconds=60), _loop)
    return _text(future.result(timeout=90))


def start(servers: dict, timeout: float = 30) -> dict:
    """Connects to every configured server and registers its tools. Returns {server: "ok" or the error}."""
    global _loop
    import brain
    import tool_registry
    import tools

    def register(server, tool):
        name = _tool_name(server, tool.name)
        read_only = bool(tool.annotations and tool.annotations.read_only_hint)
        tools.TOOL_DECLARATIONS.append({
            "name": name, "description": f"[{server}] {(tool.description or tool.name)[:900]}",
            "parameters": tool.input_schema or {"type": "object", "properties": {}}})
        tools.TOOL_DISPATCH[name] = lambda args, cfg, s=server, t=tool.name: call(s, t, args)
        tool_registry.TOOLS[name] = tool_registry.ToolMeta(
            name, f"mcp:{server}", "READ" if read_only else "UPDATE", "none" if read_only else "medium",
            side_effect=not read_only, external=True, requires_confirmation=not read_only, timeout_seconds=90)
        if not read_only:
            brain.DESTRUCTIVE.add(name)

    _loop = asyncio.new_event_loop()
    threading.Thread(target=_loop.run_forever, daemon=True).start()
    waits = []
    for name, spec in (servers or {}).items():
        ready = asyncio.Event()
        asyncio.run_coroutine_threadsafe(_serve(name, spec, ready, register), _loop)
        waits.append((name, ready))
    for name, ready in waits:
        try:
            asyncio.run_coroutine_threadsafe(asyncio.wait_for(ready.wait(), timeout), _loop).result(timeout + 5)
        except Exception:
            _errors.setdefault(name, "timed out starting")
    return {name: "ok" if name in _sessions else _errors.get(name, "failed") for name, _ in waits}


def status() -> str:
    lines = [f"{n}: connected" for n in _sessions] + [f"{n}: {e}" for n, e in _errors.items() if n not in _sessions]
    return "\n".join(lines) or "No MCP servers configured."
