// Python-compatibility helpers shared by the JS port of guide_rag (no Python counterpart).
// Everything the Python pipeline does with floats, sorting, string formatting and regexes that a
// naive JS translation would do differently lives here, so the engine modules read like the
// Python files they mirror.

/** Python 3.12+ `sum()` of floats: Neumaier compensated summation, starting from 0 + x0. */
export function pySum(values) {
  let first = true;
  let result = 0.0;
  let c = 0.0;
  for (const x of values) {
    if (first) {
      result = 0 + x;
      first = false;
      continue;
    }
    const t = result + x;
    if (Math.abs(result) >= Math.abs(x)) c += (result - t) + x;
    else c += (x - t) + result;
    result = t;
  }
  if (c && Number.isFinite(c)) result += c;
  return result;
}

/** Python `round(x, n)`: correctly rounded, half to even on exact ties. */
export function pyRound(x, n = 0) {
  if (!Number.isFinite(x)) return x;
  const digits = Math.min(30, n + 24);
  const exact = x.toFixed(digits); // exact decimal expansion for the magnitudes used here
  const dot = exact.indexOf(".");
  const tail = exact.slice(dot + 1 + n);
  if (!/^50*$/.test(tail)) return Number(x.toFixed(n));
  // An exact tie: keep the truncated digits when the last one is even, else step away from zero.
  const kept = exact.slice(0, dot + 1 + n);
  const last = Number(kept.replace(/[-.]/g, "").slice(-1));
  const truncated = Number(kept);
  if (last % 2 === 0) return truncated;
  const step = Math.pow(10, -n);
  return Number((Math.abs(truncated) + step).toFixed(n)) * (x < 0 ? -1 : 1);
}

/** Python `repr(float)`: shortest round-trip digits, "6.0" for integral values, exponent outside 1e-4..1e16. */
export function pyFloatRepr(x) {
  if (Number.isNaN(x)) return "nan";
  if (x === Infinity) return "inf";
  if (x === -Infinity) return "-inf";
  if (x === 0) return Object.is(x, -0) ? "-0.0" : "0.0";
  const sign = x < 0 ? "-" : "";
  const [mantissa, expText] = Math.abs(x).toExponential().split("e");
  const exp = Number(expText);
  const digits = mantissa.replace(".", "");
  if (exp < -4 || exp >= 16) {
    const m = digits.length > 1 ? `${digits[0]}.${digits.slice(1)}` : digits;
    const e = Math.abs(exp) < 10 ? `0${Math.abs(exp)}` : String(Math.abs(exp));
    return `${sign}${m}e${exp < 0 ? "-" : "+"}${e}`;
  }
  if (exp >= 0) {
    const intPart = digits.length > exp + 1 ? digits.slice(0, exp + 1) : digits + "0".repeat(exp + 1 - digits.length);
    const frac = digits.length > exp + 1 ? digits.slice(exp + 1) : "0";
    return `${sign}${intPart}.${frac}`;
  }
  return `${sign}0.${"0".repeat(-exp - 1)}${digits}`;
}

/** Python `str(x)` for the scalars the pipeline interpolates into sentences. */
export function pyStr(x) {
  // Scores and weights are floats in Python even when integral, counts are ints: callers that
  // format floats call pyFloatRepr directly; pyStr is for ints, booleans, None and strings.
  if (typeof x === "number") return Number.isInteger(x) ? String(x) : pyFloatRepr(x);
  if (typeof x === "boolean") return x ? "True" : "False";
  if (x === null || x === undefined) return "None";
  return String(x);
}

/** Python `repr(str)`: single quotes unless the string holds a single quote and no double quote. */
export function pyStrRepr(s) {
  const useDouble = s.includes("'") && !s.includes('"');
  const q = useDouble ? '"' : "'";
  let out = "";
  for (const ch of s) {
    if (ch === "\\") out += "\\\\";
    else if (ch === q) out += "\\" + q;
    else if (ch === "\n") out += "\\n";
    else if (ch === "\t") out += "\\t";
    else if (ch === "\r") out += "\\r";
    else out += ch;
  }
  return q + out + q;
}

/** Python `repr(list)` of strings or ints: "['a', 'b']", "[3, 4]". */
export function pyListRepr(items, each = pyRepr) {
  return "[" + items.map(each).join(", ") + "]";
}

/** Python `repr(dict)` of str -> float: "{'housing': 1.0}". */
export function pyDictRepr(entries, valueRepr = pyFloatRepr) {
  return "{" + entries.map(([k, v]) => `${pyStrRepr(String(k))}: ${valueRepr(v)}`).join(", ") + "}";
}

function pyRepr(x) {
  if (typeof x === "string") return pyStrRepr(x);
  return pyStr(x);
}

/** Python `f"{x:.2f}"`. */
export function pyFixed(x, n) {
  return pyRound(x, n).toFixed(n);
}

/** Python `f"{x:g}"` (precision 6). */
export function pyG(x) {
  if (x === 0) return "0";
  if (!Number.isFinite(x)) return pyFloatRepr(x);
  const P = 6;
  let [m, e] = Math.abs(x).toExponential(P - 1).split("e");
  const exp = Number(e);
  const sign = x < 0 ? "-" : "";
  if (exp < -4 || exp >= P) {
    m = m.includes(".") ? m.replace(/0+$/, "").replace(/\.$/, "") : m;
    const ee = Math.abs(exp) < 10 ? `0${Math.abs(exp)}` : String(Math.abs(exp));
    return `${sign}${m}e${exp < 0 ? "-" : "+"}${ee}`;
  }
  let fixed = Math.abs(x).toFixed(Math.max(0, P - 1 - exp));
  if (fixed.includes(".")) fixed = fixed.replace(/0+$/, "").replace(/\.$/, "");
  return sign + fixed;
}

/** Python ordering of two scalars (numbers, strings by code point, booleans as 0/1, null first). */
export function pyCompare(a, b) {
  if (a === b) return 0;
  if (a === null || a === undefined) return b === null || b === undefined ? 0 : -1;
  if (b === null || b === undefined) return 1;
  if (typeof a === "boolean") a = a ? 1 : 0;
  if (typeof b === "boolean") b = b ? 1 : 0;
  if (typeof a === "number" && typeof b === "number") return a < b ? -1 : a > b ? 1 : 0;
  if (Array.isArray(a) && Array.isArray(b)) return compareTuples(a, b);
  const sa = String(a);
  const sb = String(b);
  return compareCodePoints(sa, sb);
}

function compareCodePoints(a, b) {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    const ca = a.codePointAt(i);
    const cb = b.codePointAt(i);
    if (ca !== cb) return ca < cb ? -1 : 1;
    if (ca > 0xffff) i++;
  }
  return a.length === b.length ? 0 : a.length < b.length ? -1 : 1;
}

/** Python tuple comparison, element by element. */
export function compareTuples(a, b) {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    const c = pyCompare(a[i], b[i]);
    if (c !== 0) return c;
  }
  return a.length - b.length;
}

/** Python `sorted(items, key=...)`: stable, by a tuple key. */
export function sortedBy(items, key) {
  const decorated = items.map((item, i) => ({ item, k: key(item), i }));
  decorated.sort((x, y) => compareTuples(x.k, y.k) || x.i - y.i);
  return decorated.map((d) => d.item);
}

/** Python `sorted(strings)` (code-point order) with de-duplication when `unique`. */
export function sortedStrings(values, unique = true) {
  const arr = unique ? Array.from(new Set(values)) : Array.from(values);
  return arr.sort(compareCodePoints);
}

/** Python `min(items, key=...)` / `max(items, key=...)` over tuple keys (the first wins ties). */
export function minBy(items, key) {
  let best = null;
  let bestKey = null;
  for (const item of items) {
    const k = key(item);
    if (best === null || compareTuples(k, bestKey) < 0) {
      best = item;
      bestKey = k;
    }
  }
  return best;
}

export function maxBy(items, key) {
  let best = null;
  let bestKey = null;
  for (const item of items) {
    const k = key(item);
    if (best === null || compareTuples(k, bestKey) > 0) {
      best = item;
      bestKey = k;
    }
  }
  return best;
}

/** `str.isdigit()` on a folded token. */
export function isDigits(s) {
  return s.length > 0 && /^\p{Nd}+$/u.test(s);
}

/** Python `re.escape`-like escaping for a JS regex in `u` mode (outside a character class). */
export function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\\/]/g, "\\$&");
}

const WORD_CLASS = "\\p{L}\\p{N}_";
const BOUNDARY = `(?:(?<=[${WORD_CLASS}])(?![${WORD_CLASS}])|(?<![${WORD_CLASS}])(?=[${WORD_CLASS}]))`;

/**
 * A Python regex (Unicode mode) as a JS RegExp with the `u` flag: `\b`, `\d`, `\w` follow Python's
 * Unicode definitions, `(?P<name>` becomes `(?<name>`, identity escapes of plain characters are
 * dropped (JS `u` mode refuses them). Only the syntax the pipeline's patterns use is handled.
 */
export function pyRegex(pattern, flags = "") {
  let out = "";
  let inClass = false;
  for (let i = 0; i < pattern.length; i++) {
    const ch = pattern[i];
    if (ch === "\\" && i + 1 < pattern.length) {
      const next = pattern[i + 1];
      i++;
      if (next === "b" && !inClass) out += BOUNDARY;
      else if (next === "d") out += inClass ? "\\p{Nd}" : "\\p{Nd}";
      else if (next === "D") out += inClass ? "\\P{Nd}" : "\\P{Nd}";
      else if (next === "w") out += inClass ? WORD_CLASS : `[${WORD_CLASS}]`;
      else if (next === "W") out += inClass ? "" : `[^${WORD_CLASS}]`;
      else if (/[A-Za-z0-9]/.test(next)) out += "\\" + next;
      else if ("^$\\.*+?()[]{}|/".includes(next)) out += "\\" + next;
      else if (next === "-") out += inClass ? "\\-" : "-";
      else out += next;
      continue;
    }
    if (ch === "[" && !inClass) {
      inClass = true;
      out += ch;
      continue;
    }
    if (ch === "]" && inClass) {
      inClass = false;
      out += ch;
      continue;
    }
    if (ch === "(" && pattern.startsWith("(?P<", i)) {
      out += "(?<";
      i += 3;
      continue;
    }
    if (ch === "/" && !inClass) {
      out += "\\/";
      continue;
    }
    out += ch;
  }
  return new RegExp(out, flags.includes("u") ? flags : flags + "u");
}

/** Python `re.search(pattern, text)` truthiness for a prepared RegExp (no `g` flag needed). */
export function reSearch(rx, text) {
  rx.lastIndex = 0;
  return rx.test(text);
}

/** SHA-1 of a UTF-8 string, hex (for `question_id_of`); synchronous so the pipeline stays sync. */
export function sha1Hex(text) {
  const bytes = new TextEncoder().encode(text);
  const ml = bytes.length * 8;
  const padded = new Uint8Array(((bytes.length + 8) >> 6 << 6) + 64);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 4, ml >>> 0, false);
  view.setUint32(padded.length - 8, Math.floor(ml / 0x100000000), false);
  let h0 = 0x67452301, h1 = 0xefcdab89, h2 = 0x98badcfe, h3 = 0x10325476, h4 = 0xc3d2e1f0;
  const w = new Uint32Array(80);
  for (let off = 0; off < padded.length; off += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(off + i * 4, false);
    for (let i = 16; i < 80; i++) {
      const x = w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16];
      w[i] = (x << 1) | (x >>> 31);
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4;
    for (let i = 0; i < 80; i++) {
      let f, k;
      if (i < 20) { f = (b & c) | (~b & d); k = 0x5a827999; }
      else if (i < 40) { f = b ^ c ^ d; k = 0x6ed9eba1; }
      else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8f1bbcdc; }
      else { f = b ^ c ^ d; k = 0xca62c1d6; }
      const t = (((a << 5) | (a >>> 27)) + f + e + k + w[i]) >>> 0;
      e = d; d = c; c = (b << 30) | (b >>> 2); b = a; a = t;
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0; h4 = (h4 + e) >>> 0;
  }
  return [h0, h1, h2, h3, h4].map((v) => v.toString(16).padStart(8, "0")).join("");
}

/** A map keyed by a tuple of strings/ints (Python dict keyed by tuples). */
export function tupleKey(...parts) {
  return parts.map((p) => (p === null || p === undefined ? "" : String(p))).join("\u0000");
}

/** Python `isinstance(x, Mapping)` for the duck-typed readers: a plain object or a Map. */
export function isMapping(x) {
  if (x instanceof Map) return true;
  if (x === null || typeof x !== "object") return false;
  const proto = Object.getPrototypeOf(x);
  return proto === Object.prototype || proto === null;
}

/** Python `dict.fromkeys(items)` order-preserving de-duplication. */
export function uniq(items) {
  return Array.from(new Set(items));
}

/** A pandas-like cell reader: None/NaN read as the empty string. */
export function _s(value) {
  if (value === null || value === undefined || (typeof value === "number" && Number.isNaN(value))) return "";
  return String(value);
}
