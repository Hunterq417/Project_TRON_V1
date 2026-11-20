# tests/eval_commands.py
"""Command-understanding eval: does Gemini, given TRON's real tools and instructions, pick the right action with
the right details? Not part of pytest (it calls the Gemini API). Run:

    .venv\\Scripts\\python tests\\eval_commands.py              with the command matrix (what TRON uses)
    .venv\\Scripts\\python tests\\eval_commands.py --no-matrix  without it, for comparison

Uses a text Gemini model with the same declarations TRON sends to Gemini Live, so it measures understanding and
tool choice, not hearing. Each case: (what the user says, accepted first tools, a check on the arguments).
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import brain   # noqa: E402
import tools   # noqa: E402

F = lambda a: a.get("filters") or {}
CASES = [
    ("open spotify", {"open_target"}, lambda a: "spotify" in str(a).lower()),
    ("search linkedin for founder's office internships, remote, posted this week", {"search_site"},
     lambda a: "linkedin" in a.get("site", "").lower() and F(a).get("workplace") == "remote" and F(a).get("time") == "week"
     and "internship" in (F(a).get("experience", "") + F(a).get("job_type", "") + a.get("query", "")).lower()),
    ("find #hiring founder's office posts on linkedin", {"search_site"},
     lambda a: F(a).get("kind", "").startswith("post") and "hiring" in a.get("query", "")),
    ("play some karan aujla", {"play_music"}, lambda a: "aujla" in str(a).lower()),
    ("set a timer for 15 minutes", {"set_timer"}, lambda a: int(float(a.get("seconds", 0))) == 900),
    ("every weekday at 9 in the morning read me my unread mail", {"schedule_task"},
     lambda a: a.get("time") in ("09:00", "9:00") and "weekday" in a.get("days", "").lower()),
    ("what's in my inbox", {"gmail_search"}, lambda a: True),
    ("what's on my calendar tomorrow", {"calendar_events"}, lambda a: True),
    ("close the omen gaming hub", {"close_app"}, lambda a: "omen" in str(a).lower()),
    ("go back to the linkedin tab", {"focus_app"}, lambda a: "linkedin" in str(a).lower()),
    ("open the mini tray", {"show_hidden_icons"}, lambda a: True),
    ("what is this thing I'm holding", {"identify_object"}, lambda a: a.get("source", "camera") == "camera"),
    ("turn the volume down a bit", {"change_volume", "set_volume"}, lambda a: True),
    ("switch to jarvis", {"switch_assistant"}, lambda a: a.get("name") == "jarvis"),
    ("[the user, to a friend in the room] bhai pani pass kar de", {"not_for_me", None}, lambda a: True),
    ("shut up", {None}, lambda a: True),
    ("remember that my favourite code editor is VS Code", {"remember_fact"}, lambda a: "vs code" in str(a).lower()),
    ("search amazon for wireless earbuds, cheapest first", {"search_site"},
     lambda a: "amazon" in a.get("site", "").lower() and F(a).get("sort") == "price_low"),
    ("youtube pe valorant ke latest videos dikhao", {"search_site"},
     lambda a: "youtube" in a.get("site", "").lower() and (F(a).get("sort") == "recent" or F(a).get("time"))),
    ("next episode", {"browser_media"}, lambda a: a.get("action") == "next_episode"),
    ("what time is it", {"current_time"}, lambda a: True),
    ("write an email to mayukh@example.com saying I'll join tomorrow's meeting", {"gmail_draft", "draft_email"},
     lambda a: "mayukh@example.com" in str(a)),
    ("turn on dark mode", {"set_dark_mode"}, lambda a: True),
    ("take a dictation", {"start_dictation"}, lambda a: True),
    ("search github for python voice assistant repos sorted by stars", {"search_site"},
     lambda a: "github" in a.get("site", "").lower() and F(a).get("sort") in ("stars", "popular")),
]


def main():
    from google import genai
    from google.genai import types
    use_matrix = "--no-matrix" not in sys.argv
    cfg = json.loads((ROOT / "dist" / "config.json").read_text(encoding="utf-8-sig"))
    client = genai.Client(api_key=cfg["gemini_api_key"])
    declarations = [d for d in tools.TOOL_DECLARATIONS] + [tools.objects.DECLARATION]
    tool = types.Tool(function_declarations=[types.FunctionDeclaration(
        name=d["name"], description=d["description"], parameters=d.get("parameters")) for d in declarations])
    system = "\n\n".join(filter(None, [(ROOT / "persona.txt").read_text(encoding="utf-8"),
                                       brain.COMMAND_MATRIX if use_matrix else "", brain.HOUSE_RULES]))
    config = types.GenerateContentConfig(system_instruction=system, tools=[tool], temperature=0.2,
                                         automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    passed, rows = 0, []
    for said, accepted, check in CASES:
        reply = None
        for model in ("gemini-flash-latest", "gemini-flash-lite-latest"):
            for attempt in range(3):
                try:
                    reply = client.models.generate_content(model=model, contents=said, config=config)
                    break
                except Exception as exc:
                    if not any(c in str(exc) for c in ("429", "503", "UNAVAILABLE")):
                        raise
                    time.sleep(8 * (attempt + 1))
            if reply is not None:
                break
        calls = [p.function_call for c in (reply.candidates or [])[:1] for p in (c.content.parts or []) if p.function_call]
        name, args = (calls[0].name, dict(calls[0].args or {})) if calls else (None, {})
        ok = name in accepted and (name is None or check(args))
        passed += ok
        rows.append(f"{'PASS' if ok else 'FAIL'}  {said[:60]:60}  -> {name}({json.dumps(args, ensure_ascii=False)[:90]})")
        time.sleep(4)   # stay under the free tier's per-minute limit
    print("\n".join(rows))
    print(f"\n{'with' if use_matrix else 'without'} command matrix: {passed}/{len(CASES)} correct "
          f"({100 * passed // len(CASES)}%)")


if __name__ == "__main__":
    main()
