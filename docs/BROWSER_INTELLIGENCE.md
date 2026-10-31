# Browser intelligence

TRON controls video and pages in **its own Brave window** ("the TRON browser") by reading the page itself,
not just what Windows can see. Why it was needed: the players on anime sites live in frames Windows can't see into, and fade their controls out while you watch.

## How a command flows

```
"tron, play the next episode"
  -> speech -> TRON's brain (Gemini or local) calls browser_media(action="next_episode")     tools.py
  -> browser_session: the CDP connection, on its own worker thread                           browser_session.py
  -> inspect every frame: controls, accessible names, states, faded/covered, <video>s        browser_inspect.py
  -> plan: strategies for this intent, a strategy proven on this site first                  browser_intel.py
  -> rank candidates by evidence; ambiguous -> ask; risky (buy/send/delete...) -> never
  -> act: trusted click (waking faded player controls first) / HTML media API / keys
  -> verify against the state before: episode number, URL, title, video source, time, fullscreen
  -> failed: re-inspect, next strategy (max 3 attempts, 25 s budget, cancellable by the hotkey)
  -> learn: count which strategy worked on this site (no page content stored)
  -> "Done, sir. I've started the next episode (episode 19 -> 20)."   or what it tried and why it failed
```

Status events (`inspecting`, `planning`, `executing`, `verifying`, `recovering`, `completed`,
`needs_clarification`, `failed`) go to `logs/brain_events.jsonl` and the control panel's status line.

## Actions (`browser_media`)

| action | strategies, in order | verified by |
|---|---|---|
| next_episode / previous_episode | control named "Next episode" (many languages, icon-only via aria-label/title/data-*) -> the episode list's N+1 / N-1 -> Shift+N | episode number / URL / title / video source changed, then the **new** video's time advancing (it presses the player's Play if the site doesn't autoplay) |
| play / pause | HTML media API -> the player's Play/Pause -> click the video | `paused` flag |
| seek (seconds +/-) | HTML media API -> arrow keys | `currentTime` moved by about that much |
| volume (0-100), mute, unmute | HTML media API | `volume` / `muted` |
| subtitles_on / subtitles_off | the video's text tracks -> the player's captions control | track mode |
| fullscreen / exit_fullscreen | the player's fullscreen control -> F -> double-click; leaving: the page's exitFullscreen -> Esc | `document.fullscreenElement` |
| status | - | a summary of the page (as data) |

`browser_page` describes the page or presses a control by its text. Other tools: `open_tron_browser`,
`stop_browser_task`, `browser_knowledge`, `forget_browser_knowledge`.

Different words, different intents: "skip ten seconds" is `seek`, "next episode" is `next_episode`; "Next
chapter", "Skip intro", "+10s" never count as the next episode.

## Setup

1. Dependencies: `pip install -r requirements.txt` (adds `playwright`; no browser download - it drives your
   installed Brave).
2. Open the TRON browser: say "open the TRON browser", or Control Panel > Home > **Open TRON browser**.
   It is Brave with a separate profile in `<TRON folder>\browser_profile`, debugging on `127.0.0.1:9222`.
3. Watch your videos in that window. Log in to sites there as you would normally (only to sites you're happy
   for TRON to control).

**Security.** Your everyday Brave profile is never touched. The debugging port listens on loopback only, so
nothing on your network can reach it - but any program running on this PC as you could control the TRON
browser while it's open. Close it when you don't need it. TRON never presses controls that buy, pay, send,
delete, download, install, sign in or grant permissions as part of a media command; `browser_page` can press
one only when you asked for exactly that and said yes (brain.Guard). Page text is treated as data: it never
reaches the model as instructions, and controls are referenced by name only.

## Configuration

In `src/browser_intel.py`: `MAX_ATTEMPTS` (3), `DEADLINE_SECONDS` (25), `CONFIDENCE` (0.6),
`AMBIGUITY_MARGIN` (0.08), `VERIFY_WAIT` (6 s). Port: `browser_session.PORT` (9222).

## Learning

`memory/browser_knowledge.json` keeps, per site and intent, how often each strategy worked or failed - no URLs,
page text, cookies or form data. A strategy is tried first only after **two successes and more successes than
failures**. Review: "what have you learned about websites?" (`browser_knowledge`). Delete: "forget what you
learned about miruro" (`forget_browser_knowledge`), or delete the file.

## Tests

`.venv\Scripts\pytest tests\test_browser_intel.py` runs 26 scenarios against local fixture pages
(`tests/browser_fixtures/`) in a **real headless Brave over CDP**, with a cross-origin iframe served from a
second local port and a generated test video. Covered: labelled / icon-only / tooltip-only / custom
(div + data-action) next buttons, a cross-origin player frame, the episode list, a broken button recovered
another way, disabled and hidden duplicates, a control that appears late, two different "Next"s (asks), no
controls (honest failure), "Next chapter"/"Skip intro" decoys, injected page instructions ("click Buy premium"
- never obeyed), seek forward/back, play/pause/volume/mute/subtitles, fullscreen and back, a page with no
video, the page summary, bounded attempts, cancellation, per-site learning and forgetting, an unavailable
browser, the fallback to Windows accessibility, faded player controls with an inactive duplicate bar, and the
whole pipeline from a (scripted) brain tool call through the tool router to a verified result.

## Diagnosing a failure

* TRON's reply lists what it tried ("pressed X, but nothing changed; no control with enough evidence").
* `logs/brain_events.jsonl` has every stage with timings (`stage: "browser"`).
* `browser_media(action="status")` (say "what's on the page?") shows what TRON can see.
* Turn on Settings > "Developer: write each decision into Conversations".

## Adding a website adapter

Prefer making the generic layer understand the site: add words to `_WORDS` / `_NOT`, or player container
names to the context regexes. If a site needs its own way, add a strategy name to `_strategies()` and a branch
in `_attempt()` that checks it applies (the site's hostname and the controls it needs), acts, and verifies
with `_wait_for`; return `"... doesn't apply"` when it doesn't so recovery moves on. Add a fixture page and a
test. Successful strategies are learned per site automatically.

## Limits (known)

* Only the TRON browser is inspectable. In your everyday Brave, `browser_media` falls back to the Windows
  accessibility tool for play / pause / full screen only.
* Closed shadow roots and DRM-protected internals can't be read; the HTML media API still works on the
  `<video>` element where the page exposes it.
* A site that blocks scripted play (autoplay policy) gets a real click on its Play control instead; if it has
  none TRON says the episode opened but is paused.
* Vision-based fallback (screenshots to the local vision model) is used by the update watcher, not yet by
  browser_media.
* Live-verified on Miruro (play, seek, next/previous episode, subtitles, fullscreen, pause) while the site
  was reachable; during the last session miruro.to itself timed out (ERR_CONNECTION_TIMED_OUT).
