# How TRON, FRIDAY and JARVIS understand and carry out commands

All three run on one brain: Gemini Live (`gemini-3.1-flash-live-preview`) for hearing, thinking and speaking,
plus TRON's own tools, safety checks and memory. This page is the playbook they follow, what was researched to
make it reliable, and how to measure it.

## 1. The procedure (every request)

| Step | What happens | Where it's enforced |
|---|---|---|
| **Hear** | Rebuild what was meant from context, known names and sound-alikes ("drone" → TRON). Ask only if a *risky* action hangs on the unclear word. | `brain.COMMAND_MATRIX`; the user's dictionary words are given to Gemini (`dictation.vocab_hint`) |
| **Goal** | Work out the outcome wanted, not the literal words. | `COMMAND_MATRIX`, `HOUSE_RULES` |
| **Plan** | Most direct tool first. One-step tools beat open-and-click. A compound request is one plan, done end to end. | `COMMAND_MATRIX` |
| **Act** | No "shall I?" for safe actions. | `COMMAND_MATRIX` |
| **Check** | Read every tool result; one sensible retry; never claim success a tool didn't report. Stale screen items and blind typing are refused in code. | `computer.py` (stale-click and focus checks) |
| **Report** | One short sentence, in the user's language (Hindi, Hinglish, English). | `HOUSE_RULES` |

**Ask first only for:** sending mail or messages, inviting people, deleting or forgetting, shutdown/restart/sleep,
spending money, or a genuinely missing detail (an email address). Code enforces the risky ones
(`tool_registry` + `brain.Guard`), whatever the model decides.

## 2. The command matrix (what you say → what runs)

| You want | Tool |
|---|---|
| Open an app, file, folder, game | `open_target` |
| Open a website / new tab | `open_website` / `new_tab` |
| **Search a site, with any filters** (time, sort, remote, experience, price, posts/jobs/people) | **`search_site`**: builds the site's own search address with every filter, opens it in one step |
| Search the web generally | `web_search` |
| Switch to an app **or a browser tab** | `focus_app` (finds tabs by title) |
| Close / minimise / arrange | `close_app` / `minimize_app` / `window_action` |
| Music; browser video controls | `play_music`, `media_*`; `browser_media` |
| Volume, brightness, Wi-Fi/Bluetooth, dark mode, lock/sleep/shutdown | `set_volume`…, `set_brightness`, `set_radio`, `set_dark_mode`, `lock_pc`/`sleep_pc`/`shutdown_pc` (last two confirmed) |
| Timer / reminder; recurring task; the time | `set_timer`; `schedule_task`; `current_time` |
| Mail; calendar (FRIDAY) | `gmail_search`/`gmail_read`/`gmail_draft` → read back → `gmail_send` after yes; `calendar_events`/`calendar_create` |
| What's on screen; what is this object; who's here | `look_at_screen`; `identify_object`; `who_is_here` |
| Click or type on screen | `screen_elements` → `click_element` / `type_text` |
| The hidden-icons tray ("mini tray") | `show_hidden_icons` |
| Remember / forget; habits; dictation; another assistant; talk not for TRON | `remember_fact`/`forget_fact`; `my_routine`; `start_dictation`; `switch_assistant`; `not_for_me` |

`search_site` knows Google (news/images/videos, time), YouTube (time, sort), LinkedIn (jobs: time, experience,
remote/hybrid/on-site, job type, location, sort; posts: time, sort; people; companies), Amazon India and Flipkart
(price and rating sort), GitHub (language, repositories/code/issues, stars), Reddit, X, Maps, Wikipedia, Spotify,
and any other site through a Google search limited to it. A filter a site can't take is reported, never dropped
silently.

## 3. What the research found, and what was done about it

| Finding | Source | Done in TRON |
|---|---|---|
| Tool calling degrades deep into long conversations; reliability comes from well-designed tool schemas and a regression suite run before every prompt change | [Coval: Pipecat & Ultravox on instruction following](https://www.coval.ai/blog/the-state-of-voice-ai-instruction-following-in-2026-a-conversation-with-kwindla-from-pipecat-and-zach-from-ultravox), [Daily: advice on building voice AI](https://www.daily.co/blog/advice-on-building-voice-ai-in-june-2025/) | `tests/eval_commands.py`; one structured matrix instead of scattered rules |
| Test that each spoken request becomes the right tool with the right arguments, and that the agent reports the real result | [Cekura: function-calling tests for voice agents](https://www.cekura.ai/discover/function-calling-tool-use-testing-voice-agents), [Hamming: Pipecat regression testing](https://hamming.ai/blog/pipecat-bot-testing-automated-qa-regression) | The eval checks tool *and* arguments (filters, durations, recipients) |
| An interrupted or stale UI action can leave things half-done; make actions verifiable | [AAIF: where voice agents fail in production](https://aaif.io/blog/where-voice-agents-fail-in-production-part-2-tools-recovery-and-observability) | Stale-click and blind-typing refusals; URL-based search instead of clicking filters |
| Live sessions drop when the server resets the connection; resumption tokens rejoin the same session | [Gemini: session management](https://ai.google.dev/gemini-api/docs/live-api/session-management) | Session resumption: a 1006 drop or go-away rejoins the same conversation |
| Audio sessions end at ~15 minutes without context compression | [Gemini: session management](https://ai.google.dev/gemini-api/docs/live-api/session-management) | Sliding-window compression on |
| End-of-speech sensitivity and silence length are configurable | [Gemini Live capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities), [Vertex: configure language and voice](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api/configure-language-voice) | Low end-of-speech sensitivity, 600 ms: a pause mid-sentence no longer ends your turn |
| Proactive audio lets the model skip input that isn't relevant to it | [Vertex: proactive audio](https://cloud.google.com/vertex-ai/generative-ai/docs/live-api/proactive-audio) | On, together with `not_for_me` |
| Affective dialog (responding to tone) is a separate switch | [Vertex: configure Gemini capabilities](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api/configure-gemini-capabilities) | **Rejected by gemini-3.1-flash-live** (tested). The model is native audio and hears tone; the mood rule tells it how to act on it |

Every Gemini setting above was tested against your key and model on 2026-11-18 before being switched on.

## 4. Measuring it

```
.venv\Scripts\python tests\eval_commands.py              # with the matrix (what TRON uses)
.venv\Scripts\python tests\eval_commands.py --no-matrix  # without, for comparison
```

25 commands modelled on real ones from your conversation log: LinkedIn searches with filters, posts vs jobs,
timers, recurring tasks, mail, calendar, tabs, the mini tray, objects, Hinglish, talk meant for someone else,
"shut up". Each passes only if the right tool is chosen **with the right details**. It uses a text Gemini model
with TRON's real tools and instructions, so it measures understanding, not hearing. Run it after any change to
the instructions; add a case whenever TRON gets something wrong.

**Scores:** not recorded yet. The first runs (21 Nov 2026) didn't finish on a slow connection where single Gemini requests took 30+ seconds. Run it on a normal connection; a full run takes about 3–5 minutes.

## 5. What would make it better still (ranked)

1. **Grow the eval from real mistakes.** Every time TRON misunderstands, add that sentence to `CASES`.
   Production voice teams treat this regression suite as the main quality lever.
2. **More one-step tools for frequent workflows.** Each multi-click routine you repeat (apply on LinkedIn,
   reply on WhatsApp Web, book on a site) is more reliable as a dedicated tool, or a skill, than as live clicking.
3. **A computer-use model for unknown sites.** For a site TRON has no tool for, Gemini's computer-use model
   (screenshot → action loop) handles arbitrary filters and forms better than element lists. It's slower and
   costs more per task, so it's best as a fallback.
4. **A trained "is this for me?" detector** (your voice + gaze + words), if `not_for_me` plus proactive audio
   still misjudge. Needs about two hours of your labelled audio.
5. **A paid Gemini tier** if quotas bite: the free tier rate-limits the eval and refuses Google Search grounding
   at times.
