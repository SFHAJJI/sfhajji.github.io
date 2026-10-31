# Guide RAG — specification of record (2026-10-31)

A "chatbot documentaire" for newcomers to Luxembourg over the public static site https://lux-guide.github.io/ (the
corpus), built brick by brick after the method of the Towards Data Science series "Enterprise Document Intelligence"
(43 articles read on 2026-10-31; its public companion code was read for understanding only and nothing of it is
copied: its licence is personal use). The repository is public (`SFHAJJI/guide-rag`, MIT); the page is
https://sfhajji.github.io/guide-rag/. No person's name, e-mail or company appears anywhere in the repository or on
the page; the series is cited by its title and article links only.

Python 3.12, pandas + pydantic v2 + sqlite3 + httpx + beautifulsoup4/selectolax; no vector store, no framework, no
agent. Temperature 0 everywhere a model is used. The model is optional on every path: the pipeline runs end to end
without one ("no model" is a logged value of `model_used`).

## 0. The rules every brick obeys

1. Four bricks: document parsing → question parsing → retrieval → generation. Typed handoffs; what one brick passes
   to the next is what is saved. "The junctions between bricks are tables, not strings."
2. Relational, never flat: the corpus becomes tables keyed by shared identifiers; downstream reads rows, never the
   HTML again. Open the source once.
3. The line is the citation unit; every answer and every candidate carries doc_id → section breadcrumb →
   line_start..line_end → verbatim quote. The displayed passage is recovered from `line_df` by ids, never from the
   model.
4. Retrieval is filtering, not search: keyword detectors always run (deterministic, auditable, prove absence); the
   document's own structure (headings) is a first-class signal; embeddings are absent and the reason is logged.
5. Anchor small, context large, returned as a typed pair; the context always contains the anchor.
6. The expert dictionary (concepts + keyword variants, FR/EN/DE/LB) is a versioned, editable asset; models at most
   propose entries.
7. Deterministic dispatcher: every activation has a logged reason; same question, same route.
8. Generation fills a typed schema; two booleans (answer_found, complete_answer_found); a validator checks every span
   and quote before anything is shown; what fails is not shipped.
9. "Not in this guide" shows four kinds of evidence; vague questions get one clarification with a proposed default.
10. Evaluation per question type, never one aggregate; every answer replayable from its trace.

## 1. Brick 1 — document parsing (`guide_rag/parsing`)

Input: the site. `fetch.py` discovers pages from the home page links and `sitemap.xml` if present (same origin only,
≤ 60 pages, polite: 1 request/s, User-Agent naming the repository), stores raw HTML under `raw/<doc_id>.html` with
`content_sha256`, `fetched_at`, `last_modified`, `http_status`. The site's data scripts (window.KB / FICHES), if any,
are parsed from the raw text without executing them.

Tables (pandas → SQLite `index/guide.sqlite` → JSON `index/*.json`):

- `page_df` — one row per page: `doc_id` (slug from the path, e.g. `logement`), `url`, `title`, `lang` (fr/en/de
  from `<html lang>` or dictionary vote), `n_lines`, `n_sections`, `n_tables`, `content_sha256`, `fetched_at`,
  `last_modified`, `parsing_method` = "html_blocks/1".
- `line_df` — one row per visible block, **the citation unit**: `doc_id`, `line_num` (1-based, global within the
  page, in reading order), `text` (verbatim, whitespace-squashed, entities decoded), `element` ∈ h1 h2 h3 h4 p li td
  th caption blockquote dt dd, `section_id` (the innermost heading above it), `anchor_id` (nearest preceding `id`,
  for the link `url#anchor`), `css_path` (for the highlighter), `char_count`, `is_heading`.
- `toc_df` — one row per heading (h1–h4): `doc_id`, `section_id` = `<doc_id>#s<n>`, `level`, `parent_id`, `title`,
  `breadcrumb` ("Logement › Bail › Garantie locative"), `start_line`, `end_line` (the next peer-or-ancestor heading's
  start − 1, or the page's last line), `anchor_id`, `source` = "headings".
- `row_df` — one row per table body row: `doc_id`, `table_id`, `line_num` (of the row), `column_headers`, `row_cells`,
  `row_serialized` ("col: val | col: val").
- `cross_ref_df` — one row per internal link in body text: `doc_id`, `line_num`, `target_doc_id`, `target_anchor`,
  `context` (±30 chars).
- `corpus_index` — one row per document: `doc_id`, `url`, `title`, `topic` (housing / vehicle / liability /
  administration / health / work / money / other, by a dictionary over the title and headings, deterministic),
  `summary_line` (title + first paragraph ≤ 200 chars, deterministic), `tags` (the concepts found in it),
  `n_lines`, `lang`.
- `parse_coverage` (JSON): pages_total, pages_with_text, lines_total, sections_total, tables_total, cross_refs,
  fetched_at, index_version (sha256 of the tables), pipeline_version.

## 2. Brick 2 — question parsing (`guide_rag/question`)

`ParsedQuestion` (pydantic, saved as a row in `questions` + `parsed_questions`):
```
original_question: str
corrected_question: str            # normalize_query: lowercase, accents stripped for matching only, abbreviations
                                   # expanded (abbrev.yaml), spell-corrected against the CORPUS vocabulary
                                   # (SymSpell-like, max edit distance 2, keep the token when nothing is close)
language: Literal["fr","en","de","unknown"]
keywords: list[Keyword]            # Keyword(text, weight, source ∈ direct|expert_dictionary|anchor, concept|None,
                                   # is_regex)
                                   # direct = the user's own content words, weight 1.0, verbatim
                                   # expert_dictionary = every variant of a matched concept, weight 0.6
                                   # anchor = regex patterns (amount €, date, phone, postal code, form codes) weight 1.0
answer_shape: Literal["single","listing"]        # listing triggers: "quels", "liste", "toutes", "which", "what are"…
answer_type: Literal["text","amount","date","boolean","address","phone","url","duration"]
structural_hints: {pages_hint: list[doc_id] | None (the page the reader is on), toc_section_hint: str | None,
                   answer_context: Literal["line","paragraph","section"]}
scope_filters: {topic: str | None}
decomposition: {pattern: Literal["single","independent"], sub_questions: list[str]}   # the "et / and" test
suggested_clarification: str | None
ambiguity_reason: Literal["too_short","no_content_words","pronoun_only","single_term_multiple_concepts"] | None
candidate_values: list[str]        # for the clarification: the concepts or pages it could mean
proposed_default: str | None       # with its reason
parsing_notes: list[str]
```
`ExecutionPlan` from `dispatcher.py` (deterministic; every flag carries `on` and `reason`): `use_keywords` (always
on), `use_toc` (on when toc_df has ≥ 3 sections), `use_row_level` (on when answer_type ∈ amount/date or the question
names a table column), `use_embeddings` (off: "no vocabulary mismatch expected beyond the dictionary; keywords prove
absence"), `use_llm_arbiter` / `use_llm_generation` (on only when a key is configured), `answer_context` (line for
amount/date/boolean, paragraph for single text, section for listing), `sweep_for_absence` (always on),
`current_page_boost` (on when pages_hint).

The expert dictionary: `dictionary/concepts.yaml` (concept, definition, topic) and `dictionary/keywords.yaml`
(concept, language, keyword, priority primary|secondary, weight). Seeded with ≈ 60 concepts of the guide's domain
(logement/bail/garantie locative/caution; voiture/immatriculation/contrôle technique/permis; responsabilité civile/
RC/assurance; commune/biergercenter/inscription; CNS/sécurité sociale; impôts/fiche de retenue; …), each FR/EN (+DE
when known). Growable by pull request; `dictionary/CHANGELOG.md` records why each entry was added.

## 2b. The corpus shape: a pile of pages is one long document with a nested outline

The site's pages share no business field and rarely point at each other: the series' "pile of unrelated files"
shape. "A folder whose documents have nothing in common is one long document. The files are its chapters. Their
sections are its subsections." So the corpus is routed down two levels, never searched flat:
- **Level 0** = `corpus_index`, one line per page **written for the router**: the subject in both vocabularies (the
  words a newcomer types and the words the page uses), the shape of what the page answers (a procedure, a list of
  documents, a definition…), and what the page is NOT about. Deterministic draft from title + headings + first
  paragraph + the dictionary concepts found; hand-reviewed in `index/summary_lines.yaml` ("reviewed like schema, not
  like copy"). A keyword tally (question terms found in the summary line and the page's heading titles) runs
  alongside.
- **Level 1** = each page's own `toc_df`; the router descends into the one to three pages kept at level 0, stops at a
  leaf or a section small enough to read whole.
- The router is deterministic by default (tally + dictionary concepts + the reader's page), one reason string per
  kept page; the optional LLM router reads the 20–60 level-0 lines in one call and returns page ids with a reason
  each. Every returned line keeps its `doc_id`, so a citation always names its page.
- Hold-out test: the golden set's expected page must come back from level 0 (reported per type in the evaluation).

## 3. Brick 3 — retrieval (`guide_rag/retrieval`)

Detectors (all deterministic, run always):
- `keyword_lines`: for every keyword, the lines of `line_df` containing it (whole-word, accent-folded); a
  co-occurrence boost when ≥ 2 distinct concepts hit the same line or the same section.
- `title_match`: keywords against `toc_df.title` (a title hit is a strong anchor).
- `anchor_regex`: amount/date/phone patterns, required when answer_type asks for them ("two-signal match").
- `row_match`: keywords against `row_df.row_serialized` when `use_row_level`.
- `current_page_boost`: ×1.3 on the reader's page.

Aggregation to the structural unit (section via `section_id`), then **anchor → context**: anchor = the hit lines,
context = the paragraph (±3 lines, same section) or the section (`start_line..end_line`) per `answer_context`; the
context always contains the anchor.

The arbiter: deterministic by default (`arbiter.py` rules, each decision a sentence): title match + content
co-occurrence → primary; content co-occurrence → primary or supporting; single keyword only → tangential; a hit in a
section whose title names a different concept of the dictionary → discarded ("names X, not Y"). Optional LLM arbiter
(`llm_arbiter.py`, structured output, one call, roles with reasons) when a key is configured; its brief is the same
`CandidateBrief` table.

```
CandidateScope(doc_id, line_start, line_end, section_id)
RetrievedCandidate(candidate_id "logement#l12-l14", anchor: CandidateScope, context: CandidateScope, snippet,
                   text, methods: list[str], matched_keywords: list[str], section_title, breadcrumb, url_anchor,
                   role ∈ primary|supporting|tangential|discarded, reason: str)
RetrievalResult(question_id, question, candidates (primary first; discarded kept for the audit), methods_used,
                methods_skipped: dict[str, reason], not_found: bool, not_found_reason, confidence,
                per_section_audit: [{section_id, title, keyword: Y/., toc: Y/., kept: Y/.}])
```
`sweep.py`: the exhaustive absence sweep over every page (regex on every variant of every concept of the question;
NOT top-k): rows `(concept, variant, doc_id, line_num, snippet)`; zero rows for a concept = strong evidence of absence.

## 4. Brick 4 — generation (`guide_rag/generation`)

Schemas (pydantic):
```
Span(doc_id, line_start, line_end, quote: str | None)
TextItem(text, spans) · AmountItem(amount: Amount(value, currency, unit), spans) · DateItem(date: DateValue(iso,
original), spans) · BooleanItem(boolean, spans)
AnswerBase(extraction_method ∈ verbatim|computed|inferred|na, confidence, caveats, answer_found,
           complete_answer_found, context_structured, keywords_found, llm_discovered_keywords, conflicting_evidence,
           suggested_clarification)
TextAnswer/ListAnswer/AmountAnswer/DateAnswer/BooleanAnswer(items)
AbsenceJustification(answer=None, reason ∈ concept_not_found|concept_found_but_off_topic|ambiguous_question,
                     searched_concepts: [ConceptSearch(concept, variants, pages_with_hits, line_hits)],
                     closest_mentions: [Mention(doc_id, line_num, snippet, why_not_an_answer)],
                     parse_coverage, suggestion)
GenerationResult(answer, meta)   # meta = _meta block, below
```
`verbatim.py` (no model): the primary candidate's anchor lines become the item(s) verbatim (`extraction_method` =
"verbatim"); for amount/date the regex-captured value becomes the typed value with the line as its span
("computed" when normalised); listing → one item per matching line/list item of the section; answer_found = any
primary; complete_answer_found = the context is a whole section or the single value was found; conflicting_evidence
when two primary candidates on different pages carry different typed values.
`llm.py` (optional, OpenAI-compatible, structured output, temperature 0): BASE prompt + one shape fragment +
constraints; `fragments_applied` recorded; the model returns line numbers and typed values, never the passage.
`validator.py`: shape matches answer_shape; `bool(items) == answer_found`; every item has ≥ 1 span; every span's
lines exist in the context; line_end ≥ line_start; quote ⊂ cited lines after whitespace normalisation; verbatim ⇒ a
quote; date ISO; a failing answer is retried once with the discovered keywords, then rejected (typed not-answered).
`absence.py`: builds `AbsenceJustification` from the sweep, the coverage and the nearest hits (why_not = "names
<concept> in the <section> section, which is about <other concept>").

`_meta` on every answer: question_id, index_version, pipeline_version, methods_used, methods_skipped (with reasons),
activations (with reasons), chunk_strategy, model_used ("no model" | model id), prompt_version, fragments_applied,
iterations, validator_report, timings_ms. Persisted in `generation_meta`.

## 5. The page (`web/`)

Static (GitHub Pages). Loads `index/*.json`. A JS port (`web/engine/*.js`, ES modules, no bundler) of the
deterministic bricks 2–4 with the same function names; `tests/test_crosscheck.py` runs the golden questions through
both and asserts identical ParsedQuestion keywords, candidate ids, roles and item spans. BYO key (OpenAI-compatible
endpoint + key kept in sessionStorage only, requests go to the provider only) switches the LLM arbiter and
generation on; the trace shows which ran.

Layout (phone first, 16px gutters). The first screen is the question box and nothing else that competes with it:
one line of title, the box, three example questions as chips, the "Page que je lis" selector folded under a small
link. Everything about how it is built (the four bricks, the index, the evaluation, the plan) is one tap away in a
top bar: Poser une question · Comment ça marche · Index · Évaluation · Code. "Comment ça marche" opens the method
page (docs/METHOD.md rendered) and the plan (docs/PLAN.md), with the trace of a worked example.
1. Question box, "Page que je lis" selector (the corpus_index titles), language auto.
2. Answer card: verdict pill (Réponse / Réponse partielle / Pas dans ce guide / Précisez), items with their verbatim
   quotes, each quote a link `url#anchor` captioned "Logement › Bail · lignes 12–14"; the two booleans and the
   caveats visible; on absence the four kinds of evidence; on a vague question the one clarification with 2–3
   candidate values and the proposed default (one tap applies it).
3. Source panel: the page's `line_df` as numbered lines, the anchor highlighted, the context shaded; scope picker
   line / paragraph / section / page.
4. Trace panel (collapsible): ParsedQuestion, ExecutionPlan with reasons, RetrievalResult (candidates: methods,
   matched keywords, role, reason), the per-section audit table, `_meta`. "Copier la trace" copies the JSON.
5. Tabs: **Index** (page_df, toc_df, line_df browsable per page, the dictionary, the coverage); **Évaluation** (the
   golden set, per-type results from the committed `eval/report.json`); **Méthode** (the four bricks, each with the
   article(s) it follows, by title + link).

Everything the guide says is rendered as text (textContent), never injected HTML.

## 6. Evaluation (`guide_rag/eval`)

`eval/golden.yaml`: ≈ 40 questions labelled by type: factual, listing, amount, date, yes/no, address/phone, typo,
EN, DE, on-page (pages_hint), compound, vague, out-of-scope (not in the guide). Each with the expected doc_id and
section (and line range when exact), or `expected: absent`. `run.py` produces `eval/report.json` + `report.md`:
per type, retrieval hit rate (expected section ∈ primary candidates), answer_found rate, quote-fidelity rate
(validator), not-found correctness, clarification fire rate, median latency. CI fails if any quote fails the
validator or any cross-check mismatches.

## 7. Repository layout, CI, docs

```
guide_rag/ (package)  web/ (page)  index/ (built JSON + coverage)  raw/ (fetched HTML, hashed)  traces/ (golden
traces with and without model)  dictionary/  eval/  tests/  docs/ARCHITECTURE.md  docs/METHOD.md (brick → articles)
README.md  pyproject.toml  .github/workflows/ci.yml (pytest, build index, eval, cross-check, deploy Pages)
```
CLI: `guide-rag build` (fetch + tables + export), `guide-rag ask "…" [--page logement] [--llm]`, `guide-rag eval`,
`guide-rag trace <question_id>` (replay).
