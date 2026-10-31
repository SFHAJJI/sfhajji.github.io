// Port of guide_rag/retrieval/arbiter.py: the deterministic arbiter of SPEC §3, a role and one
// reason sentence per candidate. The rules are the Python docstring's, in order:
// 1. a section whose title names another dictionary concept, with no co-occurrence and no title
//    match -> discarded ("names X, not Y"); when the question has a scope topic, such a section on a
//    page of another topic is discarded even with a co-occurrence as soon as an eligible candidate
//    sits on a page of the question's topic;
// 2. the answer type asks for a typed anchor: among candidates that cover the question equally and
//    sit in equally titled sections, the ones carrying it rank first ("two-signal match"); when the
//    best section carries none, it stays primary and the typed value is reported missing;
// 3. the coverage rule: the question's words must be covered above COVERAGE_MIN with one strong word;
// 4. ranking: an exact-titled chapter first (a sub-section whose heading is made of the reader's
//    words and which holds the page's best-covering candidate), then (coverage, document-title
//    tier, section-title tier, anchor, section-title coverage, page tally, score); a section whose
//    own lines link to another document that covers the question as well defers to it (the pointer
//    rule); among equals the router's level-0 page tally decides; the best is primary, as are the
//    ones of the same coverage and tiers within PRIMARY_SHARE of its score;
// 5. a primary also needs a title, a co-occurrence, or a one-strong-word question;
// 6. the rest: supporting when backed by a title or a co-occurrence, tangential otherwise.

import { pyFixed, pyFloatRepr, pyRound, sortedBy, uniq } from "./_py.js";
import { concept_label, phrase_in, stems } from "./text.js";

export const PRIMARY_SHARE = 0.8; // a candidate of the same tier and coverage this close to the best one is a primary too
export const PAGE_SHARE = 0.5; // ... provided the router ranks its page at least this close to the best page
export const COVERAGE_MIN = 0.34; // the share of the question's words a primary must cover
export const TITLE_COVERAGE = 0.5; // a title that covers this much of the question's words is "an exact title match"

/** What the arbiter reads about a candidate; the LLM arbiter would read the same table. */
export class CandidateBrief {
  constructor(fields) {
    this.candidate_id = fields.candidate_id;
    this.doc_id = fields.doc_id;
    this.section_id = fields.section_id ?? null;
    this.section_title = fields.section_title ?? "";
    this.matched_keywords = fields.matched_keywords ?? [];
    this.matched_concepts = fields.matched_concepts ?? [];
    this.title_keywords = fields.title_keywords ?? [];
    this.co_occurrence = fields.co_occurrence ?? null; // "line" | "section" | null
    this.required_anchor = fields.required_anchor ?? null; // the anchor kind the answer type asks for
    this.has_required_anchor = fields.has_required_anchor ?? false;
    this.score = fields.score ?? 0.0;
    this.coverage = fields.coverage ?? 1.0;
    this.covered = fields.covered ?? [];
    this.uncovered = fields.uncovered ?? [];
    this.strong_covered = fields.strong_covered ?? true;
    this.title_coverage = fields.title_coverage ?? 0.0; // of the question's concept words, by the section title
    this.doc_title_coverage = fields.doc_title_coverage ?? 0.0; // of the question's concept words, by the document title
    this.doc_title = fields.doc_title ?? "";
    this.points_to = fields.points_to ?? []; // documents the section's own lines link to ("Voir la fiche")
    this.page_score = fields.page_score ?? 0.0; // the level-0 tally of the candidate's page: the router's chapter wins among equals
    this.title_exact = fields.title_exact ?? false; // every content word of the section title is a word the reader typed
    this.section_start = fields.section_start ?? 0;
    this.section_end = fields.section_end ?? 0;
    this.anchor_start = fields.anchor_start ?? 0;
    this.exact_chapter = fields.exact_chapter ?? false; // set by decide(): exact title and the section holds the page's best-covering candidate
    this.page_topic = fields.page_topic ?? null; // corpus_index.topic of the candidate's page
    this.topic_match = fields.topic_match ?? 0; // set by decide(): 1 when the page topic is the question's scope topic
  }

  contains_anchor_of(other) {
    return other.doc_id === this.doc_id && this.section_start <= other.anchor_start && other.anchor_start <= this.section_end;
  }

  get doc_tier() {
    return this.doc_title_coverage >= TITLE_COVERAGE ? 1 : 0;
  }

  get section_tier() {
    return this.title_coverage >= TITLE_COVERAGE ? 1 : 0;
  }

  /** 3: document and section titles name the question; 2: the document title; 1: the section title; 0: none. */
  get title_tier() {
    return 2 * this.doc_tier + this.section_tier;
  }

  /** 1 when the answer type asks for no typed anchor or the lines carry it ("two-signal match"). */
  get anchor_ok() {
    return !this.required_anchor || this.has_required_anchor ? 1 : 0;
  }

  /**
   * An exact-titled chapter first ("trust the TOC"); then a page whose topic is the question's
   * scope topic; then how much of the question the candidate covers; among equals the document
   * title, then the section title; then the typed anchor the answer type asks for; then the
   * section title's own coverage; then the router's level-0 page tally; then the score.
   */
  get rank_key() {
    return [this.exact_chapter ? 1 : 0, this.topic_match, pyRound(this.coverage, 2), this.doc_tier, this.section_tier, this.anchor_ok, pyRound(this.title_coverage, 2), pyRound(this.page_score, 2), this.score];
  }

  same_rank_class(other) {
    return (
      this.exact_chapter === other.exact_chapter &&
      this.topic_match === other.topic_match &&
      pyRound(this.coverage, 2) >= pyRound(other.coverage, 2) - 0.01 &&
      this.anchor_ok === other.anchor_ok &&
      this.doc_tier === other.doc_tier &&
      this.section_tier === other.section_tier
    );
  }
}

export function Decision(role, reason) {
  return { role, reason };
}

/** The dictionary concepts a section title names (whole-phrase match on any variant). */
export function title_concepts(title, variants_by_concept) {
  const ts = stems(title);
  const found = [];
  for (const [concept, variants] of Object.entries(variants_by_concept)) {
    for (const v of variants) {
      const vs = stems(v);
      if (vs.length && phrase_in(vs, ts)) {
        found.push(concept);
        break;
      }
    }
  }
  return found;
}

export function _join(items) {
  items = uniq(items);
  if (!items.length) return "";
  if (items.length === 1) return `'${items[0]}'`;
  return items.slice(0, -1).map((x) => `'${x}'`).join(", ") + ` and '${items[items.length - 1]}'`;
}

/**
 * Roles for every candidate; deterministic, reasons as sentences. `present_concepts` are the
 * question concepts that hit at least one line of the kept pages; `n_strong_present` the number of
 * non-generic content words present on those pages.
 */
export function decide(briefs, question_concepts, variants_by_concept, answer_type = "text", present_concepts = null, n_strong_present = null, doc_titles = null, question_topic = null) {
  doc_titles = doc_titles || new Map();
  const q_set = new Set(question_concepts);
  // "other" is the topic of no subject: it never matches, on either side.
  if (question_topic === "other") question_topic = null;
  for (const b of briefs) b.topic_match = question_topic && b.page_topic === question_topic ? 1 : 0;
  const present = present_concepts !== null ? question_concepts.filter((c) => new Set(present_concepts).has(c)) : Array.from(question_concepts);
  const one_term = (n_strong_present !== null ? n_strong_present : present.length) < 2;
  // "names X, not Y" needs a Y: the rule fires only when the question names a dictionary concept.
  const y_keys = question_concepts.filter((c) => c in variants_by_concept);
  const decisions = new Map();
  let eligible = [];

  // Pass 1: the exclusions, so "best" is computed over the candidates that can still answer.
  const y = y_keys.map(concept_label).join(" / ");
  const foreign = new Map(); // candidates whose section title names a concept absent from the question
  for (const b of briefs) {
    const named = title_concepts(b.section_title, variants_by_concept).filter((c) => !q_set.has(c));
    const backed = Boolean(b.co_occurrence) || Boolean(b.title_keywords.length) || b.title_tier >= 1;
    const kws = _join(b.matched_keywords);
    if (named.length && y_keys.length) foreign.set(b.candidate_id, concept_label(named[0]));
    if (named.length && !backed && y_keys.length) {
      decisions.set(b.candidate_id, Decision("discarded", `The section '${b.section_title}' names '${foreign.get(b.candidate_id)}', not '${y}'; its lines carry only ${kws}.`));
      continue;
    }
    if (b.coverage < COVERAGE_MIN || !b.strong_covered) {
      const role = backed ? "supporting" : "tangential";
      const why = b.covered.length && !b.strong_covered ? "only generic words" : `only ${_join(b.covered) || "nothing"}`;
      decisions.set(b.candidate_id, Decision(role, `Covers ${why} (${pyFixed(b.coverage, 2)} of the question's words); ${_join(b.uncovered)} not covered: ${role}.`));
      continue;
    }
    eligible.push(b);
  }

  // A foreign-titled section on a page of another topic is discarded even when its lines co-occur,
  // as soon as an eligible candidate sits on a page whose topic is the question's ("names X, not Y").
  const on_topic = eligible.filter((o) => o.topic_match && !foreign.has(o.candidate_id));
  if (question_topic && on_topic.length) {
    const kept = [];
    for (const b of eligible) {
      if (foreign.has(b.candidate_id) && !b.topic_match) {
        const o = on_topic[0];
        decisions.set(
          b.candidate_id,
          Decision(
            "discarded",
            `The section '${b.section_title}' names '${foreign.get(b.candidate_id)}', not '${y}': its page's topic ` +
              `'${b.page_topic || "none"}' is not the question's '${question_topic}', and ${o.candidate_id} answers on a '${question_topic}' page.`,
          ),
        );
      } else {
        kept.push(b);
      }
    }
    eligible = kept;
  }

  if (!eligible.length) return decisions;
  const ranked = sortedBy(eligible, (x) => [x.rank_key.map((v) => -v), x.candidate_id]);

  // The pointer rule: a section whose own lines link to another document ("Voir la fiche : X")
  // defers to X when X holds a candidate that covers the question as well; the pointer stays
  // as "also answered here". A document never defers to one that points back at it.
  const deferred = new Map();
  for (const b of ranked) {
    for (const target of b.points_to) {
      const holder = ranked.find((o) => o.doc_id === target && !deferred.has(o.candidate_id) && o.coverage >= b.coverage - 0.01 && !o.points_to.includes(b.doc_id));
      if (holder !== undefined) {
        deferred.set(b.candidate_id, target);
        break;
      }
    }
  }
  for (const b of ranked) {
    if (deferred.has(b.candidate_id)) {
      const target = deferred.get(b.candidate_id);
      const title = doc_titles instanceof Map ? doc_titles.get(target) ?? target : doc_titles[target] ?? target;
      decisions.set(
        b.candidate_id,
        Decision("supporting", `Covers ${_join(b.covered)} (coverage ${pyFixed(b.coverage, 2)}) and points to '${title}' (Voir la fiche), which covers the question as well: supporting (also answered here).`),
      );
    }
  }
  eligible = ranked.filter((b) => !deferred.has(b.candidate_id));
  if (!eligible.length) return decisions;
  // The exact-titled chapter: a sub-section whose heading is made of the reader's words and which
  // holds the best-covering candidate of the page (itself or a step below it) is the answer whole.
  const best_cov = Math.max(...eligible.map((b) => pyRound(b.coverage, 2)));
  for (const b of eligible) {
    b.exact_chapter = b.title_exact && eligible.some((o) => pyRound(o.coverage, 2) >= best_cov - 0.01 && b.contains_anchor_of(o));
  }
  eligible = sortedBy(eligible, (x) => [x.rank_key.map((v) => -v), x.candidate_id]);
  const best = eligible[0];

  // Pass 2: the roles.
  for (const b of eligible) {
    const kws = _join(b.matched_keywords);
    const cov = `coverage ${pyFixed(b.coverage, 2)}`;
    // A second primary: same coverage, titles and anchor, a score within PRIMARY_SHARE of the best,
    // and a page the router ranks within PAGE_SHARE of the best page (so a weak FAQ page never
    // co-answers, while two fiches with different values both surface as conflicting evidence).
    const close =
      b.same_rank_class(best) &&
      pyRound(b.title_coverage, 2) >= pyRound(best.title_coverage, 2) - 0.01 &&
      b.score >= PRIMARY_SHARE * best.score &&
      b.page_score >= PAGE_SHARE * best.page_score;
    const qualifies = b.title_tier >= 1 || Boolean(b.co_occurrence) || one_term;
    if (close && qualifies) {
      const missing = !b.anchor_ok ? ` (no ${b.required_anchor.replace(/_/g, " ")} on the lines: the typed value is missing)` : "";
      let reason;
      if (b.exact_chapter) {
        reason = `The section title '${b.section_title}' is exactly in the question (every word of it) and the section holds the best lines; covers ${_join(b.covered)} (${cov}); score ${pyFloatRepr(b.score)}: primary.`;
      } else if (b.title_tier === 3) {
        reason = `The document '${b.doc_title}' and the section '${b.section_title}' name the question's words ${_join(b.covered)} (${cov}); score ${pyFloatRepr(b.score)}: primary.`;
      } else if (b.title_tier >= 1) {
        const which = b.title_tier === 2 ? `document '${b.doc_title}'` : `section '${b.section_title}'`;
        reason = `The ${which} title names ${_join(b.covered)} (${cov}); score ${pyFloatRepr(b.score)}: primary.`;
      } else if (b.co_occurrence) {
        reason = `The ${b.co_occurrence} carries ${_join(b.covered)} together (${cov}) and the score ${pyFloatRepr(b.score)} is the highest: primary.`;
      } else {
        reason = `The question carries one strong word present, ${_join(b.covered)}; the lines carry it (${cov}) and the score ${pyFloatRepr(b.score)} is the highest: primary.`;
      }
      decisions.set(b.candidate_id, Decision("primary", reason.slice(0, -1) + missing + "."));
    } else if (b.co_occurrence || b.title_keywords.length || b.title_tier >= 1) {
      let reason;
      if (best.exact_chapter && !b.exact_chapter) {
        reason = `Covers ${_join(b.covered)} (${cov}) but the title of ${best.candidate_id} ('${best.section_title}') is exactly in the question: supporting (also answered here).`;
      } else if (best.topic_match && !b.topic_match) {
        reason = `Covers ${_join(b.covered)} (${cov}) but its page's topic '${b.page_topic || "none"}' is not the question's '${question_topic}', which ${best.candidate_id} is on: supporting.`;
      } else if (pyRound(best.coverage, 2) > pyRound(b.coverage, 2)) {
        reason = `Covers ${_join(b.covered)} (${cov}) but ${best.candidate_id} covers more of the question (${pyFixed(best.coverage, 2)}): supporting.`;
      } else if (best.title_tier > b.title_tier || (best.title_tier === b.title_tier && best.title_tier >= 1 && best.title_coverage > b.title_coverage + 0.01)) {
        reason = `Covers ${_join(b.covered)} (${cov}) but ${best.candidate_id} is titled with the question's words: supporting (also answered here).`;
      } else if (best.anchor_ok && !b.anchor_ok) {
        const kind = (b.required_anchor || "").replace(/_/g, " ");
        reason = `Covers ${_join(b.covered)} (${cov}) but carries no ${kind}, which an answer of type ${answer_type} requires and ${best.candidate_id} has: supporting.`;
      } else if (best.doc_id !== b.doc_id && pyRound(best.page_score, 2) > pyRound(b.page_score, 2)) {
        reason = `Covers ${_join(b.covered)} (${cov}) but the router ranks the page of ${best.candidate_id} first (${pyFloatRepr(best.page_score)} vs ${pyFloatRepr(b.page_score)}): supporting.`;
      } else if (!qualifies) {
        reason = `Covers ${_join(b.covered)} (${cov}) but only ${kws} hits the lines, no title and no second concept: supporting.`;
      } else {
        reason = `Covers ${_join(b.covered)} (${cov}) but the score ${pyFloatRepr(b.score)} is behind ${best.candidate_id}: supporting.`;
      }
      decisions.set(b.candidate_id, Decision("supporting", reason));
    } else {
      decisions.set(b.candidate_id, Decision("tangential", `Only ${kws} hits these lines: no second concept and no title match.`));
    }
  }
  return decisions;
}
