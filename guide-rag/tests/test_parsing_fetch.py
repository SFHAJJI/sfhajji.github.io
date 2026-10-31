"""The polite crawler: discovery, same origin, assets skipped, manifest, freshness, retry."""

from datetime import datetime, timedelta, timezone

from guide_rag.parsing.fetch import Fetcher, compare_manifests, is_fresh, load_manifest, sha256_of, slug_of
from tests.conftest import SITE, SiteHandler, make_fetcher


def test_crawl_discovers_pages_and_scripts_only_on_the_same_origin(tmp_path):
    handler = SiteHandler()
    manifest = make_fetcher(tmp_path, handler).crawl()
    paths = [r["path"] for r in manifest["resources"]]
    assert sorted(p for p in paths if p.endswith("/") or p == "/") == ["/", "/second/"]
    assert "/app/kb.js" in paths and "/app/styles.css" not in paths  # assets are not fetched
    assert all(u.startswith(SITE) for u in handler.requests)  # never leaves the origin
    assert handler.requests.count(SITE + "app/kb.js?v=1") == 1  # each script once, with its cache-buster
    assert (tmp_path / "index.html").exists() and (tmp_path / "second.html").exists() and (tmp_path / "app_kb.js").exists()
    assert manifest["pages_total"] == 2 and manifest["requests"] == len(handler.requests)


def test_manifest_records_hash_dates_and_status(tmp_path):
    manifest = make_fetcher(tmp_path, SiteHandler()).crawl()
    by_path = {r["path"]: r for r in manifest["resources"]}
    home = by_path["/"]
    assert home["http_status"] == 200 and home["kind"] == "html" and home["file"] == "index.html"
    assert home["content_sha256"] == sha256_of((tmp_path / "index.html").read_bytes())
    assert home["last_modified"].startswith("Mon, 26 Oct 2026") and home["fetched_at"].endswith("Z")
    assert by_path["/robots.txt"]["http_status"] == 404 and by_path["/robots.txt"]["file"] == ""
    assert by_path["/sitemap.xml"]["http_status"] == 200
    assert load_manifest(tmp_path) == manifest


def test_sitemap_pages_are_queued_and_foreign_locs_ignored(tmp_path):
    site = SiteHandler()
    site.site["/"] = (200, "text/html", "<html lang='fr'><body><h1>No links</h1></body></html>")
    manifest = make_fetcher(tmp_path, site).crawl()
    assert "/second/" in [r["path"] for r in manifest["resources"]]
    assert not any("elsewhere" in u for u in site.requests)


def test_politeness_delay_between_requests(tmp_path):
    waits: list[float] = []
    handler = SiteHandler()
    make_fetcher(tmp_path, handler, delay_s=1.0, sleep=waits.append).crawl()
    assert len(waits) >= len(handler.requests) - 1 and all(0 < w <= 1.0 for w in waits)


def test_max_pages_caps_the_crawl(tmp_path):
    site = SiteHandler()
    links = "".join(f'<a href="p{i}/">p{i}</a>' for i in range(10))
    site.site["/"] = (200, "text/html", f"<html><body>{links}</body></html>")
    for i in range(10):
        site.site[f"/p{i}/"] = (200, "text/html", f"<html><body><h1>p{i}</h1></body></html>")
    manifest = make_fetcher(tmp_path, site, max_pages=3).crawl()
    assert manifest["pages_total"] == 3


def test_transient_error_is_retried_once(tmp_path):
    waits: list[float] = []
    handler = SiteHandler(flaky={"/second/"})
    manifest = make_fetcher(tmp_path, handler, sleep=waits.append).crawl()
    second = next(r for r in manifest["resources"] if r["path"] == "/second/")
    assert second["http_status"] == 200 and handler.requests.count(SITE + "second/") == 2
    assert 2.0 in waits  # the retry pause


def test_robots_disallow_is_honoured(tmp_path):
    site = SiteHandler()
    site.site["/robots.txt"] = (200, "text/plain", "User-agent: *\nDisallow: /second/\n")
    manifest = make_fetcher(tmp_path, site).crawl()
    assert "/second/" not in [r["path"] for r in manifest["resources"]]


def test_is_fresh_checks_age_and_file_hashes(tmp_path):
    make_fetcher(tmp_path, SiteHandler()).crawl()
    ok, why = is_fresh(tmp_path, max_age_days=7)
    assert ok, why
    later = lambda: datetime.now(timezone.utc) + timedelta(days=8)
    assert is_fresh(tmp_path, max_age_days=7, now=later)[0] is False
    (tmp_path / "index.html").write_text("changed", encoding="utf-8")
    ok, why = is_fresh(tmp_path)
    assert not ok and "index.html" in why
    assert is_fresh(tmp_path / "nowhere")[0] is False


def test_clean_clone_is_not_fresh_and_refetch_verifies_the_manifest(tmp_path):
    """CI keeps raw/manifest.json but not the files: the build must refetch and compare."""
    previous = make_fetcher(tmp_path, SiteHandler()).crawl()
    for r in previous["resources"]:
        if r["file"]:
            (tmp_path / r["file"]).unlink()
    ok, why = is_fresh(tmp_path)
    assert not ok and "missing" in why
    current = make_fetcher(tmp_path, SiteHandler()).crawl()
    drift = compare_manifests(previous, current)
    assert drift["verified"] == ["/", "/app/kb.js", "/second/"] and not (drift["changed"] or drift["gone"] or drift["new"])


def test_drift_is_reported_when_the_site_changed(tmp_path):
    previous = make_fetcher(tmp_path, SiteHandler()).crawl()
    site = SiteHandler()
    site.site["/second/"] = (200, "text/html", "<html lang='en'><body><h1>Second page, revised</h1></body></html>")
    site.site["/third/"] = (200, "text/html", "<html><body><h1>Third</h1></body></html>")
    site.site["/"] = (200, "text/html", site.site["/"][2].replace('<a href="second/">', '<a href="third/">x</a><a href="second/">'))
    del site.site["/app/kb.js"]
    current = make_fetcher(tmp_path, site).crawl()
    drift = compare_manifests(previous, current)
    assert drift["gone"] == ["/app/kb.js"] and drift["new"] == ["/third/"]
    assert [d.split(" ")[0] for d in drift["changed"]] == ["/", "/second/"]
    assert compare_manifests(None, current) == {"verified": [], "changed": [], "gone": [], "new": []}


def test_slugs():
    assert slug_of("/") == "index" and slug_of("/prevoyance/") == "prevoyance"
    assert slug_of("/app/fiches/vehicule.js") == "app_fiches_vehicule.js" and slug_of("/a/index.html") == "a"
