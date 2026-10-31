"""JS data records → the HTML the site itself renders from them.

The site is one page of panels whose content lives in data scripts; the browser builds the
DOM from them (``app/ui.js``, ``app/guide.js``, ``app/avantages.js``, ``prevoyance/app/site.js``).
We mirror those renderers here, with the same container ids and classes where they exist, so
that one HTML parser serves every document and the css paths point at the live page. Every
text is escaped and copied verbatim; the only composed strings are the ones the site composes
itself (the "k : v, d." key figures of a guided fiche, "Voir la fiche : …").
"""

from __future__ import annotations

from html import escape as _e
from typing import Any


def _p(text: Any, cls: str = "") -> str:
    if text in (None, ""):
        return ""
    c = f' class="{cls}"' if cls else ""
    return f"<p{c}>{_e(str(text))}</p>"


def _h(level: int, text: Any, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f"<h{level}{c}>{_e(str(text))}</h{level}>"


def _ul(items: list[Any], cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f"<ul{c}>" + "".join(f"<li>{_e(str(x))}</li>" for x in items) + "</ul>"


def link_href(lien: dict[str, Any] | None, base: str = "") -> str:
    """The href the site gives a link record: ``{fiche}`` → ``#fiche/<id>``, ``{panneau}`` → ``#<id>``,
    ``{u}``/``{url}`` → as given."""
    if not lien:
        return ""
    if lien.get("fiche"):
        return f"{base}#fiche/{lien['fiche']}"
    if lien.get("panneau"):
        return f"{base}#{lien['panneau']}"
    return str(lien.get("u") or lien.get("url") or "")


def _a(text: Any, href: str, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f'<a{c} href="{_e(href, quote=True)}">{_e(str(text))}</a>'


def render_table(colonnes: list[Any], lignes: list[list[Any]]) -> str:
    head = "".join(f"<th>{_e(str(c))}</th>" for c in colonnes)
    body = "".join("<tr>" + "".join(f"<td>{_e(str(c))}</td>" for c in row) + "</tr>" for row in lignes)
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


# ---------------------------------------------------------------- fiches (ui.js, guide.js)


def render_guide(g: dict[str, Any]) -> str:
    """A guided fiche (``f.guide``), after app/guide.js: key figures, cases, then tabs of blocks."""
    out: list[str] = []
    reperes = g.get("reperes") or []
    if reperes:
        out.append('<div class="g-reperes">')
        for r in reperes:
            out.append(_p(f"{r.get('k')} : {r.get('v')}, {r.get('d')}.", "g-repere"))
        out.append("</div>")
    cas = g.get("cas")
    if cas:
        out.append('<section class="g-cas">' + _h(2, cas.get("titre", "")) + '<div class="g-cas-grille">')
        for it in cas.get("items") or []:
            out.append(f'<div class="g-cas-item"><strong>{_e(str(it.get("t", "")))}</strong>{_p(it.get("d"))}</div>')
        out.append("</div></section>")
    for tab in g.get("onglets") or []:
        out.append(f'<section class="g-onglet" id="g-{_e(str(tab.get("id", "")), quote=True)}">' + _h(2, tab.get("titre", "")))
        for bloc in tab.get("blocs") or []:
            out.append(render_bloc(bloc))
        out.append("</section>")
    return "".join(out)


def render_bloc(b: Any) -> str:
    if isinstance(b, str):
        return _p(b)
    if not isinstance(b, dict):
        return ""
    out: list[str] = []
    if b.get("note"):
        out.append(f'<blockquote class="g-note">{_e(str(b["note"]))}</blockquote>')
    if b.get("etapes"):
        out.append('<ol class="g-etapes">')
        for e in b["etapes"]:
            out.append('<li class="g-etape"><div class="g-etape-carte">' + _h(3, e.get("t", "")) + _p(e.get("d")))
            fields = [("Où", e.get("ou")), ("Apportez", e.get("apportez")), ("Coût", e.get("cout")), ("Vous obtenez", e.get("obtenez"))]
            if any(v for _, v in fields):
                out.append('<dl class="g-champs">')
                for k, v in fields:
                    if not v:
                        continue
                    out.append(f"<dt>{_e(k)}</dt>")
                    for x in v if isinstance(v, list) else [v]:
                        out.append(f"<dd>{_e(str(x))}</dd>")
                out.append("</dl>")
            if e.get("lien"):
                out.append(f'<p class="g-pied">{_a(e["lien"].get("t", ""), link_href(e["lien"]), "g-lien")}</p>')
            out.append("</div></li>")
        out.append("</ol>")
    if b.get("cocher"):
        out.append('<ul class="g-cocher">')
        for it in b.get("items") or []:
            li = _e(str(it.get("t", "")))
            if it.get("d"):
                li += f'<span class="g-d"> : {_e(str(it["d"]))}</span>'
            if it.get("lien"):
                li += " " + _a(it["lien"].get("t", ""), link_href(it["lien"]), "g-lien")
            out.append(f"<li>{li}</li>")
        out.append("</ul>")
    for p in b.get("pays") or []:
        out.append('<section class="g-pays">' + _h(3, p.get("t", "")))
        for col in p.get("colonnes") or []:
            out.append(_h(4, col.get("h", "")) + _ul(col.get("l") or []))
        out.append("</section>")
    if b.get("tableau"):
        t = b["tableau"]
        out.append(render_table(t.get("colonnes") or [], t.get("lignes") or []))
    for pli in b.get("plis") or []:
        # The site folds these behind <details>/<summary>; the question is a heading for us.
        out.append('<section class="g-pli">' + _h(3, pli.get("t", "")) + "".join(_p(x) for x in pli.get("p") or []) + "</section>")
    return "".join(out)


def render_fiche(f: dict[str, Any]) -> str:
    """One fiche as ``#fiche-detail`` shows it: hero title, body (or guide), key points, sources."""
    out = ['<div class="detail-hero"><div class="titre">' + _h(1, f.get("titre", "")) + "</div></div>"]
    out.append('<div class="detail-corps"><div class="detail-texte">')
    out.append(_p(f.get("resume"), "chapo"))
    if f.get("guide"):
        out.append(render_guide(f["guide"]))
    else:
        for p in f.get("corps") or []:
            if isinstance(p, dict) and p.get("h"):
                out.append(_h(2, p["h"]))
            elif p not in (None, ""):
                out.append(_p(p))
        for t in f.get("tableaux") or []:
            out.append(_h(3, t.get("titre", "")) + render_table(t.get("colonnes") or [], t.get("lignes") or []))
    out.append("</div>")
    # The side column sits beside the body, not inside its last section. The site titles its
    # blocks with <h4>; as <h2> here, the outline says what the layout says.
    out.append('<div class="detail-cote">')
    if f.get("aRetenir"):
        out.append('<div class="bloc cle">' + _h(2, "À retenir") + _ul(f["aRetenir"]) + "</div>")
    if f.get("sources"):
        out.append('<div class="bloc">' + _h(2, "Sources officielles") + "<ul class=\"sources\">")
        for s in f["sources"]:
            out.append(f"<li>{_a(s.get('t', ''), str(s.get('u', '')))}</li>")
        out.append("</ul></div>")
    out.append("</div></div>")
    return "".join(out)


def render_fiche_list(fiches: list[dict[str, Any]]) -> str:
    """The ``#fiches-grid`` cards: title and summary of every fiche."""
    out = []
    for f in fiches:
        out.append('<article class="carte">' + f"<h3>{_a(f.get('titre', ''), '#fiche/' + str(f.get('id', '')))}</h3>" + _p(f.get("resume")) + "</article>")
    return "".join(out)


# ---------------------------------------------------------------- faq, parcours (ui.js)


def render_faq(faq: list[dict[str, Any]], fiches: list[dict[str, Any]]) -> str:
    """``#faq-liste``: questions grouped by the category of their fiche, in first-seen order."""
    by_id = {f.get("id"): f for f in fiches}
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in faq:
        f = by_id.get(item.get("fiche"))
        cat = f.get("cat", "Divers") if f else "Divers"
        groups.setdefault(cat, []).append(item)
    out = []
    for cat, items in groups.items():
        out.append(_h(2, cat, "faq-groupe"))
        for item in items:
            f = by_id.get(item.get("fiche"))
            out.append('<div class="faq-item">' + _h(3, item.get("q", "")) + '<div class="faq-corps">' + _p(item.get("a")))
            if f:
                out.append(f'<p class="chips">{_a("Voir la fiche : " + str(f.get("titre", "")), "#fiche/" + str(f.get("id")), "chip")}</p>')
            out.append("</div></div>")
    return "".join(out)


def render_timeline(timeline: list[dict[str, Any]]) -> str:
    """``#timeline``: one heading per phase, one item per step, each step linking its fiche."""
    out = []
    for phase in timeline:
        out.append('<div class="tl-phase">' + _h(2, phase.get("phase", "")) + '<ol class="tl-items">')
        for item in phase.get("items") or []:
            text = str(item.get("t", ""))
            out.append("<li>" + (_a(text, "#fiche/" + str(item["fiche"])) if item.get("fiche") else _e(text)) + "</li>")
        out.append("</ol></div>")
    return "".join(out)


# ---------------------------------------------------------------- avantages (avantages.js)


def render_avantages(avantages: list[dict[str, Any]], moments: list[list[Any]], modes: dict[str, list[Any]]) -> str:
    """``#avantages-grille``: one heading per life moment, one card per advantage."""
    labels = {m[0]: m[1] for m in moments if isinstance(m, list) and len(m) >= 2}
    out = []
    for moment_id, label in labels.items():
        cards = [a for a in avantages if a.get("moment") == moment_id]
        if not cards:
            continue
        out.append('<section class="av-moment">' + _h(2, label))
        for a in cards:
            out.append(f'<article class="av-carte" id="av-{_e(str(a.get("id", "")), quote=True)}">' + _h(3, a.get("titre", "")))
            if a.get("chiffre") or a.get("sous"):
                out.append(f'<p class="av-chiffre"><strong>{_e(str(a.get("chiffre", "")))}</strong> {_e(str(a.get("sous", "")))}</p>')
            mode = modes.get(a.get("mode", ""))
            if mode:
                out.append(f'<dl class="av-mode"><dt>{_e(str(mode[0]))}</dt><dd>{_e(str(mode[1]))}</dd></dl>')
            out.append(_p(a.get("texte"), "av-texte"))
            out.append(_p(a.get("savoir"), "av-savoir"))
            if a.get("sources"):
                out.append('<ul class="av-sources">' + "".join(f"<li>{_a(s.get('t', ''), str(s.get('u', '')))}</li>" for s in a["sources"]) + "</ul>")
            if a.get("verifie"):
                out.append(f'<dl class="av-verifie"><dt>Vérifié</dt><dd>{_e(str(a["verifie"]))}</dd></dl>')
            if a.get("lien"):
                out.append(_p_link(a["lien"]))
            out.append("</article>")
        out.append("</section>")
    return "".join(out)


def _p_link(lien: dict[str, Any]) -> str:
    text = lien.get("texte") or lien.get("t") or ""
    return f'<p class="av-lien">{_a(text, link_href(lien))}</p>' if text else ""


# ---------------------------------------------------------------- prevoyance (site.js)


def eur(n: Any) -> str:
    """``4500`` → ``4 500 €``, as the site's ``eur()`` prints it (a plain space, not U+202F)."""
    return f"{int(round(float(n))):,}".replace(",", " ") + " €"


def prevoyance_marks(table: dict[str, Any]) -> dict[str, str]:
    """The ``{plafond}``-style marks that site.js fills from ``PREVOYANCE.table``."""
    p = table.get("prevoyance") or {}
    return {
        "plafond": eur(p.get("plafond", 0)),
        "plafondPrecedent": eur(p.get("plafondPrecedent", 0)),
        "annee": str(table.get("annee", "")),
        "anneePrecedente": str(table.get("anneePrecedente", "")),
        "duree": str(p.get("dureeMinimaleAns", "")),
        "ageMax": str(p.get("ageMaxSouscription", "")),
        "sortieMin": str(p.get("sortieMin", "")),
        "sortieMax": str(p.get("sortieMax", "")),
    }


def fill_marks(text: Any, marks: dict[str, str]) -> str:
    import re

    return re.sub(r"\{(\w+)\}", lambda m: marks.get(m.group(1), m.group(0)), str(text or ""))


def render_prevoyance_questions(questions: dict[str, Any], marks: dict[str, str]) -> str:
    """``#q-liste``: the entries grouped by theme; answers with their marks filled."""
    themes = questions.get("themes") or []
    entries = questions.get("entrees") or []
    out = []
    for theme in themes:
        items = [e for e in entries if e.get("theme") == theme.get("id")]
        if not items:
            continue
        out.append('<section class="q-theme">' + _h(2, theme.get("nom", "")))
        for e in items:
            out.append(f'<article class="q-item" id="q-{_e(str(e.get("id", "")), quote=True)}">' + _h(3, fill_marks(e.get("question"), marks)))
            out.append(_p(fill_marks(e.get("reponse"), marks), "q-reponse"))
            out.append(_p(fill_marks(e.get("reserve"), marks), "q-reserve"))
            sources = [s for s in e.get("sources") or [] if isinstance(s, dict)]
            if sources:
                out.append('<ul class="q-sources">' + "".join(f"<li>{_a(s.get('t', ''), str(s.get('u', '')))}</li>" for s in sources) + "</ul>")
            out.append("</article>")
        out.append("</section>")
    return "".join(out)


def render_prevoyance_leviers(table: dict[str, Any]) -> str:
    """``#acc-apercu``: the deductible items of the fiscal table, one row each."""
    rows = []
    for lv in table.get("leviers") or []:
        rows.append([lv.get("nom", ""), eur(lv.get("plafond", 0)) + ("" if lv.get("annuel", True) else " (ponctuel)"), lv.get("condition", "")])
    return render_table(["Poste", "Plafond", "Condition"], rows) if rows else ""


def render_sources_list(sources: list[dict[str, Any]]) -> str:
    return "".join(f"<li>{_a(s.get('t', ''), str(s.get('u', '')))}</li>" for s in sources if isinstance(s, dict))
