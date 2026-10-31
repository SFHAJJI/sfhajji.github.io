# The method, brick by brick

This project follows the Towards Data Science series *Enterprise Document Intelligence* (2026), which builds
enterprise RAG from four bricks with typed contracts between them. The full list of articles is in
[series-articles.md](series-articles.md). Below, what each brick of `guide-rag` takes from the series, with the
article(s) it follows, and what the page shows to prove it.

## The rules we hold ourselves to

| rule | where it comes from | where you can see it |
|---|---|---|
| The corpus becomes relational tables, keyed by shared ids; the line is the citation unit | *Stop Returning Flat Text from a PDF: The Relational Tables RAG Needs* (5B); *Beyond extract_text* (5A) | Index tab: `page_df`, `line_df`, `toc_df`, `row_df`, `cross_ref_df` |
| A pile of unrelated documents is one long document with a nested outline: one summary line per document, then each document's own outline | *Multi-Document RAG: A Folder of Unrelated PDFs Is One Long Document with a Nested Outline* (14B); *Three Kinds of RAG Corpus* (14A) | Index tab: `corpus_index` with the summary lines; trace: the level-0 and level-1 routing with a reason per kept page |
| Parse the question before you search: a typed row, not a string | *Parse the question before you search* (6A); *Five fields RAG should extract from any question* (6B) | Trace: `ParsedQuestion` |
| Spell-correct against the corpus vocabulary, expand with the expert dictionary, never with a bigger model | *Noisy Text in RAG* (B1); *Embeddings Aren't Magic* (2); *Expert dictionaries beat better embedding models* (M3) | Trace: `corrected_question`, keywords tagged `direct` / `expert_dictionary` / `anchor`; Index tab: the dictionary |
| A deterministic dispatcher decides what runs, with a logged reason per flag | *Dispatching the Parsed RAG Question* (6C); *10 Positions for Enterprise RAG* (M3, position 7) | Trace: `ExecutionPlan` |
| Retrieval is filtering, not search; keywords always run, the outline is a first-class signal, embeddings come last (here: not at all, and the reason is logged) | *Retrieval Is Filtering, Not Search* (7A); *6 common RAG retrieval mistakes* (7ter); *Finding the Right Anchor* (7B) | Trace: `methods_used`, `methods_skipped` with reasons; the per-section audit table |
| Anchor small, context large, returned as a typed pair | *Retrieval Is Filtering, Not Search* (7A); *An LLM as arbiter in RAG retrieval* (7C) | Source panel: the anchor highlighted inside the shaded context; scope picker |
| Every candidate carries its provenance: methods, matched keywords, section, role, reason | *An LLM as arbiter in RAG retrieval* (7C) | Trace: `RetrievalResult.candidates` |
| Generation fills a typed schema; two booleans; the shown passage is recovered from the index by line ids, the model's quote is only a check | *Stop Returning Text from RAG: The Typed Answer Contract* (8A); *Most RAG Hallucinations Are Extraction Errors* (8ter) | Answer card: items with spans and verbatim quotes; `answer_found`, `complete_answer_found` |
| The prompt is a fixed base plus the fragments the question needs; temperature 0; the trace records which | *Prompt engineering for RAG generation: build each prompt from reusable parts* (8B) | Trace: `prompt_version`, `fragments_applied` (when a model is used) |
| Validate before showing: spans exist, quotes are substrings of the cited lines; what fails is not shipped | *Validating the RAG Answer Before the User Sees It* (8C) | Trace: `validator_report` |
| "Not in this guide" shows four kinds of evidence; keywords prove absence, embeddings cannot | *A RAG That Says "Not in This Document" Has to Show Four Kinds of Evidence* (B3) | Answer card on absence: coverage, concepts searched with hit counts, the sweep, closest mentions with why-not |
| Vague question: clarify once, propose a default, never a chat loop | *When RAG Users Ask Vague Questions: Clarify Once, Learn the Default* (6bis); *Loop Engineering for RAG Question Parsing* (6quinquies) | Answer card: the one clarification with candidate values and a proposed default |
| Call the model less: deterministic first, model only when the retrieval margin is flat | *Cut an Enterprise RAG Pipeline's Latency and Cost by Calling the LLM Less* (9ter) | Trace: `model_used` = "no model" on most questions; the route label |
| Evaluate per question type, never one aggregate; every answer replayable from its trace | *RAG Is Not Machine Learning* (3); *Prompt, Context, Loop* (M2) | Évaluation tab; `guide-rag trace <question_id>` |
| Amplify the expert: the dictionary and the golden set are the expert's assets; the system shows its work so the expert can dispute it | *Amplify the Expert: A Philosophy for Building Enterprise RAG* (M1) | The dictionary and the summary lines are plain YAML, changed by pull request |

## What is deliberately not here

- No vector store and no embeddings: the guide is small, its vocabulary is covered by the dictionary, and a keyword
  zero is an honest absence. The dispatcher logs this choice on every question.
- No autonomous agent: every route is a rule you can read in `guide_rag/question/dispatcher.py`.
- No model on the default path: the typed contract is filled by code from the anchor lines ("verbatim"). A model
  (bring your own key) can take the arbiter and generation roles under the same contract and the same validator.
