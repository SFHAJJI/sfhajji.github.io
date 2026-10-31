# Guide RAG: a "chatbot documentaire" for newcomers, built exactly the way the series prescribes

Plan of 2026-10-31. Target: a public repository `SFHAJJI/guide-rag` and its page at
https://sfhajji.github.io/guide-rag/. The series is cited by its name ("Enterprise Document Intelligence", Towards
Data Science) with links to the articles ([series-articles.md](series-articles.md)).

## 1. What the series prescribes (the checklist the demo must visibly meet)

Read in full on 2026-10-31: 43 articles of the series (both authors) plus the public companion code
(`doc-intel/notebooks-vol1`, read for understanding only; its licence forbids reuse, nothing is copied).

Four bricks, typed handoffs, saved between steps: document parsing, question parsing, retrieval, generation
("Each brick says what it takes in and what it gives back; what we pass from one brick to the next is what we save").

**The index is built, and it is relational.** "A good PDF parser does not extract text. It models the document as a
relational set of tables." Tables and their columns, as the series names them:

| table | one row per | columns (series) | our web equivalent |
|---|---|---|---|
| `line_df` | visible line, **the citation unit** | page_num, line_num, text, x0 y0 x1 y1, font, column_position, content_type, parsing_method | doc_id (page slug), line_num (global in the page), text, element (h1/h2/h3/p/li/tr/td), anchor_id, css_path, char_count |
| `toc_df` | section | toc_idx, level, parent_idx, title, start_page, end_page, start_y, breadcrumb, source | section_id, level, parent, title, breadcrumb, start_line, end_line (next peer or ancestor), anchor |
| `page_df` | page | page_num, text, page_type, flags, n_lines | one row per web page: doc_id, url, title, lang, n_lines, n_sections, fetched_at, last_modified, content_sha256 |
| `corpus_index` | document of the corpus | doc_id, the business fields, a one-line summary, page refs | doc_id, url, title, topic (housing / vehicle / liability / …), summary line (deterministic: title + first paragraph), tags |
| `row_df` | table row | table_id, page_num, line_num, column_headers, row_cells, row_serialized | same, from HTML tables ("col: val \| col: val") |
| `cross_ref_df` | internal reference | ref_type, ref_id, page_num, line_num, context | internal links "voir la page X" → doc_id, anchor |
| `concepts_df` + `concept_keywords_df` | concept / (concept, language, keyword) | concept, definition, document family; keyword, priority, weight | the expert dictionary, FR / EN / DE / LB variants, editable in the repo |
| `questions`, `parsed_questions`, `retrieved`, `answers`, `generation_meta` | per question | question_id = hash, parsed_json, retrieved rows, answer_json, model_used, meta_json | the same, as the audit trail |

Storage: SQLite built once at ingestion (`guide.sqlite`), exported to JSON for the page. "You open the PDF once. After
that, you only work with tables." Every table carries `parsing_method` / `source` provenance; the raw HTML is kept
by content hash with `fetched_at`.

**The question becomes a typed row before any search.** `ParsedQuestion`: original_question, corrected_question
(spell-corrected against the corpus vocabulary), language, keywords[] each with `source` ∈ direct / expert_dictionary /
anchor and a weight, answer_shape ∈ single / listing, answer_type ∈ text / amount / date / boolean / address / phone /
url, structural_hints (pages_hint = the page the reader is on; toc_section_hint), decomposition (single / independent),
suggested_clarification + ambiguity_reason. A deterministic **dispatcher** writes an `ExecutionPlan` with one logged
reason per activation (use_toc, use_keywords, use_row_level, use_embeddings=false and why, answer_context ∈ line /
paragraph / section). "The selection happens deterministically in Python. The LLM inherits the choice and executes it."

**Retrieval is filtering, not search.** Keyword detectors on `line_df` (co-occurrence boost, anchor regex for amounts,
dates, codes) and title match on `toc_df`, run always; aggregation to the section via the section_id join; **anchor**
(the matching lines) and **context** (the section) returned as a typed pair, the context always containing the anchor;
one arbiter at the end ranks candidates with a role (primary / supporting / tangential / discarded) and a one-line
reason; embeddings absent by design with the reason logged. Output: `RetrievalResult {doc_id, question, candidates[
{candidate_id, anchor, context, snippet, methods, matched_keywords, section_title, role, reason}], methods_used,
not_found, not_found_reason, confidence}`. "Keywords prove absence; embeddings cannot."

**Generation fills a typed schema, never prose.** `items[]` each with its own `spans[{doc_id, line_start, line_end,
quote}]`; `extraction_method` ∈ verbatim / computed / inferred / na; `answer_found`, `complete_answer_found`,
`caveats`, `keywords_found`, `llm_discovered_keywords`, `conflicting_evidence`, `suggested_clarification`. The
displayed passage is **recovered from `line_df` by line ids**, the model's quote only used as a check. A validator
checks quote ⊂ cited lines, spans ⊂ context, contiguity, boundaries; what fails is not shipped.

**"Not in this guide" shows four kinds of evidence**: parse coverage (pages, lines, sections, fetched when),
the concept set searched with every variant and its hit counts, the exhaustive sweep (not top-k), the closest
mentions with "why this is not an answer", a suggestion. **Vague question: clarify once**, with candidate values
and a proposed default, never a chat loop.

**The path is always returned.** Every answer and every candidate points back doc → page → section breadcrumb
→ line_start..line_end → verbatim quote, and the trace says which methods found it, the role, the reason, the
model (or "no model"), the prompt version, the index version. "The citation is part of the answer, not an analysis
layer added on top." "The trace is the explanation."

**Evaluation measures the process, per question type**, never one aggregate: a labelled set by type (factual,
listing, amount, yes/no, typo, EN/FR, compound, vague, out of scope), retrieval hit rate per type, not-found rate,
clarification fire rate, quote-fidelity rate.

**Amplify the expert**: the dictionary and the golden set are the expert's assets; the system shows its work
so the expert can dispute the parse, the keyword set or the closest mention.

## 2. What the current demo (sfhajji.github.io/guide/) has and lacks

Has: structure-first parsing by heading, a synonym dictionary before any model, a typed verdict (found / two pages /
clarify / not in guide), the passage highlighted, the current-page boost, no vector store. Lacks, against the
checklist: no visible relational index (sections are in memory, no line ids, no toc table, no corpus index); BM25
ranking where the series prescribes filtering + co-occurrence; a verdict computed from scores, not a `RetrievalResult`
with anchor/context, roles and reasons; no `ParsedQuestion` row, no dispatcher with reasons; no typed answer with
items and spans, no `extraction_method`; "not in guide" without the four kinds of evidence; no audit trail
(`_meta`), no replay; no evaluation page; no package (one JS file). It is a good seed, not the deliverable.

## 3. The deliverable

**Repository `SFHAJJI/guide-rag`** (public, MIT), modular packaged code, "the pipeline you read is the pipeline
that runs":

```
guide_rag/                  Python package, the pipeline of record (pip install -e .)
  parsing/   fetch.py (sitemap + links, content hash, fetched_at), html_tables.py (line_df, toc_df, page_df,
             row_df, cross_ref_df), corpus_index.py, coverage.py
  question/  spelling.py (corpus-vocabulary correction), dictionary.py (concepts_df, concept_keywords_df),
             parse_question.py (ParsedQuestion), dispatcher.py (ExecutionPlan with reasons), clarify.py
  retrieval/ detectors.py (keyword, title, anchor regex, co-occurrence), scope.py (anchor → context),
             arbiter.py (deterministic rules; LLM arbiter optional), result.py (RetrievalResult), sweep.py
  generation/ schemas.py (Span, items, AnswerBase family, AbsenceJustification), verbatim.py (no model:
             extraction_method=verbatim by code), llm.py (optional, OpenAI-compatible, structured output),
             validator.py (8C checks), absence.py (four kinds of evidence)
  storage/   sqlite.py (the tables above + the audit tables), export_json.py (for the page)
  eval/      golden.yaml (≈40 labelled questions by type), run.py, report.md
  cli.py     guide-rag build | ask "…" [--page …] [--llm] | eval | export
web/                        the page (static, GitHub Pages): loads index/*.json, runs the same deterministic
                            bricks in JS (ported, cross-checked against the Python traces in CI), BYO key for the
                            optional LLM arbiter/generation (key kept in sessionStorage only, never sent anywhere
                            but the provider)
index/                      the built index (JSON) + build-report.json (coverage, versions, hashes)
traces/                     committed, replayable traces of the golden set (parsed question, plan, retrieval,
                            answer, meta) — with and without the model
docs/                       ARCHITECTURE.md (the four bricks, every table and field), EVALUATION.md, the
                            series articles each brick follows (by title + link)
tests/                      pytest on every brick + JS tests on the port; CI builds the index, runs the golden set,
                            fails on any quote-fidelity or cross-check mismatch
```

**The page** (https://sfhajji.github.io/guide-rag/): question box + "page I am reading" selector →
(1) the typed answer card: verdict pill (answer / partial / not in the guide / please clarify), the items with
their verbatim quotes, each quote linking to the page and anchor and naming "Logement › Bail › lines 12–14";
(2) the source panel: the page's `line_df` made visible, anchor lines highlighted, context shaded, a scope picker
anchor / paragraph / section / page; (3) the trace panel: ParsedQuestion, the dispatcher's flags with reasons, the
RetrievalResult (candidates with methods, matched keywords, role, reason), the per-section audit table (keyword
Y/·, TOC Y/·, kept Y/·), `_meta` (methods_used, model or "no model", prompt_version, index version); on absence,
the four kinds of evidence; on a vague question, the one clarification with candidates and the proposed default.
Two more tabs: **Index** (the tables, browsable: pages, sections, lines, dictionary, coverage) and **Evaluation**
(the golden set with per-type results from the last CI run).

## 4. Order of work (Saturday 11:00 → Sunday 20:00)

1. Python package: fetch + parsing tables + SQLite + JSON export, build report (Sat afternoon).
2. Question parsing + dictionary + dispatcher + clarification; retrieval detectors, scope, deterministic arbiter,
   RetrievalResult, sweep; verbatim generation + validator + absence (Sat evening).
3. Golden set + eval + traces; optional LLM bricks behind a flag (Sat night).
4. The page: JS port of the deterministic bricks, cross-check test against the Python traces, the three panels,
   Index and Evaluation tabs (Sun morning).
5. Docs, README, CI, Pages; link from the portfolio and the profile README; the reply e-mail updated (Sun afternoon).

Each step is a PR on the new repo with the evidence in its description (counts, tests). The existing guide demo stays
until the new page is live, then redirects to it.
