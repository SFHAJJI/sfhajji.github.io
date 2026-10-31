"""Synthetic SPEC tables for the brick-2 tests: small frames with the columns of SPEC §1.

No network, no brick-1 code: the corpus is three pages typed here. The module also holds one
smoke test so that pytest never reports it as an empty file.
"""

from __future__ import annotations

import pandas as pd
import pytest

from guide_rag.question import Dictionary

LINE_COLUMNS = ["doc_id", "line_num", "text", "element", "section_id", "anchor_id", "css_path", "char_count", "is_heading"]
TOC_COLUMNS = ["doc_id", "section_id", "level", "parent_id", "title", "breadcrumb", "start_line", "end_line", "anchor_id", "source"]
CORPUS_COLUMNS = ["doc_id", "url", "title", "topic", "summary_line", "tags", "n_lines", "lang"]
ROW_COLUMNS = ["doc_id", "table_id", "line_num", "column_headers", "row_cells", "row_serialized"]

_LINES = [
    ("logement", 1, "Logement", "h1", "logement#s1"),
    ("logement", 2, "Trouver un logement au Luxembourg demande du temps et un bon dossier.", "p", "logement#s1"),
    ("logement", 3, "Garantie locative", "h2", "logement#s2"),
    ("logement", 4, "La garantie locative est au maximum de 3 mois de loyer, par exemple 4 500 € pour un loyer de 1 500 €.", "p", "logement#s2"),
    ("logement", 5, "Elle est versée sur un compte bloqué ou par garantie bancaire.", "p", "logement#s2"),
    ("logement", 6, "État des lieux", "h2", "logement#s3"),
    ("logement", 7, "L'état des lieux d'entrée est signé par le locataire et le propriétaire.", "p", "logement#s3"),
    ("logement", 8, "Les documents à fournir sont : une pièce d'identité, un contrat de travail, trois fiches de paie.", "p", "logement#s3"),
    ("voiture", 1, "Voiture", "h1", "voiture#s1"),
    ("voiture", 2, "Immatriculation du véhicule", "h2", "voiture#s2"),
    ("voiture", 3, "L'immatriculation de votre véhicule se fait à la SNCA, avec la carte grise et l'assurance.", "p", "voiture#s2"),
    ("voiture", 4, "Contrôle technique", "h2", "voiture#s3"),
    ("voiture", 5, "Le contrôle technique coûte environ 50 €. Appelez le 26 62 68 00 pour un rendez-vous.", "p", "voiture#s3"),
    ("voiture", 6, "Le certificat est valable 1 an ; la prochaine visite est due le 15 mars 2026.", "p", "voiture#s3"),
    ("commune", 1, "Commune", "h1", "commune#s1"),
    ("commune", 2, "Déclaration d'arrivée", "h2", "commune#s2"),
    ("commune", 3, "L'inscription à la commune se fait dans les 8 jours suivant l'arrivée, au Biergercenter.", "p", "commune#s2"),
    ("commune", 4, "Adresse : 44 Place Guillaume II, L-1648 Luxembourg. Site : www.vdl.lu.", "p", "commune#s2"),
]

_TOC = [
    ("logement", "logement#s1", 1, None, "Logement", "Logement", 1, 8),
    ("logement", "logement#s2", 2, "logement#s1", "Garantie locative", "Logement › Garantie locative", 3, 5),
    ("logement", "logement#s3", 2, "logement#s1", "État des lieux", "Logement › État des lieux", 6, 8),
    ("voiture", "voiture#s1", 1, None, "Voiture", "Voiture", 1, 6),
    ("voiture", "voiture#s2", 2, "voiture#s1", "Immatriculation du véhicule", "Voiture › Immatriculation du véhicule", 2, 3),
    ("voiture", "voiture#s3", 2, "voiture#s1", "Contrôle technique", "Voiture › Contrôle technique", 4, 6),
    ("commune", "commune#s1", 1, None, "Commune", "Commune", 1, 4),
    ("commune", "commune#s2", 2, "commune#s1", "Déclaration d'arrivée", "Commune › Déclaration d'arrivée", 2, 4),
]

_CORPUS = [
    ("logement", "https://example.invalid/logement", "Logement", "housing", "Logement: trouver un logement...",
     ["logement", "garantie_locative", "etat_des_lieux", "loyer", "locataire", "proprietaire", "garantie_bancaire"], 8, "fr"),
    ("voiture", "https://example.invalid/voiture", "Voiture", "vehicle", "Voiture: immatriculation...",
     ["voiture", "immatriculation", "snca", "carte_grise", "controle_technique", "assurance_auto"], 6, "fr"),
    ("commune", "https://example.invalid/commune", "Commune", "administration", "Commune: déclaration d'arrivée...",
     ["commune", "declaration d'arrivee", "biergercenter"], 4, "fr"),
]


def synthetic_tables() -> dict[str, pd.DataFrame]:
    line_rows = []
    for doc_id, n, text, element, section_id in _LINES:
        line_rows.append((doc_id, n, text, element, section_id, section_id.split("#")[1], f"body > {element}", len(text), element.startswith("h")))
    line_df = pd.DataFrame(line_rows, columns=LINE_COLUMNS)
    toc_rows = [(*row, row[1].split("#")[1], "headings") for row in _TOC]
    toc_df = pd.DataFrame(toc_rows, columns=TOC_COLUMNS)
    corpus_index = pd.DataFrame(_CORPUS, columns=CORPUS_COLUMNS)
    row_df = pd.DataFrame(
        [("voiture", "voiture#t1", 5, ["Prestation", "Prix"], ["Contrôle technique", "50 €"], "Prestation: Contrôle technique | Prix: 50 €")],
        columns=ROW_COLUMNS,
    )
    page_df = corpus_index[["doc_id", "url", "title", "lang", "n_lines"]].copy()
    return {"line_df": line_df, "toc_df": toc_df, "corpus_index": corpus_index, "row_df": row_df, "page_df": page_df}


@pytest.fixture(scope="session")
def tables() -> dict[str, pd.DataFrame]:
    return synthetic_tables()


@pytest.fixture(scope="session")
def dictionary() -> Dictionary:
    return Dictionary.load()


def test_synthetic_tables_have_spec_columns(tables):
    assert list(tables["line_df"].columns) == LINE_COLUMNS
    assert list(tables["toc_df"].columns) == TOC_COLUMNS
    assert list(tables["corpus_index"].columns) == CORPUS_COLUMNS
    assert tables["line_df"]["line_num"].min() == 1
