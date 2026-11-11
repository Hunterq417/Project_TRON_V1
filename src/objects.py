# objects.py
"""identify_object: "what is this?" held up to the camera (or on the screen), answered in detail.

The picture goes to Gemini's vision model with Google Search turned on, so it can read labels and logos,
name the exact product and model, and look up its specs and typical price instead of guessing. The live
conversation then says the answer. Needs the internet and the Gemini key; the camera or screen permission
in Settings must be on, the same as look_via_camera / look_at_screen.
"""
MODEL = "gemini-flash-latest"        # Google's alias for its current Flash model: vision + search grounding
LITE = "gemini-flash-lite-latest"    # lighter fallback when Flash is overloaded
PROMPT = """Identify what is in this picture{focus}. Be specific and accurate; it's {who} asking.

For the main object (or each one, if they asked about several):
- What it is: the most specific name you can justify (brand, product, model or species), and how sure you are.
- How you know: the labels, logos, shapes or text that gave it away.
- Details: what it does or is used for, key specifications, materials, size, condition, colour or variant.
- Useful extras when they apply: typical price (in INR if it's a product sold in India, else USD), where it's
  made, how to use or care for it, safety notes, or for food: what's in it.
Use Google Search, when it's available, to confirm the model and specs. If you can't tell exactly, say what it most likely is and what
would settle it (e.g. "turn it so I can see the label"). Never invent a model number. Plain sentences, under 180
words, no markdown."""


def identify_object(args, cfg=None) -> str:
    source = str((args or {}).get("source", "camera")).lower()
    question = str((args or {}).get("question", "")).strip()
    if source == "screen" and not getattr(cfg, "screen_enabled", False):
        return "screen access is switched off in Settings, sir"
    if source != "screen" and not getattr(cfg, "camera_enabled", False):
        return "the camera is switched off in Settings, sir"
    key = getattr(cfg, "gemini_api_key", "") or ""
    if not key or "YOUR_" in key:
        return "identifying objects needs the Gemini key (Settings > Keys), sir"
    import perception
    try:
        jpeg = perception.capture_screen_jpeg() if source == "screen" else perception.capture_camera_jpeg()
    except Exception as exc:
        return f"I couldn't take the picture: {exc}, sir"
    return describe(jpeg, question, key)


def describe(jpeg: bytes, question: str, key: str, client=None) -> str:
    from google import genai
    from google.genai import types
    client = client or genai.Client(api_key=key)
    prompt = PROMPT.format(focus=f' ("{question}")' if question else "", who="the user")
    contents = [types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"), prompt]
    search = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
    # Search grounding has its own quota (none left on a free key at times), and Flash is sometimes overloaded:
    # then the model's own knowledge, then the lighter model. Any other error is reported, not retried.
    failure = None
    for model, config in ((MODEL, search), (MODEL, None), (LITE, None)):
        try:
            reply = client.models.generate_content(model=model, contents=contents, config=config)
            return (reply.text or "").strip() or "I couldn't make out anything clearly, sir. Try better light."
        except Exception as exc:
            failure = exc
            if not any(code in str(exc) for code in ("429", "503", "UNAVAILABLE")):
                break
    return f"the vision lookup failed ({type(failure).__name__}: {str(failure)[:120]}), sir"


DECLARATION = {
    "name": "identify_object",
    "description": "Identify what the user is holding up or pointing at, in detail: exact product/model or "
                   "species, how you can tell, specs, use, price, care. Use for 'what is this', 'tell me about "
                   "this', 'what model is this'. source 'screen' for something on the screen. Say 'let me take "
                   "a look' first; then relay the answer naturally.",
    "parameters": {"type": "object", "properties": {
        "question": {"type": "string", "description": "what they want to know, in their words"},
        "source": {"type": "string", "enum": ["camera", "screen"]}}},
}
