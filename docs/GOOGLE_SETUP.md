# Connecting FRIDAY to Google (Gmail, Calendar, Meet)

**Using TRON:** open the control panel > **Settings > Google account** > **Sign in with Google** (or say "Friday,
connect Google"), pick your account and allow access. **Disconnect** there signs you out and cancels TRON's access
at Google.

**Building TRON to share it:** do the steps below once. When `google_client_secret.json` is in the repository root
at build time, `TRON.spec` builds it into TRON.exe, so the people you share it with only sign in. Git ignores the
file, so it never reaches GitHub. Until your Google app is published, add each person as a **test user**
(Audience > Test users). Published but unverified apps show a "Google hasn't verified this app" warning and allow
about 100 users; a public release needs Google's verification, and reading Gmail needs its yearly security
assessment as well.

## One-time setup (the developer)

It's free.

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
