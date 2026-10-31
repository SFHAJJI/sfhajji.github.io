"""Fetch the site politely into ``raw/`` and keep a manifest of what was fetched.

Discovery: the home page's links and ``sitemap.xml`` if present, then the links of every page
reached, same origin only, assets skipped, at most ``MAX_PAGES`` pages. The site's data
scripts (every same-origin ``<script src>``) are fetched too, because this site keeps its
content in them; they are parsed later from their raw text, never executed.

Politeness: one request per second, one retry on a transient error, a User-Agent that names
the repository, ``robots.txt`` honoured. Every byte fetched is stored under ``raw/`` with its
sha256 so that the build is reproducible from the files alone.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from .. import PIPELINE_VERSION

USER_AGENT = "guide-rag/0.1 (+https://github.com/SFHAJJI/guide-rag)"
SITE_URL = "https://lux-guide.github.io/"
MAX_PAGES = 60
DELAY_S = 1.0
RETRY_WAIT_S = 2.0
MANIFEST_NAME = "manifest.json"

# Linked files that are not pages. Scripts are discovered through <script src>, not links.
ASSET_SUFFIXES = (
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".pdf", ".woff",
    ".woff2", ".ttf", ".mp4", ".zip", ".json", ".txt", ".xml", ".geojson", ".csv",
)


@dataclass
class Resource:
    """One fetched URL, as recorded in the manifest."""

    url: str
    path: str  # the site path, query and fragment removed
    kind: str  # html | script | sitemap | robots
    file: str  # file name under raw/, empty when nothing was stored
    content_sha256: str
    fetched_at: str
    last_modified: str
    http_status: int
    bytes: int
    error: str = ""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slug_of(path: str) -> str:
    """``/`` → ``index``, ``/prevoyance/`` → ``prevoyance``, ``/app/kb.js`` → ``app_kb.js``."""
    p = path.strip("/")
    if not p:
        return "index"
    if p.endswith(".html"):
        p = p[:-5]
    if p.endswith("/index"):
        p = p[:-6]
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", p.replace("/", "_")) or "index"


def file_name_for(path: str, kind: str) -> str:
    slug = slug_of(path)
    if kind == "html":
        return f"{slug}.html"
    if kind == "script":
        return slug if slug.endswith(".js") else f"{slug}.js"
    return slug


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Fetcher:
    """Crawl one site into ``raw_dir``. ``client``, ``sleep`` and ``now`` are injectable for tests."""

    def __init__(
        self,
        raw_dir: Path,
        site_url: str = SITE_URL,
        max_pages: int = MAX_PAGES,
        delay_s: float = DELAY_S,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = utc_now,
        log: Callable[[str], None] | None = None,
    ):
        self.raw_dir = Path(raw_dir)
        self.site_url = site_url if site_url.endswith("/") else site_url + "/"
        self.site = urlsplit(self.site_url)
        self.max_pages = max_pages
        self.delay_s = delay_s
        self.client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30.0)
        self.sleep = sleep
        self.now = now
        self.log = log or (lambda msg: None)
        self._last_request: float | None = None
        self.requests = 0
        self.disallowed: list[str] = []
        self.resources: list[Resource] = []

    # ----- one request -----

    def get(self, url: str) -> tuple[httpx.Response | None, str]:
        """One polite GET: at least ``delay_s`` after the previous one, one retry on failure."""
        last_error = ""
        for attempt in (1, 2):
            if self._last_request is not None:
                wait = self.delay_s - (time.monotonic() - self._last_request)
                if wait > 0:
                    self.sleep(wait)
            self._last_request = time.monotonic()
            self.requests += 1
            try:
                resp = self.client.get(url)
            except httpx.HTTPError as exc:  # transport errors, timeouts
                last_error = f"{type(exc).__name__}: {exc}"
                resp = None
            if resp is not None and resp.status_code < 500:
                return resp, ""
            if resp is not None:
                last_error = f"HTTP {resp.status_code}"
            if attempt == 1:
                self.log(f"retrying {url} after {last_error}")
                self.sleep(RETRY_WAIT_S)
        return None, last_error

    def _store(self, url: str, kind: str, resp: httpx.Response | None, error: str) -> Resource:
        path = urlsplit(url).path or "/"
        fetched_at = iso(self.now())
        if resp is None:
            res = Resource(url, path, kind, "", "", fetched_at, "", 0, 0, error)
        else:
            file = file_name_for(path, kind) if resp.status_code == 200 and kind in ("html", "script") else ""
            if file:
                self.raw_dir.mkdir(parents=True, exist_ok=True)
                (self.raw_dir / file).write_bytes(resp.content)
            res = Resource(
                url=url,
                path=path,
                kind=kind,
                file=file,
                content_sha256=sha256_of(resp.content) if resp.status_code == 200 else "",
                fetched_at=fetched_at,
                last_modified=resp.headers.get("last-modified", ""),
                http_status=resp.status_code,
                bytes=len(resp.content),
                error=error,
            )
        self.resources.append(res)
        self.log(f"{res.http_status or 'ERR'} {kind:7s} {url}")
        return res

    # ----- discovery -----

    def _same_origin(self, url: str) -> bool:
        u = urlsplit(url)
        return u.scheme in ("http", "https") and u.netloc == self.site.netloc

    def _page_url(self, base: str, href: str) -> str | None:
        """A crawlable page URL for ``href``, or None (external, asset, fragment-only, disallowed)."""
        href = href.strip()
        if not href or href.startswith("#") or href.startswith(("mailto:", "tel:", "javascript:")):
            return None
        u = urlsplit(urljoin(base, href))
        if not self._same_origin(urlunsplit(u)):
            return None
        path = u.path or "/"
        if path.lower().endswith(ASSET_SUFFIXES):
            return None
        if any(path.startswith(d) for d in self.disallowed):
            return None
        return urlunsplit((u.scheme, u.netloc, path, "", ""))

    def _robots(self) -> None:
        resp, error = self.get(urljoin(self.site_url, "/robots.txt"))
        self._store(urljoin(self.site_url, "/robots.txt"), "robots", resp, error)
        if resp is None or resp.status_code != 200:
            return
        applies = False
        for raw in resp.text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, value = (x.strip() for x in line.split(":", 1))
            if key.lower() == "user-agent":
                applies = value == "*" or "guide-rag" in value.lower()
            elif key.lower() == "disallow" and applies and value:
                self.disallowed.append(value)

    def _sitemap(self) -> list[str]:
        url = urljoin(self.site_url, "/sitemap.xml")
        resp, error = self.get(url)
        self._store(url, "sitemap", resp, error)
        if resp is None or resp.status_code != 200:
            return []
        found = []
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", resp.text):
            page = self._page_url(self.site_url, loc)
            if page:
                found.append(page)
        return found

    # ----- the crawl -----

    def crawl(self) -> dict:
        """Fetch the pages and their scripts; write and return the manifest."""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._robots()
        queue = [self.site_url]
        seen = {self.site_url}
        for page in self._sitemap():
            if page not in seen:
                seen.add(page)
                queue.append(page)
        scripts: dict[str, str] = {}  # path → first url seen (its cache-buster query kept)
        n_pages = 0
        while queue and n_pages < self.max_pages:
            url = queue.pop(0)
            resp, error = self.get(url)
            res = self._store(url, "html", resp, error)
            n_pages += 1
            if resp is None or resp.status_code != 200 or "html" not in resp.headers.get("content-type", "html"):
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.find_all("a", href=True):
                page = self._page_url(url, a["href"])
                if page and page not in seen:
                    seen.add(page)
                    queue.append(page)
            for s in soup.find_all("script", src=True):
                full = urljoin(url, s["src"].strip())
                if self._same_origin(full):
                    scripts.setdefault(urlsplit(full).path, full)
        for path, url in sorted(scripts.items()):
            resp, error = self.get(url)
            self._store(url, "script", resp, error)
        manifest = self.manifest()
        write_manifest(self.raw_dir, manifest)
        return manifest

    def manifest(self) -> dict:
        resources = sorted((asdict(r) for r in self.resources), key=lambda r: (r["kind"], r["url"]))
        return {
            "site": self.site_url,
            "user_agent": USER_AGENT,
            "pipeline_version": PIPELINE_VERSION,
            "fetched_at": iso(self.now()),
            "requests": self.requests,
            "pages_total": sum(1 for r in resources if r["kind"] == "html"),
            "resources": resources,
        }


# ----- the manifest on disk -----


def write_manifest(raw_dir: Path, manifest: dict) -> Path:
    path = Path(raw_dir) / MANIFEST_NAME
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_manifest(raw_dir: Path) -> dict | None:
    path = Path(raw_dir) / MANIFEST_NAME
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def compare_manifests(previous: dict | None, current: dict) -> dict[str, list[str]]:
    """What changed between the manifest we had and the one we just wrote.

    CI starts from a clean clone: the manifest is committed, the files are not, so every build
    there refetches. This says whether the site still matches what the index was built from:
    ``verified`` (same sha256), ``changed`` (another sha256), ``gone`` (no longer fetched or no
    longer 200), ``new`` (fetched for the first time). Drift is reported, never hidden: the
    caller prints it and keeps it in the coverage.
    """
    out: dict[str, list[str]] = {"verified": [], "changed": [], "gone": [], "new": []}
    if not previous:
        return out
    old = {r["path"]: r for r in previous.get("resources", []) if r.get("file")}
    new = {r["path"]: r for r in current.get("resources", []) if r.get("file")}
    for path in sorted(old):
        if path not in new:
            out["gone"].append(path)
        elif old[path]["content_sha256"] != new[path]["content_sha256"]:
            out["changed"].append(f"{path} ({old[path]['content_sha256'][:12]} → {new[path]['content_sha256'][:12]})")
        else:
            out["verified"].append(path)
    for path in sorted(new):
        if path not in old:
            out["new"].append(path)
    return out


def is_fresh(raw_dir: Path, max_age_days: int = 7, now: Callable[[], datetime] = utc_now) -> tuple[bool, str]:
    """Fresh = a manifest exists, is younger than ``max_age_days``, and every file matches its sha256."""
    manifest = load_manifest(raw_dir)
    if manifest is None:
        return False, "no manifest"
    try:
        fetched = datetime.fromisoformat(manifest["fetched_at"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return False, "manifest has no readable fetched_at"
    if now() - fetched > timedelta(days=max_age_days):
        return False, f"fetched {iso(fetched)}, older than {max_age_days} days"
    for r in manifest.get("resources", []):
        if not r.get("file"):
            continue
        path = Path(raw_dir) / r["file"]
        if not path.exists():
            return False, f"{r['file']} missing"
        if sha256_of(path.read_bytes()) != r.get("content_sha256"):
            return False, f"{r['file']} changed since it was fetched"
    return True, f"fetched {manifest['fetched_at']}, {manifest.get('pages_total', 0)} pages"
