# site_search.py
"""search_site: "search LinkedIn for founder's office internships, remote, posted this week" in one step.

Clicking through a site's filter menus is the fragile part of browser control (a redrawn LinkedIn page once sent
a click and an Enter to the wrong tab). Every site here takes its search and filters in the web address, so TRON
builds that address and opens it: no clicks, nothing to go stale. A filter a site can't take is reported, never
silently dropped; an unknown site becomes a Google search limited to that site.
"""
from urllib.parse import quote, quote_plus, urlencode

import desktop_control

_LI_TIME = {"hour": "r3600", "day": "r86400", "week": "r604800", "month": "r2592000"}
_LI_POST_TIME = {"day": "past-24h", "week": "past-week", "month": "past-month"}
_LI_LEVEL = {"internship": "1", "entry": "2", "associate": "3", "mid": "4", "senior": "4", "director": "5",
             "executive": "6"}
_LI_WORKPLACE = {"onsite": "1", "remote": "2", "hybrid": "3"}
_LI_JOB_TYPE = {"full-time": "F", "part-time": "P", "contract": "C", "temporary": "T", "internship": "I"}
_YT = {("time", "hour"): "EgIIAQ%3D%3D", ("time", "day"): "EgIIAg%3D%3D", ("time", "week"): "EgIIAw%3D%3D",
       ("time", "month"): "EgIIBA%3D%3D", ("time", "year"): "EgIIBQ%3D%3D", ("sort", "recent"): "CAI%3D",
       ("sort", "popular"): "CAM%3D", ("sort", "rating"): "CAE%3D"}


def build(site: str, query: str, f: dict):
    """(url, applied filters, ignored filters). f: time, sort, kind, location, experience, workplace, job_type,
    language - each optional, in plain words."""
    raw = {k: str(v).strip() for k, v in (f or {}).items() if v}
    site, used, f = site.lower().strip(), [], {k: v.lower() for k, v in raw.items()}   # lower for matching only
    take = lambda key, table: (used.append(key), table[f[key]])[1] if f.get(key) in table else None
    q = quote_plus(query)

    if "linkedin" in site:
        kind = f.get("kind", "jobs")
        used.append("kind") if "kind" in f else None
        if kind.startswith("post"):
            params = {"keywords": query, "datePosted": take("time", _LI_POST_TIME),
                      "sortBy": {"recent": "date_posted", "relevant": "relevance"}.get(f.get("sort"))}
            used.append("sort") if f.get("sort") in ("recent", "relevant") else None
            params = {k: (f'"{v}"' if k != "keywords" else v) for k, v in params.items() if v}
            url = "https://www.linkedin.com/search/results/content/?" + urlencode(params)
        elif kind.startswith(("people", "person")) or kind.startswith("compan"):
            path = "people" if kind.startswith(("people", "person")) else "companies"
            url = f"https://www.linkedin.com/search/results/{path}/?keywords={q}"
        else:
            params = {"keywords": query, "location": raw.get("location"), "f_TPR": take("time", _LI_TIME),
                      "f_E": take("experience", _LI_LEVEL), "f_WT": take("workplace", _LI_WORKPLACE),
                      "f_JT": take("job_type", _LI_JOB_TYPE),
                      "sortBy": {"recent": "DD", "relevant": "R"}.get(f.get("sort"))}
            used += [k for k in ("location",) if f.get(k)] + (["sort"] if f.get("sort") in ("recent", "relevant") else [])
            url = "https://www.linkedin.com/jobs/search/?" + urlencode({k: v for k, v in params.items() if v})
    elif "youtube" in site:
        sp = next((code for (key, value), code in _YT.items() if f.get(key) == value and not used.append(key)), None)
        url = f"https://www.youtube.com/results?search_query={q}" + (f"&sp={sp}" if sp else "")
    elif "amazon" in site:
        sort = take("sort", {"price_low": "price-asc-rank", "price_high": "price-desc-rank", "rating": "review-rank",
                             "recent": "date-desc-rank"})
        url = f"https://www.amazon.in/s?k={q}" + (f"&s={sort}" if sort else "")
    elif "flipkart" in site:
        sort = take("sort", {"price_low": "price_asc", "price_high": "price_desc", "recent": "recency_desc",
                             "popular": "popularity"})
        url = f"https://www.flipkart.com/search?q={q}" + (f"&sort={sort}" if sort else "")
    elif "github" in site:
        lang = f" language:{f['language']}" if f.get("language") and not used.append("language") else ""
        kind = take("kind", {"repositories": "repositories", "repos": "repositories", "code": "code",
                             "issues": "issues", "users": "users"}) or "repositories"
        sort = take("sort", {"popular": "&s=stars&o=desc", "stars": "&s=stars&o=desc", "recent": "&s=updated&o=desc"})
        url = f"https://github.com/search?q={quote_plus(query + lang)}&type={kind}" + (sort or "")
    elif "reddit" in site:
        sort = take("sort", {"recent": "new", "popular": "top", "relevant": "relevance"})
        t = take("time", {"hour": "hour", "day": "day", "week": "week", "month": "month", "year": "year"})
        url = f"https://www.reddit.com/search/?q={q}" + (f"&sort={sort}" if sort else "") + (f"&t={t}" if t else "")
    elif site in ("x", "twitter") or "twitter" in site or site == "x.com":
        mode = take("sort", {"recent": "live", "popular": "top"})
        url = f"https://x.com/search?q={q}" + (f"&f={mode}" if mode else "")
    elif "map" in site:
        url = f"https://www.google.com/maps/search/{quote(query)}"
    elif "wiki" in site:
        url = f"https://en.wikipedia.org/w/index.php?search={q}"
    elif "spotify" in site:
        url = f"https://open.spotify.com/search/{quote(query)}"
    else:   # Google itself, or any other site: a Google search limited to it
        scope = "" if site in ("", "google", "web") else f" site:{site if '.' in site else site + '.com'}"
        tbm = take("kind", {"news": "nws", "images": "isch", "videos": "vid"})
        tbs = take("time", {"hour": "qdr:h", "day": "qdr:d", "week": "qdr:w", "month": "qdr:m", "year": "qdr:y"})
        url = (f"https://www.google.com/search?q={quote_plus(query + scope)}" + (f"&tbm={tbm}" if tbm else "")
               + (f"&tbs={tbs}" if tbs else ""))
    ignored = [f"{k}={v}" for k, v in f.items() if k not in used and not (k == "kind" and v == "jobs")]
    return url, [f"{k}={f[k]}" for k in dict.fromkeys(used) if k in f], ignored


def search_site(args, cfg=None) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "what should I search for, sir?"
    url, applied, ignored = build(str(args.get("site", "google")), query, args.get("filters") or {})
    opened = desktop_control.open_website({"url": url, "browser": args.get("browser", "")}, cfg)
    if not opened.startswith("opened"):
        return opened
    note = f" with {', '.join(applied)}" if applied else ""
    skipped = f". This site can't filter by {', '.join(ignored)} from the address; say so" if ignored else ""
    return f"{opened.removesuffix(', sir')}: searched for {query!r}{note}{skipped}"


DECLARATION = {
    "name": "search_site",
    "description": "Search a website WITH filters in one step, by opening its search address (no clicking): Google, "
                   "YouTube, LinkedIn (jobs, posts, people, companies), Amazon, Flipkart, GitHub, Reddit, X, Maps, "
                   "Wikipedia, Spotify, or any site (Google, limited to it). Prefer this over open_website plus clicks "
                   "for any 'search X for Y' request, and put every filter the user said into filters.",
    "parameters": {"type": "object", "properties": {
        "site": {"type": "string", "description": "e.g. linkedin, youtube, amazon, google, github, or a domain"},
        "query": {"type": "string", "description": "the search words only, without the filters"},
        "filters": {"type": "object", "description": "only the ones the user asked for", "properties": {
            "kind": {"type": "string", "description": "linkedin: jobs|posts|people|companies; google: news|images|videos; github: repositories|code|issues|users"},
            "time": {"type": "string", "enum": ["hour", "day", "week", "month", "year"]},
            "sort": {"type": "string", "enum": ["recent", "relevant", "popular", "rating", "price_low", "price_high", "stars"]},
            "location": {"type": "string"},
            "experience": {"type": "string", "enum": ["internship", "entry", "associate", "mid", "senior", "director", "executive"]},
            "workplace": {"type": "string", "enum": ["onsite", "remote", "hybrid"]},
            "job_type": {"type": "string", "enum": ["full-time", "part-time", "contract", "temporary", "internship"]},
            "language": {"type": "string", "description": "programming language, for github"}}},
        "browser": {"type": "string", "description": "only if the user named one"}},
        "required": ["site", "query"]},
}
