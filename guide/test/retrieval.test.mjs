import test from "node:test";
import assert from "node:assert/strict";
import { fold, tokenize, stem, expandQuery, buildIndex, search, decide, coverageOf, VERDICTS, THRESHOLDS, segmentHtml, segmentKnowledge, onPage, DICTIONARY } from "../engine.js";
import { PAGE_HTML, SECOND_PAGE_HTML, KNOWLEDGE, ORIGIN } from "./fixtures.mjs";

function corpus() {
  return [
    ...segmentHtml(PAGE_HTML, `${ORIGIN}/`),
    ...segmentHtml(SECOND_PAGE_HTML, `${ORIGIN}/mobilite/`),
    ...segmentKnowledge(KNOWLEDGE, ORIGIN),
  ];
}

test("fold removes marks and case, folds apostrophes and ligatures, and maps back to the original", () => {
  const { folded, map } = fold("Œuvre d’ÉTÉ à Luxembourg");
  assert.equal(folded, "oeuvre d'ete a luxembourg");
  assert.equal(map[0], 0);
  assert.equal(map[1], 0, "both units of 'oe' come from the ligature");
  assert.equal(map[8], 7, "the apostrophe keeps its index: one unit later in the folded text");
  assert.equal("Œuvre d’ÉTÉ à Luxembourg"[map[folded.indexOf("luxembourg")]], "L");
});

test("tokenize drops stopwords, folds and stems plurals", () => {
  assert.deepEqual(tokenize("Où sont les plaques d'immatriculation de ma voiture ?"), ["plaque", "immatriculation", "voiture"]);
  assert.deepEqual(tokenize("How do I register my car?"), ["register", "car"]);
  assert.equal(stem("bus"), "bus", "short words are not stemmed");
  assert.equal(stem("chevaux"), "chevau");
});

test("the dictionary brings synonyms into the query at a lower weight, phrases first", () => {
  const en = expandQuery("How much is the rental deposit?");
  assert.ok(en.terms.has("caution"), "deposit brings caution");
  assert.ok(en.terms.has("garantie"), "and garantie");
  assert.equal(en.terms.get("deposit"), 1);
  assert.equal(en.terms.get("caution"), 0.6);
  assert.ok(en.phrases.includes("rental deposit"), "the two-word entry is matched as a phrase");
  const fr = expandQuery("immatriculer ma voiture");
  assert.ok(fr.terms.has("plaque") && fr.terms.has("snca") && fr.terms.has("car"));
  const none = expandQuery("xylophone");
  assert.equal(none.groups.length, 0);
  assert.deepEqual([...none.terms.keys()], ["xylophone"]);
});

test("every dictionary entry tokenizes to something, and no group is a singleton", () => {
  for (const group of DICTIONARY) {
    assert.ok(group.length >= 2);
    for (const entry of group) assert.ok(tokenize(entry).length >= 1, `entry "${entry}" is all stopwords`);
  }
});

test("BM25 ranks the section about the deposit first for a French and for an English question", () => {
  const index = buildIndex(corpus());
  const fr = search(index, expandQuery("Quel est le montant de la caution pour un logement ?"));
  assert.ok(["Montant", "La garantie locative"].includes(fr[0].section.heading), fr.map((r) => `${r.section.heading}:${r.score.toFixed(2)}`).join(" | "));
  assert.ok(fr[0].relevance > 0.3 && fr[0].relevance <= 1, String(fr[0].relevance));
  const en = search(index, expandQuery("rental deposit amount"));
  assert.ok(["Montant", "La garantie locative"].includes(en[0].section.heading));
  assert.ok(en[0].matched.includes("caution") || en[0].matched.includes("garantie"), "matched through the dictionary");
});

test("accents and case do not matter to the search", () => {
  const index = buildIndex(corpus());
  const a = search(index, expandQuery("CONTROLE TECHNIQUE"))[0];
  const b = search(index, expandQuery("contrôle technique"))[0];
  assert.equal(a.section.heading, b.section.heading);
  assert.equal(a.score, b.score);
});

test("the page the reader is on is boosted", () => {
  const index = buildIndex(corpus());
  const plain = search(index, expandQuery("assurance vélo"));
  const boosted = search(index, expandQuery("assurance vélo"), { boostPage: `${ORIGIN}/mobilite/` });
  const plainScore = plain.find((r) => r.section.heading === "Le vélo").score;
  const boostedScore = boosted.find((r) => r.section.heading === "Le vélo").score;
  assert.ok(boostedScore > plainScore);
  assert.ok(onPage({ page: `${ORIGIN}/#fiche/banque`, anchor: "fiche/banque" }, "fiche/banque"));
  assert.ok(onPage({ page: `${ORIGIN}/mobilite/`, anchor: "" }, "mobilite/"));
  assert.ok(!onPage({ page: `${ORIGIN}/mobilite/`, anchor: "" }, "fiche/banque"));
});

test("verdict: Précisez for an empty or one-stopword question", () => {
  const index = buildIndex(corpus());
  for (const q of ["", "   ", "le", "les ?", "how"]) {
    const x = expandQuery(q);
    const d = decide(q, x, search(index, x));
    assert.equal(d.verdict, VERDICTS.CLARIFY, JSON.stringify(q));
  }
});

test("verdict: Pas dans ce guide when nothing matches or only a synonym matches weakly, naming what was searched", () => {
  const index = buildIndex(corpus());
  const q = "astronomie quantique";
  const x = expandQuery(q);
  const d = decide(q, x, search(index, x));
  assert.equal(d.verdict, VERDICTS.NOT_IN_GUIDE);
  assert.deepEqual(d.searched, ["astronomie", "quantique"]);
  assert.equal(d.reason, "no_match");
  // a question whose own words are absent and whose synonyms barely match
  const q2 = "lease";
  const x2 = expandQuery(q2);
  const results = search(index, x2);
  const d2 = decide(q2, x2, results);
  assert.ok([VERDICTS.NOT_IN_GUIDE, VERDICTS.FOUND, VERDICTS.TWO_PAGES].includes(d2.verdict));
  if (d2.verdict === VERDICTS.NOT_IN_GUIDE) assert.ok(["words_not_covered", "below_threshold"].includes(d2.reason));
  // a question whose words are all unknown to the guide, except one synonym-covered word in a weak section
  const q3 = "capitale australie canberra deposit";
  const x3 = expandQuery(q3);
  const d3 = decide(q3, x3, search(index, x3));
  assert.equal(d3.verdict, VERDICTS.NOT_IN_GUIDE, d3.reason);
  assert.equal(d3.reason, "words_not_covered");
});

test("verdict: Trouvé dans le guide with a margin for a clear question", () => {
  const index = buildIndex(corpus());
  const q = "Quel est le montant de la garantie locative ?";
  const x = expandQuery(q);
  const d = decide(q, x, search(index, x));
  assert.equal(d.verdict, VERDICTS.FOUND);
  assert.equal(d.best.section.heading, "Montant");
  assert.ok(d.margin >= THRESHOLDS.closeMargin);
});

test("verdict: Deux pages possibles when the top two scores are close and on different pages", () => {
  // two sections, two pages, the same text: the scores tie exactly
  const twins = [
    { page: `${ORIGIN}/a/`, anchor: "", headingPath: ["Assurance"], heading: "Assurance", level: 1, text: "La franchise est la part du sinistre qui reste à votre charge après indemnisation par l'assureur." },
    { page: `${ORIGIN}/b/`, anchor: "", headingPath: ["Assurance"], heading: "Assurance", level: 1, text: "La franchise est la part du sinistre qui reste à votre charge après indemnisation par l'assureur." },
  ];
  const index = buildIndex(twins);
  const q = "franchise sinistre";
  const x = expandQuery(q);
  const d = decide(q, x, search(index, x));
  assert.equal(d.verdict, VERDICTS.TWO_PAGES);
  assert.equal(d.margin, 0);
  assert.notEqual(d.best.section.page, d.second.section.page);
  // the same two sections on one page: one answer, not two
  const same = buildIndex(twins.map((s) => ({ ...s, page: `${ORIGIN}/a/` })));
  assert.equal(decide(q, x, search(same, x)).verdict, VERDICTS.FOUND);
});

test("coverage counts a reader's word as answered when the section holds it or one of its synonyms", () => {
  const x = expandQuery("Is home insurance mandatory?");
  assert.equal(coverageOf(x, ["assurance"]), 2 / 3, "the phrase 'home insurance' is one dictionary entry, so assurance covers home and insurance; mandatory is not covered");
  assert.equal(coverageOf(x, ["habitation", "assurance"]), 2 / 3);
  assert.equal(coverageOf(expandQuery("deposit mandatory"), ["caution"]), 1 / 2);
  assert.equal(coverageOf(x, []), 0);
  assert.ok(x.serves.get("assurance").has("insurance"));
});

test("the thresholds are the ones the page says", () => {
  assert.equal(THRESHOLDS.minCoverage, 0.34);
  assert.equal(THRESHOLDS.closeMargin, 0.12);
  assert.equal(THRESHOLDS.minRelevance, 0.2);
  assert.equal(THRESHOLDS.minQueryChars, 4);
});
