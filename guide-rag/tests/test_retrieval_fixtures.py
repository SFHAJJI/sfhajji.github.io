"""The synthetic two-page guide every retrieval/generation test reads: "logement" (Bail / Garantie
locative / État des lieux) and "voiture" (Immatriculation / Contrôle technique), as SPEC §1 tables.

Imported by the other test modules; it carries helpers, no test of its own.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # so `pytest` from any directory finds the package
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from guide_rag.retrieval.contracts import (Activation, Decomposition, ExecutionPlan, Keyword,  # noqa: E402
                                           ParsedQuestion, StructuralHints, Tables)

LOGEMENT = [
    # line_num, element, section_id, text
    (1, "h1", "logement#s1", "Logement"),
    (2, "p", "logement#s1", "Trouver un logement au Luxembourg demande du temps."),
    (3, "h2", "logement#s2", "Bail"),
    (4, "p", "logement#s2", "Le bail est le contrat de location signé entre le locataire et le propriétaire."),
    (5, "p", "logement#s2", "Le bail doit être écrit et préciser la durée et le loyer."),
    (6, "td", "logement#s2", "Durée du bail: 3 ans | Préavis: 3 mois"),
    (7, "td", "logement#s2", "Loyer mensuel: 750 € | Charges: 150 €"),
    (8, "h2", "logement#s3", "Garantie locative"),
    (9, "p", "logement#s3", "La garantie locative est une somme déposée par le locataire pour couvrir les dégâts éventuels."),
    (10, "p", "logement#s3", "Elle correspond en général à deux mois de loyer, soit 1 500 € pour un loyer de 750 €."),
    (11, "p", "logement#s3", "Elle est rendue à la fin du bail après l'état des lieux de sortie."),
    (12, "h2", "logement#s4", "État des lieux"),
    (13, "p", "logement#s4", "L'état des lieux décrit le logement à l'entrée et à la sortie."),
    (14, "p", "logement#s4", "Il doit être signé par le locataire et le propriétaire avant le 15 janvier 2025."),
    (15, "li", "logement#s4", "Photos de chaque pièce"),
    (16, "li", "logement#s4", "Relevé des compteurs"),
]
VOITURE = [
    (1, "h1", "voiture#s1", "Voiture"),
    (2, "p", "voiture#s1", "Rouler au Luxembourg avec une voiture étrangère impose quelques démarches."),
    (3, "h2", "voiture#s2", "Immatriculation"),
    (4, "p", "voiture#s2", "L'immatriculation de la voiture se fait auprès de l'administration dans les six mois après l'arrivée."),
    (5, "p", "voiture#s2", "La taxe d'immatriculation coûte 50 € et le certificat est envoyé par la poste."),
    (6, "li", "voiture#s2", "Certificat de conformité"),
    (7, "li", "voiture#s2", "Preuve d'assurance responsabilité civile"),
    (8, "h2", "voiture#s3", "Contrôle technique"),
    (9, "p", "voiture#s3", "Le contrôle technique est obligatoire tous les ans pour une voiture de plus de six ans."),
    (10, "p", "voiture#s3", "Le rendez-vous se prend en ligne sur https://example.org/ct ou par téléphone au +352 26 12 34 56."),
    (11, "p", "voiture#s3", "Le centre se trouve à L-3225 Bettembourg et ouvre le 2025-03-01."),
]
TOC = [
    # doc_id, section_id, level, parent_id, title, breadcrumb, start, end, anchor_id
    ("logement", "logement#s1", 1, None, "Logement", "Logement", 1, 16, "top"),
    ("logement", "logement#s2", 2, "logement#s1", "Bail", "Logement › Bail", 3, 7, "bail"),
    ("logement", "logement#s3", 2, "logement#s1", "Garantie locative", "Logement › Garantie locative", 8, 11, "garantie"),
    ("logement", "logement#s4", 2, "logement#s1", "État des lieux", "Logement › État des lieux", 12, 16, "edl"),
    ("voiture", "voiture#s1", 1, None, "Voiture", "Voiture", 1, 11, "top"),
    ("voiture", "voiture#s2", 2, "voiture#s1", "Immatriculation", "Voiture › Immatriculation", 3, 7, "immat"),
    ("voiture", "voiture#s3", 2, "voiture#s1", "Contrôle technique", "Voiture › Contrôle technique", 8, 11, "ct"),
]
DICTIONARY = {
    "logement": ["logement", "housing", "Wohnung"],
    "bail": ["bail", "contrat de location", "lease", "Mietvertrag"],
    "garantie_locative": ["garantie locative", "caution", "deposit", "rental guarantee"],
    "etat_des_lieux": ["état des lieux", "inventory", "check-in report"],
    "loyer": ["loyer", "rent"],
    "voiture": ["voiture", "car", "Auto"],
    "immatriculation": ["immatriculation", "registration"],
    "controle_technique": ["contrôle technique", "roadworthiness test", "technical inspection"],
    "permis": ["permis de conduire", "driving licence"],
}
URLS = {"logement": "https://example.org/logement", "voiture": "https://example.org/voiture"}


def _anchor_for(doc_id: str, section_id: str) -> str:
    return next(r[8] for r in TOC if r[0] == doc_id and r[1] == section_id)


def make_tables() -> Tables:
    rows = []
    for doc_id, lines in (("logement", LOGEMENT), ("voiture", VOITURE)):
        for line_num, element, section_id, text in lines:
            rows.append({
                "doc_id": doc_id, "line_num": line_num, "text": text, "element": element,
                "section_id": section_id, "anchor_id": _anchor_for(doc_id, section_id),
                "css_path": f"body > {element}:nth-of-type({line_num})", "char_count": len(text),
                "is_heading": element.startswith("h"),
            })
    line_df = pd.DataFrame(rows)
    toc_df = pd.DataFrame([
        {"doc_id": d, "section_id": s, "level": lv, "parent_id": p, "title": t, "breadcrumb": b,
         "start_line": a, "end_line": e, "anchor_id": an, "source": "headings"}
        for d, s, lv, p, t, b, a, e, an in TOC
    ])
    row_df = pd.DataFrame([
        {"doc_id": "logement", "table_id": "logement#t1", "line_num": 6, "column_headers": ["Durée du bail", "Préavis"],
         "row_cells": ["3 ans", "3 mois"], "row_serialized": "Durée du bail: 3 ans | Préavis: 3 mois"},
        {"doc_id": "logement", "table_id": "logement#t1", "line_num": 7, "column_headers": ["Loyer mensuel", "Charges"],
         "row_cells": ["750 €", "150 €"], "row_serialized": "Loyer mensuel: 750 € | Charges: 150 €"},
    ])
    corpus_index = pd.DataFrame([
        {"doc_id": "logement", "url": URLS["logement"], "title": "Logement", "topic": "housing",
         "summary_line": "Logement — Trouver un logement au Luxembourg demande du temps. Bail, garantie locative, état des lieux.",
         "tags": ["logement", "bail", "garantie_locative", "etat_des_lieux", "loyer"], "n_lines": 16, "lang": "fr"},
        {"doc_id": "voiture", "url": URLS["voiture"], "title": "Voiture", "topic": "vehicle",
         "summary_line": "Voiture — Rouler au Luxembourg avec une voiture étrangère impose quelques démarches. Immatriculation, contrôle technique.",
         "tags": ["voiture", "immatriculation", "controle_technique"], "n_lines": 11, "lang": "fr"},
    ])
    page_df = pd.DataFrame([
        {"doc_id": "logement", "url": URLS["logement"], "title": "Logement", "lang": "fr", "n_lines": 16, "n_sections": 4,
         "n_tables": 1, "content_sha256": "a" * 64, "fetched_at": "2026-10-31T00:00:00Z", "last_modified": None,
         "parsing_method": "html_blocks/1"},
        {"doc_id": "voiture", "url": URLS["voiture"], "title": "Voiture", "lang": "fr", "n_lines": 11, "n_sections": 3,
         "n_tables": 0, "content_sha256": "b" * 64, "fetched_at": "2026-10-31T00:00:00Z", "last_modified": None,
         "parsing_method": "html_blocks/1"},
    ])
    coverage = {"pages_total": 2, "pages_with_text": 2, "lines_total": 27, "sections_total": 7, "tables_total": 1,
                "cross_refs": 0, "fetched_at": "2026-10-31T00:00:00Z", "index_version": "idx-test-1",
                "pipeline_version": "guide-rag/0.1"}
    return Tables(line_df=line_df, toc_df=toc_df, row_df=row_df, corpus_index=corpus_index, page_df=page_df,
                  parse_coverage=coverage, index_version="idx-test-1")


def kw(text: str, weight: float = 1.0, source: str = "direct", concept: str | None = None, is_regex: bool = False) -> Keyword:
    return Keyword(text=text, weight=weight, source=source, concept=concept, is_regex=is_regex)


def expand(concept: str) -> list[Keyword]:
    """What brick 2 does for a matched concept: every variant at weight 0.6."""
    return [kw(v, 0.6, "expert_dictionary", concept) for v in DICTIONARY[concept]]


def pq(question: str, keywords: list[Keyword], *, qid: str = "q1", answer_type: str = "text", answer_shape: str = "single",
       pages_hint: list[str] | None = None, toc_hint: str | None = None, answer_context: str | None = None,
       language: str = "fr", **extra) -> ParsedQuestion:
    if answer_context is None:
        answer_context = "section" if answer_shape == "listing" else ("line" if answer_type in ("amount", "date", "boolean") else "paragraph")
    return ParsedQuestion(
        question_id=qid, original_question=question, corrected_question=question.lower(), language=language,
        keywords=keywords, answer_shape=answer_shape, answer_type=answer_type,
        structural_hints=StructuralHints(pages_hint=pages_hint, toc_section_hint=toc_hint, answer_context=answer_context),
        decomposition=Decomposition(), **extra,
    )


def plan_for(parsed: ParsedQuestion, *, use_toc: bool = True, llm: bool = False) -> ExecutionPlan:
    """A plan shaped as brick 2's dispatcher writes it: every flag with on and reason."""
    typed = parsed.answer_type in ("amount", "date")
    hinted = bool(parsed.structural_hints.pages_hint)
    return ExecutionPlan(activations={
        "use_keywords": Activation(on=True, reason="always on"),
        "use_toc": Activation(on=use_toc, reason="toc_df has >= 3 sections" if use_toc else "test: toc off"),
        "use_row_level": Activation(on=typed, reason="answer_type asks for an amount or a date" if typed else "no amount/date and no column named"),
        "use_embeddings": Activation(on=False, reason="no vocabulary mismatch expected beyond the dictionary; keywords prove absence"),
        "use_llm_arbiter": Activation(on=False, reason="no key configured"),
        "use_llm_generation": Activation(on=llm, reason="key configured (test transport)" if llm else "no key configured"),
        "sweep_for_absence": Activation(on=True, reason="always on"),
        "current_page_boost": Activation(on=hinted, reason="pages_hint present" if hinted else "no pages_hint"),
    })


# Ready-made questions.
def q_garantie(**kw_args) -> ParsedQuestion:
    return pq("Combien coûte la garantie locative ?", [kw("garantie", concept="garantie_locative"), *expand("garantie_locative")],
              answer_type="amount", **kw_args)


def q_bail(**kw_args) -> ParsedQuestion:
    return pq("Qu'est-ce que le bail ?", [kw("bail", concept="bail"), *expand("bail")], **kw_args)


def q_edl_date(**kw_args) -> ParsedQuestion:
    return pq("Quand signer l'état des lieux ?", [kw("état des lieux", concept="etat_des_lieux"), kw("signé"), *expand("etat_des_lieux")],
              answer_type="date", **kw_args)


def q_immat_list(**kw_args) -> ParsedQuestion:
    return pq("Quels documents pour l'immatriculation ?", [kw("documents"), kw("immatriculation", concept="immatriculation"), *expand("immatriculation")],
              answer_shape="listing", **kw_args)


def q_permis(**kw_args) -> ParsedQuestion:
    return pq("Comment échanger mon permis de conduire ?", [kw("échanger"), kw("permis", concept="permis"), *expand("permis")], **kw_args)
