# Connecting FRIDAY to Google (Gmail, Calendar, Meet)

You do this once. It's free.

1. Go to https://console.cloud.google.com/ and create a project, for example "TRON".
2. Under **APIs & Services > Library**, enable the **Gmail API** and the **Google Calendar API**.
3. Under **APIs & Services > OAuth consent screen**, choose External, fill in the app name and your email, and
   add your own Google address as a **test user**.
4. Under **APIs & Services > Credentials**, choose **Create credentials > OAuth client ID > Desktop app**, then
   download the JSON file.
5. Rename the file to `google_client_secret.json` and put it next to `TRON.exe`, or in the repository root
   when running from source. Git ignores it.
6. Say "Friday, connect Google". A browser window opens: sign in and allow access. The sign-in is saved in
   `memory/google_token.json`, so you only do this once.

What FRIDAY can then do:

| Tool | What it does | Asks before doing it? |
|---|---|---|
| `gmail_search`, `gmail_read` | find and summarise mail | no |
| `gmail_draft` | save a draft in Gmail | no |
| `gmail_send` | send mail | yes, after reading the mail back to you |
| `calendar_events` | what's on | no |
| `calendar_create` | add an event, optionally with a Meet link and invitations | yes |

**Use it from other apps.** The same tools are a single MCP server: `.venv\Scripts\python src\google_mcp.py`
(stdio). Add it to any MCP client (Claude Desktop, Claude Code, …) as a command server.
