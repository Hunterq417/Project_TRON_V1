# Connecting TRON to other apps, and what each setting does

All of these settings go in `config.json` (next to `TRON.exe`). Restart TRON after changing them.

## Any MCP server: Slack, Notion, GitHub, Home Assistant, …

```json
"mcp_servers": {
  "notion": {"command": "npx", "args": ["-y", "@notionhq/notion-mcp-server"], "env": {"NOTION_TOKEN": "ntn_..."}},
  "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
             "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..."}},
  "home":   {"url": "http://homeassistant.local:8123/mcp_server/sse"}
}
```

- Their tools show up as `notion__search`, `github__create_issue` and so on, in both brains.
- Tools a server marks read-only run straight away. Everything else needs your spoken yes.
- Check what connected with `python src\mcp_hub.py`, or read TRON's log.
- `npx` servers need [Node.js](https://nodejs.org).

## Recurring tasks

Just say it: "every weekday at 9, read me my unread mail", "every day at 11 pm, remind me to sleep",
"what are my recurring tasks?", "cancel the mail one". They're saved in `memory/schedules.json`.

## Response times (microseconds)

Every reply and tool call is timed into `logs/latency.jsonl`. To see the summary:

```
.venv\Scripts\python src\latency.py
```

## Phone

| Setting | What it does |
|---|---|
| `"announce_calls": true` (default) | announces calls from Phone Link and WhatsApp Desktop |
| `"announce_messages": false` (default) | set it to true to have messages announced too |
| `"ancs_address": "XX:XX:..."` | prototype: reads the iPhone directly over Bluetooth (see `src/ancs.py`) |
| `"hotspot_ssid": "iPhone"` | when the internet drops, joins your phone's hotspot (iPhone: Personal Hotspot > Allow Others to Join) |
