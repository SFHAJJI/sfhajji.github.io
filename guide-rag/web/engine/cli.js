// Port of guide_rag/generation/cli.py's `load_tables` and `ask`: the four bricks end to end on the
// built index, model-free unless a client is given. Environment-neutral: the caller fetches the
// JSON (the browser with fetch, node from disk) and passes it here.

import { Tables } from "./contracts.js";
import { Abbreviations, Dictionary, WeakWords, parse_question, set_weak_words as set_parser_weak_words, vocabulary_for } from "./parse_question.js";
import { dispatch } from "./dispatcher.js";
import { answer_question } from "./pipeline.js";
import { set_weak_words as set_text_weak_words } from "./text.js";

/** The brick-1 tables from the loaded index JSON ({line_df, toc_df, row_df, corpus_index, page_df, cross_ref_df, coverage}). */
export function load_tables(index) {
  const coverage = index.coverage || null;
  return new Tables({
    line_df: index.line_df,
    toc_df: index.toc_df,
    row_df: index.row_df ?? null,
    corpus_index: index.corpus_index ?? null,
    page_df: index.page_df ?? null,
    cross_ref_df: index.cross_ref_df ?? null,
    parse_coverage: coverage,
    index_version: coverage ? coverage.index_version ?? null : null,
  });
}

/** The dictionary assets from web/data/dictionary.json: the Dictionary, the Abbreviations and the WeakWords (installed for retrieval too). */
export function load_dictionary(data) {
  const dictionary = Dictionary.load(data);
  const abbreviations = Abbreviations.load(data.abbreviations);
  const weak = WeakWords.load(data.weak_words);
  set_parser_weak_words(weak);
  set_text_weak_words(weak);
  return { dictionary, abbreviations, weak };
}

/** One question through the four bricks; returns {result, parsed, plan}. */
export async function ask(question, { tables, assets, page = null, llm_client = null }) {
  const { dictionary, abbreviations, weak } = assets;
  const parsed = parse_question(question, {
    line_df: tables.line_df,
    toc_df: tables.toc_df,
    corpus_index: tables.corpus_index,
    dictionary,
    current_page: page,
    vocabulary: vocabulary_for(tables.line_df, dictionary),
    abbreviations,
    weak,
  });
  const plan = dispatch(parsed, { toc_df: tables.toc_df, llm_available: llm_client !== null, row_df: tables.row_df });
  const result = await answer_question(parsed, plan, tables, dictionary, { llm_client, index_version: tables.index_version });
  return { result, parsed, plan };
}
