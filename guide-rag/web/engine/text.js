// Port of guide_rag/retrieval/text.py: folding, tokens and whole-word matching shared by the
// detectors, the router and the sweep. Pure and deterministic; mirrors the Python rules exactly.

import { escapeRegex } from "./_py.js";

const _WS = /\s+/g;
// A hyphenated compound is one token ("car-pass", "rendez-vous"): a bare "car" never matches inside it.
const _TOKEN = /[a-z0-9]+(?:-[a-z0-9]+)*/g;
const _APOSTROPHES = { "’": "'", "‘": "'", " ": " ", " ": " " };

// Generic verbs and nouns a reader types around the subject ("acheter", "documents"). They weigh 0.3
// as content words and can never anchor a primary alone (the series' coverage rule). The list is
// brick 2's asset dictionary/weak_words.yaml (normalize.WeakWords, matched by stem); retrieval reads
// it, never redefines it. The loader installs it with `set_weak_words`; absent, nothing is weak.
let _WEAK = null;

/** Brick 2's WeakWords (stem membership via `has`), or an empty set when the asset is absent. */
export function _weak_words() {
  if (_WEAK === null) _WEAK = new Set();
  return _WEAK;
}

export function set_weak_words(weak) {
  _WEAK = weak;
}

// A procedure question ("comment …", "how do I …") is answered by a section's steps, not a line.
export const PROCEDURE_CUES = ["comment", "how do i", "how do we", "how to", "how can i", "wie kann ich", "wie melde", "wie beantrage"];

/** Whitespace normalisation only; used to compare quotes with cited lines. */
export function squash(text) {
  if (text === null || text === undefined || (typeof text === "number" && Number.isNaN(text))) return "";
  return String(text)
    .replace(/[’‘  ]/g, (ch) => _APOSTROPHES[ch])
    .replace(_WS, " ")
    .trim();
}

const _FOLD_CACHE = new Map();

/** Lowercase, strip accents, squash whitespace. Used for matching only, never for display. */
export function fold(text) {
  const cached = _FOLD_CACHE.get(text);
  if (cached !== undefined) return cached;
  const squashed = squash(text);
  const stripped = squashed.normalize("NFKD").replace(/\p{M}/gu, "");
  const out = stripped.toLowerCase();
  if (_FOLD_CACHE.size < 65536) _FOLD_CACHE.set(text, out);
  return out;
}

/** Word tokens of the folded text; "l'état" gives ["l", "etat"], "car-pass" stays one token. */
export function tokens(text) {
  return fold(text).match(_TOKEN) || [];
}

const _STEM_CACHE = new Map();

// Derivational endings folded when at least MIN_STEM letters remain: "immatriculer" and
// "immatriculation" meet at "immatricul", "assurer" and "assurance" at "assur", "couvre" and
// "couvrant" at "couvr". Longest first; one ending at most.
const _DERIVATIONS = ["ation", "ement", "ance", "ant", "er"];
export const MIN_STEM = 5;

/**
 * A light FR/EN stem: plurals, a final mute e and a few derivational endings fall, so "garanties"
 * meets "garantie" and "immatriculer" meets "immatriculation". Hyphenated compounds part by part.
 */
export function stem(token) {
  const cached = _STEM_CACHE.get(token);
  if (cached !== undefined) return cached;
  const out = _stem(token);
  if (_STEM_CACHE.size < 65536) _STEM_CACHE.set(token, out);
  return out;
}

function _stem(token) {
  if (token.includes("-")) return token.split("-").map(stem).join("-");
  if (token.length <= 3) return token;
  if (token.endsWith("eaux")) return token.slice(0, -1);
  if (token.endsWith("aux") && token.length > 4) return token.slice(0, -3) + "al";
  if ((token.endsWith("s") || token.endsWith("x")) && !token.endsWith("ss")) token = token.slice(0, -1);
  for (const ending of _DERIVATIONS) {
    if (token.endsWith(ending) && token.length - ending.length >= MIN_STEM) return token.slice(0, -ending.length);
  }
  if (token.length > 5 && token.endsWith("e")) token = token.slice(0, -1);
  return token;
}

export function stems(text) {
  return tokens(text).map(stem);
}

/**
 * True when the phrase appears as consecutive whole words (stem-equal) in the line. A multi-word
 * phrase also matches one hyphenated line token whose parts are the phrase ("rendez vous" meets
 * "rendez-vous"); a one-word phrase never matches inside a compound.
 */
export function phrase_in(phrase_stems, line_stems) {
  const n = phrase_stems.length;
  if (n === 0) return false;
  if (n <= line_stems.length) {
    outer: for (let i = 0; i <= line_stems.length - n; i++) {
      for (let j = 0; j < n; j++) if (line_stems[i + j] !== phrase_stems[j]) continue outer;
      return true;
    }
  }
  if (n >= 2) {
    const joined = phrase_stems.join("-");
    return line_stems.some((t) => t.includes("-") && t === joined);
  }
  return false;
}

export function contains_keyword(text, keyword) {
  return phrase_in(stems(keyword), stems(text));
}

/**
 * A whole-word regex over folded text for one dictionary variant; plurals allowed. Word
 * boundaries exclude hyphens, so "car" does not match "car-pass" here either.
 */
export function variant_regex(variant) {
  const parts = tokens(variant).map((t) => escapeRegex(t) + "(?:s|x|es)?");
  if (!parts.length) return /(?!x)x/u; // never matches: an empty variant hits nothing
  return new RegExp("(?<![\\p{L}\\p{N}_-])" + parts.join("[\\s-]+") + "(?![\\p{L}\\p{N}_-])", "u");
}

/** A generic word (every token of it, by brick 2's stem list) that cannot carry a question's subject. */
export function is_weak(text) {
  const ts = tokens(text);
  if (!ts.length) return true;
  const weak = _weak_words();
  return ts.every((t) => weak.has(t));
}

export function is_procedure_question(text) {
  const folded = " " + fold(text) + " ";
  return PROCEDURE_CUES.some((cue) => folded.includes(` ${cue} `));
}

/** "garantie_locative" reads as "garantie locative" in a reason sentence. */
export function concept_label(concept) {
  return concept.replace(/_/g, " ");
}

export function snippet_of(text, limit = 160) {
  text = squash(text);
  const chars = Array.from(text);
  if (chars.length <= limit) return text;
  return chars.slice(0, limit - 1).join("").replace(/\s+$/u, "") + "…";
}
