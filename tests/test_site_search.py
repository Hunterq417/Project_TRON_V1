import site_search


def test_linkedin_jobs_with_every_filter_in_the_address():
    url, applied, ignored = site_search.build("LinkedIn", "founder's office", {
        "time": "week", "experience": "internship", "workplace": "remote", "location": "Delhi", "sort": "recent"})
    assert url.startswith("https://www.linkedin.com/jobs/search/?keywords=founder%27s+office")
    for part in ("f_TPR=r604800", "f_E=1", "f_WT=2", "location=Delhi", "sortBy=DD"):
        assert part in url
    assert ignored == []


def test_linkedin_posts_are_not_jobs():
    url, _a, ignored = site_search.build("linkedin", "#hiring founder's office", {"kind": "posts", "time": "day"})
    assert url.startswith("https://www.linkedin.com/search/results/content/?")
    assert "datePosted=%22past-24h%22" in url and ignored == []


def test_filters_a_site_cannot_take_are_reported_not_dropped():
    url, _a, ignored = site_search.build("wikipedia", "Mount Everest", {"time": "week"})
    assert "wikipedia.org" in url and ignored == ["time=week"]


def test_shopping_youtube_github_and_unknown_sites():
    assert "s=price-asc-rank" in site_search.build("amazon", "earbuds", {"sort": "price_low"})[0]
    assert "sp=EgIIAw%3D%3D" in site_search.build("youtube", "valorant", {"time": "week"})[0]
    url = site_search.build("github", "voice assistant", {"language": "python", "sort": "stars"})[0]
    assert "language%3Apython" in url and "s=stars" in url
    assert "site%3Ainternshala.com" in site_search.build("internshala", "founder's office", {})[0]


def test_search_site_opens_the_address(monkeypatch):
    opened = []
    monkeypatch.setattr(site_search.desktop_control, "open_website",
                        lambda args, cfg=None: opened.append(args["url"]) or "opened linkedin.com, sir")
    reply = site_search.search_site({"site": "linkedin", "query": "data analyst", "filters": {"workplace": "remote"}})
    assert "f_WT=2" in opened[0] and "workplace=remote" in reply
