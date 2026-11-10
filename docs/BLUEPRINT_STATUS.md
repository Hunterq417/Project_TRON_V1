# TRON master blueprint: status

Compared against `TRON_MASTER_BLUEPRINT.md` and `claude_master_instructions_md.md` (1 Nov 2026). The iOS bridge is
deferred on purpose. DONE means code plus tests; the suite is 451 passed, 1 skipped.

| Requirement | Status | Where |
|---|---|---|
| One brain, three personas (TRON, FRIDAY, JARVIS) with shared memory and tools | DONE | `config.DEFAULT_ASSISTANTS`, `persona.txt`, `personas/` |
| Switch by voice ("switch to Friday", "Jarvis, take over") or from the panel; applies from the next conversation without a restart | DONE | `tools._switch_assistant`, `state_manager._load_assistant` |
| Per-persona voice: Gemini (Orus / Aoede / Charon) and local (David / Zira / David) | DONE | `config._apply_assistant` |
| One-off opinion from another persona, without switching | DONE (by instruction) | `switch_assistant` description |
| "hey jarvis" wake word | DONE | `wake_trigger.persona_wake_models` |
| "hey friday" wake word | PARTIAL | loads `models/hey_friday.onnx` once trained (docs/train_wakeword.md) |
| Provider abstraction: Gemini and Ollama behind TRON's own tool registry, guard and memory | PARTIAL | `gemini_live_client.py`, `local_brain.py`; no shared `ModelProvider` interface, the two brains are separate loops |
| Local-only mode (nothing sent to the cloud) | DONE | `brain: local` |
| Offline fallback when Gemini can't be reached | DONE | `offline.py` |
| Risk levels and confirmation enforced in code, not by the model | DONE | `tool_registry.py`, `brain.Guard` |
| Email: draft, read back, explicit yes, then send | DONE | `email_client.py`, `persona.txt` |
| Memory with provenance, scored retrieval, gated learning, forget guard, pause (memory_enabled) | DONE | `memory.py`, `memory_service.py` |
| Routine learning: inferred only after 3 different days, labelled as an inference, paused with learning, deletable | DONE | `routine.py` (`my_routine`, `forget_routine`) |
| Routine confirmation step (user confirms an inferred habit) | MISSING | |
| Reminders and timers persist across restarts | DONE | `timers.py` with `memory/timers.json` |
| Recurring automations / scheduler with quiet hours | MISSING | |
| Calendar integration | MISSING | needs Google or Outlook OAuth |
| Skills the user teaches (SKILL.md routines) | DONE | `skills.py` |
| Self-written code skills (sandbox, tests, approval, rollback) | MISSING, by design | the blueprint forbids unreviewed generated code; needs a sandbox first |
| Audit log of tool calls and decisions | PARTIAL | `logs/brain_events.jsonl` covers the local brain only |
| Offline queue for actions that need the internet | MISSING | |
| iOS bridge | DEFERRED | |

**Next suggested step:** a recurring-automation scheduler (persisted like the timers), or the "hey friday" and
"hey jarvis" wake models.
