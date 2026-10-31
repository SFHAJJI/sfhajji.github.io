// Port of guide_rag/retrieval/router.py: the two-level router of SPEC §2b, pages first
// (corpus_index), then each kept page's own outline. Deterministic, one reason string per kept
// page and per stopped section.

import { _s, pyFixed, pyFloatRepr, pyRound, pySum, sortedBy, sortedStrings } from "./_py.js";
import { as_tables, concept_keys, concept_words, content_words, coverage, hints, plan_activation } from "./contracts.js";
import { CURRENT_PAGE_FACTOR } from "./detectors.js";
import { concept_label, fold, phrase_in, stems } from "./text.js";

export const MAX_PAGES = 3;
export const MIN_SHARE_OF_BEST = 0.34; // a page far behind the best one is noise, not a second chapter
export const SMALL_SECTION_LINES = 12; // a section this small is read whole; no descent below it
export const MAX_SECTIONS_PER_LEVEL = 3;
export const DOC_TITLE_BONUS = 2.0; // a document whose title covers the question's words is its chapter
export const DOC_TITLE_COVERAGE = 0.5;

/** doc_id -> document title, from corpus_index, page_df or the h1 of toc_df. */
export function doc_titles(t) {
  const titles = new Map();
  for (const df of [t.corpus_index, t.page_df]) {
    if (df && df.length && "title" in df[0]) for (const r of df) if (!titles.has(String(r.doc_id))) titles.set(String(r.doc_id), _s(r.title));
  }
  if (t.toc_df && t.toc_df.length) {
    for (const r of sortedBy(t.toc_df, (r) => [r.doc_id, r.start_line])) if (!titles.has(String(r.doc_id))) titles.set(String(r.doc_id), _s(r.title));
  }
  return titles;
}

/** The concept ids a page's tags name: a tag is a concept id, its label, or one of its variants. */
export function tag_concepts(tags, variants_by_concept) {
  const lookup = new Map();
  const setdefault = (k, v) => {
    if (!lookup.has(k)) lookup.set(k, v);
  };
  for (const [concept, variants] of Object.entries(variants_by_concept)) {
    setdefault(fold(concept), concept);
    setdefault(fold(concept_label(concept)), concept);
    for (const v of variants) setdefault(fold(v), concept);
  }
  const found = new Set();
  for (const tag of tags) {
    const c = lookup.get(fold(tag));
    if (c) found.add(c);
    else found.add(tag); // an unknown tag still matches a question term spelled the same way
  }
  return found;
}

export function RoutedPage(doc_id, score, reason, matched_terms = []) {
  return { doc_id, score, reason, matched_terms };
}

export function RoutedSection(doc_id, section_id, title, breadcrumb, start_line, end_line, level, score, reason, matched_terms = [], is_leaf = true) {
  return { doc_id, section_id, title, breadcrumb, start_line, end_line, level, score, reason, matched_terms, is_leaf };
}

export function RouteResult(pages, sections, page_scores, notes = []) {
  return { pages, sections, page_scores, notes };
}

/** The terms whose phrase appears in the text (whole words, stems). */
export function _tally_text(text, terms) {
  const ts = stems(text);
  return terms.filter((t) => !t.is_regex && stems(t.text).length && phrase_in(stems(t.text), ts));
}

export function _page_titles(toc_df, doc_id) {
  if (!toc_df || toc_df.length === 0) return [];
  return toc_df.filter((r) => r.doc_id === doc_id).map((r) => _s(r.title));
}

export function _tags(value) {
  if (value === null || value === undefined || (typeof value === "number" && Number.isNaN(value))) return [];
  if (typeof value === "string") return value.replace(/;/g, ",").split(",").map((v) => v.trim()).filter((v) => v);
  return Array.from(value, (v) => String(v));
}

/** Level 0: tally the question terms over every page's summary line, headings, tags and title. */
export function route_level0(parsed, tables, terms, max_pages = MAX_PAGES, variants_by_concept = null) {
  const t = as_tables(tables);
  const [pages_hint] = hints(parsed);
  const q_concepts = new Set(concept_keys(terms));
  variants_by_concept = variants_by_concept || {};
  const words = content_words(terms, variants_by_concept);
  const index = t.corpus_index;
  let rows;
  if (!index || index.length === 0) {
    // Without a corpus index the pages come from page_df or line_df; the tally reads headings only.
    const src = t.page_df && t.page_df.length ? t.page_df : t.line_df;
    const doc_ids = src && src.length ? sortedStrings(src.map((r) => r.doc_id)) : [];
    rows = doc_ids.map((d) => ({ doc_id: d, title: "", summary_line: "", tags: [] }));
  } else {
    rows = sortedBy(index, (r) => [r.doc_id]);
  }

  const scored = [];
  for (const row of rows) {
    const doc_id = String(row.doc_id);
    const parts = [];
    let matched = [];
    let score = 0.0;
    const summary_terms = _tally_text(_s(row.summary_line) + " " + _s(row.title), terms);
    if (summary_terms.length) {
      score += pySum(summary_terms.map((x) => x.weight));
      matched = matched.concat(summary_terms.map((x) => x.text));
      parts.push(`${summary_terms.length} term(s) in the summary line (${summary_terms.map((x) => x.text).join(", ")})`);
    }
    const title_terms = new Map();
    for (const title of _page_titles(t.toc_df, doc_id)) {
      for (const x of _tally_text(title, terms)) {
        if (!title_terms.has(x.text)) title_terms.set(x.text, []);
        title_terms.get(x.text).push(title);
      }
    }
    if (title_terms.size) {
      score += pySum(Array.from(title_terms.keys(), (k) => terms.find((x) => x.text === k).weight));
      matched = matched.concat(Array.from(title_terms.keys()).filter((k) => !matched.includes(k)));
      const titles = sortedStrings(Array.from(title_terms.values()).flat());
      parts.push(`heading title match (${titles.join(", ")})`);
    }
    const tag_hits = sortedStrings(Array.from(tag_concepts(_tags(row.tags), variants_by_concept)).filter((c) => q_concepts.has(c)));
    if (tag_hits.length) {
      score += 1.0 * tag_hits.length;
      parts.push(`concept(s) in tags (${tag_hits.map(concept_label).join(", ")})`);
    }
    // "Trust the TOC": a document titled with the question's words is its chapter.
    const [doc_cov] = words.length ? coverage(concept_words(words), [stems(_s(row.title))]) : [0.0, [], []];
    if (doc_cov >= DOC_TITLE_COVERAGE) {
      score += DOC_TITLE_BONUS * doc_cov;
      parts.push(`document title '${_s(row.title)}' covers ${pyFixed(doc_cov, 2)} of the question's words`);
    }
    if (pages_hint.includes(doc_id)) {
      if (score === 0) {
        score = 0.5; // the reader's page is always a candidate chapter
        parts.push("the reader's page, no term found");
      } else {
        score *= CURRENT_PAGE_FACTOR;
        parts.push(`the reader's page x${pyFloatRepr(CURRENT_PAGE_FACTOR)}`);
      }
    }
    if (score > 0) scored.push(RoutedPage(doc_id, pyRound(score, 3), parts.join("; "), sortedStrings(matched)));
  }

  const page_scores = {};
  for (const p of scored) page_scores[p.doc_id] = p.score;
  const ranked = sortedBy(scored, (p) => [-p.score, p.doc_id]);
  const kept = [];
  const best = ranked.length ? ranked[0].score : 0.0;
  for (const p of ranked) {
    if (kept.length >= max_pages) break;
    if (p.score < best * MIN_SHARE_OF_BEST) break;
    p.reason = `kept: ${p.reason}; tally ${pyFloatRepr(p.score)}`;
    kept.push(p);
  }
  return [kept, page_scores];
}

export function _page_toc(toc_df, doc_id) {
  if (!toc_df || toc_df.length === 0) return [];
  return sortedBy(toc_df.filter((r) => r.doc_id === doc_id), (r) => [r.start_line]);
}

/** Level 1: descend the page's outline; stop at a leaf or a section of <= `small` lines. */
export function route_level1(parsed, tables, doc_id, terms, hits, small = SMALL_SECTION_LINES) {
  const t = as_tables(tables);
  const toc = _page_toc(t.toc_df, doc_id);
  if (!toc.length) return [];
  const [, toc_hint] = hints(parsed);
  const ids = new Set(toc.map((r) => String(r.section_id)));
  const children = new Map(); // parent id (or null) -> rows
  for (const r of toc) {
    const parent = _s(r.parent_id) || null;
    const key = parent !== null && ids.has(parent) ? parent : null;
    if (!children.has(key)) children.set(key, []);
    children.get(key).push(r);
  }
  // Hits of this page grouped by line, so a section's tally is the distinct terms in its range.
  const line_terms = new Map();
  for (const h of hits) {
    if (h.doc_id === doc_id && (h.method === "keyword_lines" || h.method === "row_match")) {
      if (!line_terms.has(h.line_num)) line_terms.set(h.line_num, new Set());
      line_terms.get(h.line_num).add(h.keyword);
    }
  }

  const tally = (r) => {
    const title = _s(r.title);
    const title_terms = _tally_text(title, terms).map((x) => x.text);
    const start = Number(r.start_line);
    const end = Number(r.end_line);
    const body_terms = new Set();
    for (const [ln, ts] of line_terms) if (start <= ln && ln <= end) for (const x of ts) body_terms.add(x);
    let score = 2.0 * title_terms.length + body_terms.size;
    if (toc_hint && phrase_in(stems(toc_hint), stems(title))) {
      score += 2.0;
      title_terms.push(`hint:${toc_hint}`);
    }
    return [score, title_terms, sortedStrings(body_terms)];
  };

  const descend = (nodes) => {
    const scored = nodes.map((r) => [tally(r), r]);
    const best = scored.length ? Math.max(...scored.map(([s]) => s[0])) : 0.0;
    if (best <= 0) return [];
    const chosen = scored.filter(([s]) => s[0] > 0 && s[0] >= 0.5 * best).slice(0, MAX_SECTIONS_PER_LEVEL);
    const out = [];
    for (const [[score, title_terms, body_terms], r] of chosen) {
      const sid = String(r.section_id);
      const start = Number(r.start_line);
      const end = Number(r.end_line);
      const size = end - start + 1;
      const kids = children.get(sid) || [];
      const why = [];
      if (title_terms.length) why.push(`title '${_s(r.title)}' matches ${title_terms.join(", ")}`);
      if (body_terms.length) why.push(`${body_terms.length} term(s) in its lines (${body_terms.join(", ")})`);
      const base = RoutedSection(doc_id, sid, _s(r.title), _s(r.breadcrumb), start, end, Number(r.level ?? 1) || 1, pyRound(score, 3), "", title_terms.concat(body_terms), !kids.length);
      // A child whose title names a term is a better stop than a small parent read whole.
      const kid_title_hit = kids.some(
        (k) => _tally_text(_s(k.title), terms).length > 0 || (toc_hint && phrase_in(stems(toc_hint), stems(_s(k.title)))),
      );
      if (!kids.length) {
        base.reason = why.join("; ") + "; a leaf, stop here";
        out.push(base);
      } else if (size <= small && !kid_title_hit) {
        base.reason = why.join("; ") + `; ${size} lines, small enough to read whole`;
        out.push(base);
      } else {
        const below = descend(kids);
        if (below.length) out.push(...below);
        else {
          base.reason = why.join("; ") + "; no child section carries a term, read whole";
          out.push(base);
        }
      }
    }
    return out;
  };

  const result = descend(children.get(null) || []);
  return sortedBy(result, (s) => [-s.score, s.start_line]);
}

/** Both levels. `hits_by_doc` (keyword hits per page) sharpens level 1 when given. */
export function route(parsed, plan, tables, terms, hits_by_doc = null, variants_by_concept = null) {
  const [kept, page_scores] = route_level0(parsed, tables, terms, MAX_PAGES, variants_by_concept);
  const notes = [];
  const sections = [];
  const use_toc = plan !== null && plan !== undefined ? plan_activation(plan, "use_toc")[0] : true;
  if (!kept.length) notes.push("level 0 kept no page: no term of the question in any summary line, heading or tag");
  for (const p of kept) {
    if (use_toc === false) {
      notes.push(`${p.doc_id}: use_toc is off, the page is read whole`);
      continue;
    }
    const secs = route_level1(parsed, tables, p.doc_id, terms, (hits_by_doc && hits_by_doc.get ? hits_by_doc.get(p.doc_id) : hits_by_doc?.[p.doc_id]) || []);
    if (!secs.length) notes.push(`${p.doc_id}: no section of the outline carries a term; the page is read whole`);
    sections.push(...secs);
  }
  return RouteResult(kept, sections, page_scores, notes);
}
