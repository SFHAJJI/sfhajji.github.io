"""Topic, tags and the router's summary line for ``corpus_index`` (SPEC §1 and §2b).

All deterministic: a small dictionary over titles and headings votes the topic; the concepts
of the same dictionary found in the page are its tags; the summary line is a sentence written
for the router, not for a reader: the subject in the reader's words and in the page's own
words, the shape of what the page answers, and what it is not about (its neighbours).

This seed overlaps with brick 2's expert dictionary on purpose: brick 1 must build without
brick 2. When ``dictionary/concepts.yaml`` exists, brick 2 may rewire ``CONCEPTS`` to it.
"""

from __future__ import annotations

import re
from typing import Iterable

from .blocks import fold

TOPICS = ("housing", "vehicle", "liability", "administration", "health", "work", "money", "other")

# Accent-free, lowercase variants (FR/EN/DE); matched as whole words on folded text.
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "housing": ["logement", "bail", "loyer", "louer", "location", "achat", "acheter", "proprietaire", "locataire",
                "habitation", "emmenagement", "demenagement", "immobilier", "housing", "rent", "lease", "wohnung", "miete",
                "commune", "quartier", "logements"],
    "vehicle": ["voiture", "vehicule", "immatriculation", "immatriculer", "permis", "conduire", "auto", "plaque",
                "controle technique", "car", "vehicle", "driving", "fahrzeug", "auto", "transport", "bus", "tram", "train"],
    "liability": ["responsabilite civile", "assurance", "assurer", "sinistre", "franchise", "insurance", "liability",
                  "haftpflicht", "versicherung", "garantie"],
    "administration": ["commune", "declaration", "matricule", "certificat", "residence", "enregistrement", "titre de sejour",
                       "luxtrust", "biergercenter", "guichet", "administration", "nationalite", "naturalisation",
                       "reclamation", "arrivee", "demarche", "demarches", "registration", "gemeinde", "anmeldung", "dechets",
                       "langues", "telecom"],
    "health": ["sante", "cns", "securite sociale", "medecin", "remboursement", "mutuelle", "maladie", "hopital",
               "health", "doctor", "gesundheit", "krankenkasse", "caisse"],
    "work": ["travail", "emploi", "salaire", "employeur", "contrat de travail", "conges", "independant", "freelance",
             "chomage", "work", "job", "employer", "salary", "arbeit", "gehalt", "frontalier", "impatries"],
    "money": ["impot", "impots", "fiscal", "fiscaux", "deduction", "deductions", "banque", "compte", "epargne", "retraite",
              "prevoyance", "credit", "pret", "emprunt", "allocations", "cout", "budget", "simulateur", "tax", "bank",
              "steuer", "classe", "bareme", "avantages", "economies", "interets", "cheque"],
}

# concept → variants. Tags = the concepts whose variant occurs in the page.
CONCEPTS: dict[str, list[str]] = {
    "logement": ["logement", "housing", "wohnung"],
    "bail": ["bail", "contrat de bail", "lease", "mietvertrag"],
    "loyer": ["loyer", "rent", "miete"],
    "garantie locative": ["garantie locative", "caution", "deposit", "kaution"],
    "achat immobilier": ["achat", "acheter", "acte notarie", "notaire", "bellegen akt", "purchase"],
    "assurance habitation": ["assurance habitation", "multirisque", "home insurance"],
    "voiture": ["voiture", "vehicule", "car", "fahrzeug"],
    "immatriculation": ["immatriculation", "immatriculer", "carte grise", "snca", "registration"],
    "controle technique": ["controle technique", "snct", "roadworthiness"],
    "permis de conduire": ["permis", "permis de conduire", "driving licence", "fuhrerschein"],
    "assurance auto": ["assurance auto", "assurance automobile", "bonus", "malus", "releve d'information", "releve d'informations"],
    "responsabilite civile": ["responsabilite civile", "rc", "liability", "haftpflicht"],
    "assurance": ["assurance", "assureur", "insurance", "versicherung"],
    "commune": ["commune", "biergercenter", "bureau de la population", "gemeinde", "municipality"],
    "declaration d'arrivee": ["declaration d'arrivee", "declarer son arrivee", "arrivee", "arrival"],
    "certificat de residence": ["certificat de residence", "attestation d'enregistrement", "residence certificate"],
    "matricule": ["matricule", "numero d'identification", "national id"],
    "titre de sejour": ["titre de sejour", "residence permit", "pays tiers"],
    "luxtrust": ["luxtrust", "myguichet", "guichet.lu"],
    "securite sociale": ["securite sociale", "ccss", "affiliation", "social security"],
    "cns": ["cns", "caisse nationale de sante", "remboursement", "remboursements"],
    "medecin": ["medecin", "doctor", "arzt", "hopital", "pharmacie"],
    "impot": ["impot", "impots", "fiscal", "fiscale", "tax", "steuer"],
    "classe d'impot": ["classe d'impot", "classe 1", "classe 1a", "classe 2", "tax class", "steuerklasse"],
    "fiche de retenue": ["fiche de retenue", "retenue a la source", "retenue d'impot", "withholding"],
    "deduction": ["deduction", "deductible", "deductions", "deduire", "abzug"],
    "impatries": ["impatrie", "impatries", "regime des impatries", "impatriate"],
    "interets hypothecaires": ["interets", "interets hypothecaires", "mortgage interest"],
    "epargne retraite": ["prevoyance-vieillesse", "prevoyance vieillesse", "111bis", "epargne retraite", "pension"],
    "banque": ["banque", "compte bancaire", "iban", "bank", "bankkonto"],
    "pret immobilier": ["pret", "emprunt", "credit immobilier", "hypothecaire", "mortgage", "capacite d'emprunt"],
    "salaire": ["salaire", "brut", "net", "fiche de paie", "salary", "gehalt", "indexation"],
    "contrat de travail": ["contrat de travail", "cdi", "cdd", "periode d'essai", "employment contract"],
    "conges": ["conge", "conges", "jours feries", "leave", "urlaub"],
    "independant": ["independant", "freelance", "autorisation d'etablissement", "self-employed"],
    "chomage": ["chomage", "adem", "unemployment"],
    "frontalier": ["frontalier", "frontaliers", "cross-border", "grenzganger"],
    "allocations familiales": ["allocations familiales", "allocation", "cae", "zukunftskeess", "family allowance"],
    "ecole": ["ecole", "scolaire", "lycee", "school", "schule"],
    "creche": ["creche", "garde", "cheque-service", "maison relais", "childcare", "kita"],
    "transports publics": ["transports publics", "bus", "tram", "train", "cfl", "mobiliteit", "public transport"],
    "telecom": ["telecom", "telecoms", "internet", "mobile", "forfait", "operateur"],
    "langues": ["luxembourgeois", "langue", "langues", "cours de langue", "language"],
    "nationalite": ["nationalite", "naturalisation", "citizenship", "staatsburgerschaft"],
    "dechets": ["dechets", "poubelle", "recyclage", "tri", "waste", "mull"],
    "cout de la vie": ["cout de la vie", "index", "indexation", "cost of living", "budget"],
    "electricite": ["electricite", "fournisseur", "energie", "electricity"],
    "reclamation": ["reclamation", "litige", "mediateur", "contester", "complaint"],
    "demenagement": ["demenagement", "emmenagement", "moving", "umzug"],
    "credit d'impot": ["credit d'impot", "cis", "ci-co2", "tax credit"],
    "cheques-repas": ["cheques-repas", "cheque-repas", "meal voucher"],
}


def _wordre(variant: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w])" + re.escape(fold(variant)) + r"(?![\w])")


_TOPIC_RES = {t: [_wordre(v) for v in vs] for t, vs in TOPIC_KEYWORDS.items()}
_CONCEPT_RES = {c: [_wordre(v) for v in vs] for c, vs in CONCEPTS.items()}


# The site's own categories (``cat`` of a fiche), folded: the strongest single signal.
CATEGORY_TOPIC = {
    "administratif": "administration", "famille": "other", "finances": "money", "impots": "money",
    "logement": "housing", "mobilite": "vehicle", "quotidien": "other", "sante": "health", "travail": "work",
}

# Headings every fiche carries; they say nothing about its subject.
BOILERPLATE_HEADINGS = frozenset({"a retenir", "sources officielles", "dans la meme rubrique"})


def classify_topic(title: str, headings: Iterable[str], category: str = "") -> str:
    """Vote over the title (weight 3), the site's own category (weight 4) and the headings (1).

    A page whose votes spread over many topics (the best one under 40 % of the total, as on a
    FAQ or an index panel) is ``other``: it is about everything, and the router must not be
    told otherwise. Ties go to the first topic in ``TOPICS``; nothing found → ``other``.
    """
    texts = [(fold(title), 3)] + [(fold(h), 1) for h in headings if fold(h) not in BOILERPLATE_HEADINGS]
    scores = {t: 0 for t in TOPICS if t != "other"}
    for text, weight in texts:
        for topic, patterns in _TOPIC_RES.items():
            scores[topic] += weight * sum(1 for p in patterns if p.search(text))
    cat_topic = CATEGORY_TOPIC.get(fold(category))
    if cat_topic == "other":
        return "other"
    if cat_topic:
        scores[cat_topic] += 4
    total = sum(scores.values())
    best = max(scores.values()) if scores else 0
    if best == 0 or (cat_topic is None and best < 0.4 * total):
        return "other"
    return next(t for t in TOPICS if scores.get(t, 0) == best)


def page_words(title: str, headings: Iterable[str], limit: int = 5) -> list[str]:
    """The page's own vocabulary: its heading titles, boilerplate and the title itself removed."""
    out = []
    for h in headings:
        if h == title or fold(h) in BOILERPLATE_HEADINGS or h in out:
            continue
        out.append(h)
    return out[:limit]


def find_concepts(text: str) -> list[str]:
    """The concepts of ``CONCEPTS`` whose variant occurs in ``text`` (whole word, accent-folded)."""
    f = fold(text)
    return [c for c, patterns in _CONCEPT_RES.items() if any(p.search(f) for p in patterns)]


def shape_of(n_sections: int, n_tables: int, n_steps: int, n_questions: int, n_lines: int = 1) -> str:
    """What the page answers with: a procedure, figures, questions, a dossier, or one explanation."""
    if n_lines == 0:
        return "aucun texte (un outil rendu par script)"
    if n_questions >= 3:
        return f"des questions-réponses ({n_questions})"
    if n_steps >= 3:
        return f"une procédure en {n_steps} étapes"
    if n_tables:
        return f"des montants et plafonds en tableau ({n_tables}) et {n_sections} sections"
    if n_sections >= 3:
        return f"un dossier en {n_sections} sections"
    return "une explication courte"


def _cut(items: list[str], limit: int) -> str:
    return ", ".join(x for x in items[:limit] if x)


def summary_line(
    title: str,
    reader_words: list[str],
    page_words: list[str],
    shape: str,
    not_about: list[str],
) -> str:
    """The level-0 line the router reads: subject in both vocabularies, shape, what it is not."""
    parts = [title.strip().rstrip(".") + "."]
    if reader_words:
        parts.append("Mots du lecteur : " + _cut(reader_words, 8) + ".")
    if page_words:
        parts.append("Mots de la page : " + _cut(page_words, 5) + ".")
    parts.append("Forme : " + shape + ".")
    if not_about:
        parts.append("Pas sur : " + _cut(not_about, 3) + ".")
    return " ".join(parts)
