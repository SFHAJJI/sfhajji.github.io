"""Shared fixtures: a tiny two-page fake site, served from memory, and its built tables.

The home page has the real site's shape (panels, with the content in a data script); the
second page is plain HTML in English. Bricks 2 to 4 can build on ``tiny_tables`` without
touching the network: ``accueil`` (static text with nested headings, a table, lists, links),
``fiches``, two fiche documents ``bail`` and ``voiture``, ``faq``, and ``second``.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from guide_rag.parsing.documents import build_documents
from guide_rag.parsing.fetch import Fetcher
from guide_rag.parsing.tables import build_tables

SITE = "https://tiny.example/"

HOME_HTML = """<!doctype html>
<html lang="fr">
<head><meta charset="utf-8"><title>Guide minuscule</title>
<link rel="stylesheet" href="app/styles.css"><script src="app/kb.js?v=1"></script></head>
<body>
<header id="entete"><button>Menu</button></header>
<main>
<section class="panel" id="panel-accueil">
  <h1>Vivre ici</h1>
  <p class="lead">Un guide&nbsp;: d&eacute;marches, logement &amp; voiture.
     <a href="second/">La seconde page</a> et <a href="https://example.org/ext">un site externe</a>.</p>
  <h2 id="logement">Logement</h2>
  <p>Trouver un logement prend du temps. <span id="badge">3</span> Voir <a href="#fiche/bail">le bail</a>.</p>
  <h3>Bail</h3>
  <ul>
    <li>Un bail écrit</li>
    <li>Une garantie
      <ul><li>bancaire</li><li>ou en espèces</li></ul>
    </li>
  </ul>
  <h3>Prix</h3>
  <div class="table-wrap"><table>
    <caption>Loyers moyens</caption>
    <thead><tr><th>Ville</th><th>Loyer</th></tr></thead>
    <tbody><tr><td>Luxembourg</td><td>2 000 €</td></tr><tr><td>Esch</td><td>1 500 €</td></tr></tbody>
  </table></div>
  <h2 id="voiture">Voiture</h2>
  <p>Immatriculer sa voiture dans les six mois. <a href="#voiture">ancre</a></p>
  <div class="notice"><strong>Attention.</strong> Les délais changent.<button>Fermer</button></div>
  <script>var x = 1;</script>
  <input type="search" placeholder="Chercher"><label for="q">Question</label>
</section>
<section class="panel" id="panel-fiches" hidden>
  <div id="fiches-liste"><h1>Fiches pratiques</h1><div class="grid" id="fiches-grid"></div></div>
  <div id="fiche-detail" class="detail" hidden></div>
</section>
<section class="panel" id="panel-faq" hidden>
  <h1>Questions et réponses</h1>
  <div id="faq-liste"></div>
</section>
</main>
</body></html>
"""

SECOND_HTML = """<!doctype html>
<html lang="en">
<head><title>Second page</title></head>
<body>
<h1>Second page</h1>
<p>The second page links <a href="../#logement">back to housing</a> and to <a href="../#fiche/voiture">the car fiche</a>.</p>
<h2>Costs</h2>
<table><tr><th>Item</th><th>Amount</th></tr><tr><td>Deposit</td><td>3 months</td></tr></table>
</body></html>
"""

KB_JS = """// tiny knowledge base
window.KB = {
  meta: { version: 1 },
  fiches: [
    {
      id: "bail", titre: "Signer un bail", cat: "Logement", resume: "Le bail se signe avant les clés.",
      tags: ["bail", "caution", "loyer"],
      corps: [
        "Un bail écrit est la règle. " + "Il fixe le loyer.",
        { h: "La garantie locative" },
        'Elle vaut au plus trois mois de loyer, dit l\\'article.',
      ],
      tableaux: [{ titre: "Délais", colonnes: ["Étape", "Délai"], lignes: [["Préavis", "3 mois"], ["État des lieux", "à la remise"]] }],
      aRetenir: ["Trois mois de garantie au plus."],
      sources: [{ t: "Guichet, le bail", u: "https://guichet.example/bail" }]
    },
    {
      id: "voiture", titre: "Immatriculer sa voiture", cat: "Mobilite", resume: "Six mois pour immatriculer.",
      tags: ["voiture", "immatriculation"],
      corps: ["La SNCA immatricule sur rendez-vous.", { h: "Le dossier" }, "Assurance, plaques, vignette."],
      aRetenir: [],
      sources: []
    }
  ],
  faq: [
    { q: "Combien de mois de garantie ?", a: "Trois mois de loyer au plus.", fiche: "bail" },
    { q: "Quel délai pour immatriculer ?", a: "Six mois après l'arrivée.", fiche: "voiture" }
  ],
  timeline: [ { phase: "Semaine 1", items: [ { t: "Signer le bail.", fiche: "bail" } ] } ]
};
"""

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset><url><loc>https://tiny.example/second/</loc></url><url><loc>https://elsewhere.example/</loc></url></urlset>
"""

TINY_SITE: dict[str, tuple[int, str, str]] = {
    "/": (200, "text/html; charset=utf-8", HOME_HTML),
    "/second/": (200, "text/html; charset=utf-8", SECOND_HTML),
    "/app/kb.js": (200, "application/javascript", KB_JS),
    "/sitemap.xml": (200, "application/xml", SITEMAP_XML),
    "/app/styles.css": (200, "text/css", "body{}"),
}


class SiteHandler:
    """A MockTransport handler that serves ``TINY_SITE`` and records every request."""

    def __init__(self, site: dict[str, tuple[int, str, str]] | None = None, flaky: set[str] | None = None):
        self.site = dict(site or TINY_SITE)
        self.flaky = set(flaky or ())  # paths that fail once with a 500, then succeed
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        path = request.url.path
        if path in self.flaky:
            self.flaky.discard(path)
            return httpx.Response(500, text="boom")
        if path not in self.site:
            return httpx.Response(404, text="not found")
        status, ctype, body = self.site[path]
        return httpx.Response(status, headers={"content-type": ctype, "last-modified": "Mon, 26 Oct 2026 15:49:39 GMT"}, content=body.encode("utf-8"))


def make_fetcher(raw_dir: Path, handler: SiteHandler, **kw) -> Fetcher:
    client = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": "guide-rag/0.1 (+test)"})
    kw.setdefault("sleep", lambda s: None)
    return Fetcher(raw_dir, site_url=SITE, client=client, **kw)


@pytest.fixture
def tiny_site() -> dict[str, tuple[int, str, str]]:
    return dict(TINY_SITE)


@pytest.fixture
def tiny_kb_js() -> str:
    return KB_JS


@pytest.fixture(scope="session")
def tiny_raw_dir(tmp_path_factory) -> Path:
    raw = tmp_path_factory.mktemp("raw")
    make_fetcher(raw, SiteHandler()).crawl()
    return raw


@pytest.fixture(scope="session")
def tiny_manifest(tiny_raw_dir) -> dict:
    from guide_rag.parsing.fetch import load_manifest

    return load_manifest(tiny_raw_dir)


@pytest.fixture(scope="session")
def tiny_documents(tiny_raw_dir, tiny_manifest):
    docs, data = build_documents(tiny_raw_dir, tiny_manifest)
    return docs, data


@pytest.fixture(scope="session")
def tiny_index(tiny_documents):
    docs, data = tiny_documents
    return build_tables(docs, data, site_url=SITE)


@pytest.fixture(scope="session")
def tiny_tables(tiny_index):
    """The six DataFrames of SPEC §1 for the tiny site (page_df, line_df, toc_df, row_df, cross_ref_df, corpus_index)."""
    return tiny_index.tables


@pytest.fixture(scope="session")
def tiny_coverage(tiny_index):
    return tiny_index.coverage
