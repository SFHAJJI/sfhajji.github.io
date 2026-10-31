import test from "node:test";
import assert from "node:assert/strict";
import { findMatches, passage, expandQuery } from "../engine.js";

const TEXT = "La garantie locative, souvent appelée caution, est versée au propriétaire. Elle est rendue à la fin du bail. Les CAUTIONS bancaires sont fréquentes.";

test("findMatches marks words on the original text through the fold, case and accents ignored, plurals included", () => {
  const matches = findMatches(TEXT, ["caution", "proprietaire"]);
  const words = matches.map((m) => TEXT.slice(m.start, m.end));
  assert.deepEqual(words, ["caution", "propriétaire", "CAUTIONS"]);
});

test("passage cuts around the first match at sentence bounds and keeps the original characters", () => {
  const p = passage(TEXT, ["bail"], { maxChars: 60 });
  const joined = p.parts.map((x) => x.text).join("");
  assert.equal(TEXT.slice(p.start, p.end), joined, "the parts are the passage, byte for byte");
  assert.match(joined, /^Elle est rendue à la fin du bail\./);
  assert.ok(p.parts.some((x) => x.matched && x.text === "bail"));
  assert.equal(p.truncatedBefore, true);
  assert.equal(p.truncatedAfter, true);
});

test("passage with no match is the start of the text, unmarked", () => {
  const p = passage(TEXT, ["xylophone"], { maxChars: 40 });
  assert.equal(p.matchCount, 0);
  assert.equal(p.start, 0);
  assert.ok(p.parts.every((x) => !x.matched));
  assert.ok(p.parts.map((x) => x.text).join("").length <= 40);
});

test("passage marks the query's expanded terms, so a synonym is highlighted too", () => {
  const x = expandQuery("deposit");
  const p = passage(TEXT, [...x.terms.keys()]);
  const marked = p.parts.filter((y) => y.matched).map((y) => y.text);
  assert.ok(marked.includes("caution"));
  assert.ok(marked.includes("garantie"));
});

test("passage handles astral characters without breaking offsets", () => {
  const text = "Un chien 🐕 déclaré à la commune paie une taxe. Le chat 🐈 non.";
  const p = passage(text, ["commune", "taxe"]);
  assert.equal(text.slice(p.start, p.end), p.parts.map((x) => x.text).join(""));
  assert.deepEqual(p.parts.filter((x) => x.matched).map((x) => x.text), ["commune", "taxe"]);
});
