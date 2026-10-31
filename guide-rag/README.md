# guide-rag

Un chatbot documentaire pour les nouveaux arrivants au Luxembourg, construit brique par brique sur le guide public
[lux-guide.github.io](https://lux-guide.github.io/). Chaque réponse est une citation textuelle du guide avec son
chemin (page › section › lignes), ou une absence justifiée. Aucun modèle n'est nécessaire ; un modèle peut être
branché (clé fournie par le visiteur) sous le même contrat typé.

**La page : https://sfhajji.github.io/guide-rag/** — posez une question, lisez la citation et son chemin, ouvrez la
trace.

*A documentary chatbot for newcomers to Luxembourg, built brick by brick over a public guide, after the method of the
Towards Data Science series "Enterprise Document Intelligence". Every answer is a verbatim quote with its path (page ›
section › lines) or a justified absence; no model required, one can be plugged in under the same typed contract.*

## Les quatre briques

| brique | ce qu'elle fait | ce qu'elle produit |
|---|---|---|
| 1. Analyse du document (`guide_rag/parsing`) | lit le site une fois (HTML et données JS, sans exécuter de code) et le modélise en tables relationnelles | `page_df`, `line_df` (l'unité de citation), `toc_df` (sections, fil d'Ariane, début/fin), `row_df`, `cross_ref_df`, `corpus_index` (une ligne de routage par page), la couverture |
| 2. Analyse de la question (`guide_rag/question`) | corrige l'orthographe contre le vocabulaire du corpus, développe avec le dictionnaire expert (83 concepts, 851 variantes FR/EN/DE), type la question | `ParsedQuestion` (mots-clés avec leur source, forme, type, page lue, décomposition, demande de précision) et un `ExecutionPlan` dont chaque activation porte sa raison |
| 3. Recherche (`guide_rag/retrieval`) | filtre les tables : mots-clés toujours, titres des sections, ancres typées ; routage en deux niveaux (page, puis son plan) ; ancre petite, contexte large ; un arbitre déterministe donne un rôle et une raison à chaque candidat | `RetrievalResult` (candidats avec méthodes, mots trouvés, rôle, raison ; audit par section ; balayage exhaustif pour prouver l'absence) |
| 4. Génération (`guide_rag/generation`) | remplit un schéma typé à partir des lignes de l'ancre ; valide chaque citation contre l'index ; justifie l'absence avec quatre preuves | `TextAnswer` / `ListAnswer` / `AmountAnswer`… avec `items[].spans`, les deux booléens, les réserves ; `AbsenceJustification` ; un bloc `_meta` sur chaque réponse |

Pas de base vectorielle, pas d'agent, pas de texte libre : « la citation est l'explication ». La méthode suivie,
brique par brique, est dans [docs/METHOD.md](docs/METHOD.md) ; le plan dans [docs/PLAN.md](docs/PLAN.md) ; la
spécification dans [SPEC.md](SPEC.md).

## Essayer en local

```bash
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -e .
guide-rag build                       # lit le guide (poliment), construit les tables, exporte index/*.json
guide-rag ask "comment immatriculer ma voiture"
guide-rag ask "combien coûte la garantie locative" --json > trace.json
guide-rag trace trace.json            # rejoue la trace contre l'index
guide-rag eval --traces               # les 46 questions étiquetées : rapport par type, traces/
python -m pytest                      # ~300 tests, dont la vérification croisée Python ↔ JavaScript
```

La page (`index.html` + `web/`) exécute les briques 2 à 4 dans le navigateur, module pour module le miroir du code
Python ; `tests/test_crosscheck.py` vérifie que les deux donnent les mêmes mots-clés, pages, candidats, rôles,
citations et verdict sur chaque question du jeu étalon.

## Évaluation

Mesurée par type de question, jamais en moyenne : [eval/report.md](eval/report.md). Chaque question du jeu étalon a
sa trace rejouable dans `traces/`.

## Licence

MIT pour le code. Le contenu du guide reste celui de ses auteurs ; rien n'en est copié dans ce dépôt (les fichiers
bruts sont lus à la construction et vérifiés par leur empreinte dans `raw/manifest.json`).
