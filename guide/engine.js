// The demo's engine: segmentation, folding, the dictionary, BM25, the verdict and the highlighter.
// Plain ES module, no dependency, the same file in the browser (guide/app.js) and under node:test (guide/test).
// Nothing here writes text of its own: an answer is a section of the guide, quoted, with its link.

// ---------------------------------------------------------------------------------------------
// Folding: letters without their marks, lower case, one apostrophe, œ/æ written out. Each folded
// unit remembers the index of the original character it came from, so a match found on the folded
// text is marked on the original text (the same idea as Lex's FoldedText).
// ---------------------------------------------------------------------------------------------

const APOSTROPHES = /[’‘ʼ`´]/;
const SPACES = /[       \t\r\n\f\v]/;

/** Folds one character to its folded units (a string of 0, 1 or 2 characters). */
function foldChar(ch) {
  if (APOSTROPHES.test(ch)) return "'";
  if (SPACES.test(ch)) return " ";
  if (ch === "­") return ""; // soft hyphen: dropped
  if (ch === "œ" || ch === "Œ") return "oe";
  if (ch === "æ" || ch === "Æ") return "ae";
  if (ch === "ß") return "ss";
  const decomposed = ch.normalize("NFD").replace(/[̀-ͯ]/g, "");
  return decomposed.toLowerCase();
}

/**
 * Folds a text. Returns { folded, map } where map[i] is the index in `text` of the character that
 * produced folded[i]. Iterates by code point so astral characters stay whole.
 */
export function fold(text) {
  const units = [];
  const map = [];
  let index = 0;
  for (const ch of String(text)) {
    const out = foldChar(ch);
    for (let k = 0; k < out.length; k++) {
      units.push(out[k]);
      map.push(index);
    }
    index += ch.length;
  }
  return { folded: units.join(""), map };
}

// ---------------------------------------------------------------------------------------------
// Tokens: words of letters and digits, folded, without stopwords, with a light plural stem.
// ---------------------------------------------------------------------------------------------

const STOPWORDS = new Set((
  "le la les l un une des du de d au aux et ou où mais donc or ni ce cet cette ces c ça cela ceci " +
  "je tu il elle on nous vous ils elles me te se y en ne pas plus moins très tres trop peu que qui quoi dont " +
  "quel quelle quels quelles est sont suis es sommes êtes etes été ete être etre a ai as avons avez ont avoir " +
  "fait faire faut dois doit dois-je puis peut peux pour par sur sous dans avec sans chez vers entre comme " +
  "mon ma mes ton ta tes son sa ses notre nos votre vos leur leurs si oui non tout tous toute toutes " +
  "quand comment pourquoi combien lequel laquelle lesquels lesquelles ici là la là-bas " +
  // "car" is left out: a French conjunction, but the English word for a vehicle

  "the a an and or but of to in on at for from with without by about as is are was were be been being am " +
  "do does did have has had can could should would may might will shall must i you he she it we they me him her us them " +
  "my your his its our their this that these those what which who whom whose when where why how there here " +
  "if then else not no yes so than too very just also into onto over under again"
).split(/\s+/).filter(Boolean));

/** A light stem for French and English: a final plural s or x after at least four letters. */
export function stem(token) {
  if (token.length > 4 && (token.endsWith("s") || token.endsWith("x"))) {
    const cut = token.slice(0, -1);
    // "aux" plurals (animaux, chevaux) are left alone: the dictionary carries the pairs that matter.
    return cut;
  }
  return token;
}

/** The query's or a text's tokens: folded words of two or more characters, stopwords removed, stemmed. */
export function tokenize(text) {
  const { folded } = fold(text);
  const words = folded.match(/[\p{L}\p{N}]+/gu) ?? [];
  const out = [];
  for (const w of words) {
    if (w.length < 2) continue;
    if (STOPWORDS.has(w)) continue;
    out.push(stem(w));
  }
  return out;
}

/** The query's raw words (for "what was searched" and the Précisez verdict): no stopwords, no stem. */
export function contentWords(text) {
  const { folded } = fold(text);
  const words = folded.match(/[\p{L}\p{N}]+/gu) ?? [];
  return words.filter((w) => w.length >= 2 && !STOPWORDS.has(w));
}

// ---------------------------------------------------------------------------------------------
// The dictionary: domain synonyms, French and English, for a newcomer's questions. Dictionaries
// before models: each group is a hand-written set; a query word that belongs to a group brings the
// group's other words into the query at a lower weight. Multi-word entries are matched as phrases
// on the folded query before single words are looked up.
// ---------------------------------------------------------------------------------------------

export const DICTIONARY = [
  // housing
  ["logement", "housing", "appartement", "apartment", "flat", "maison", "house", "habitation", "loger", "home", "studio", "colocation"],
  ["loyer", "rent", "louer", "location", "locatif", "locative", "renting", "lease", "bail"],
  ["bail", "contrat de bail", "lease", "tenancy", "contrat de location", "rental contract"],
  ["caution", "garantie locative", "deposit", "rental deposit", "security deposit", "garantie bancaire", "garantie"],
  ["locataire", "tenant", "renter", "preneur"],
  ["proprietaire", "landlord", "bailleur", "owner", "landlady"],
  ["acheter", "achat", "buy", "buying", "purchase", "acquisition", "acquerir", "devenir proprietaire"],
  ["pret", "credit", "emprunt", "hypothecaire", "mortgage", "loan", "taux", "interest rate", "banque pret"],
  ["charges", "service charges", "utilities", "eau", "electricite", "chauffage", "heating", "gaz"],
  ["demenagement", "demenager", "moving", "move in", "relocation", "relocate", "emmenager", "arrivee", "arriver", "arrival", "installation", "s'installer"],
  // the commune and papers
  ["commune", "municipality", "town hall", "mairie", "administration communale", "bierger-center", "biergercenter", "commune de residence"],
  ["declaration d'arrivee", "declaration arrivee", "registration", "register", "s'inscrire", "inscription", "enregistrement", "declarer", "attestation d'enregistrement", "residence certificate", "certificat de residence"],
  ["matricule", "numero national", "national number", "social security number", "identifiant national", "numero d'identification", "ccss"],
  ["carte d'identite", "passeport", "passport", "id card", "titre de sejour", "residence permit", "visa", "sejour"],
  ["permis de conduire", "driving licence", "driver's license", "drivers license", "permis", "conduire", "echange du permis"],
  // vehicles
  ["vehicule", "voiture", "car", "vehicle", "auto", "automobile", "moto", "motorbike", "camionnette"],
  ["immatriculation", "immatriculer", "plaque", "plaques", "number plate", "licence plate", "license plate", "registration plate", "carte grise", "registration certificate", "snca", "certificat d'immatriculation", "importer une voiture", "import car"],
  ["controle technique", "snct", "technical inspection", "mot", "inspection", "controle"],
  ["vignette", "vignette 705", "douane", "douanes", "customs", "taxe", "duty"],
  ["car-pass", "carpass", "acte de vente", "bill of sale", "occasion", "second-hand", "used car", "cession"],
  ["transport", "bus", "tram", "train", "cfl", "public transport", "transports publics", "mobilite", "mobility", "gratuit", "free transport", "ligne", "arret", "gare", "station"],
  // liability and insurance
  ["responsabilite civile", "responsabilite", "rc", "liability", "civil liability", "third party", "tiers", "dommage", "dommages", "damage", "degats", "faute"],
  ["assurance", "insurance", "assureur", "insurer", "assure", "insured", "police d'assurance", "policy", "contrat d'assurance", "prime", "premium", "cotisation"],
  ["assurance habitation", "multirisque", "mrh", "home insurance", "household insurance", "contents insurance", "incendie", "fire", "degat des eaux", "water damage", "vol", "theft", "cambriolage", "burglary", "sinistre", "claim", "franchise", "deductible", "exclusion", "plafond", "garantie"],
  ["assurance auto", "car insurance", "motor insurance", "bonus-malus", "bonus malus", "omnium", "casco", "comprehensive"],
  ["velo", "bicycle", "bike", "cyclist", "trottinette", "e-bike", "velo electrique"],
  // health and social security
  ["cns", "caisse nationale de sante", "caisse de maladie", "health insurance", "securite sociale", "social security", "affiliation", "affilier", "remboursement", "reimbursement", "mutuelle", "cmcm", "medecin", "doctor", "sante", "health"],
  ["pension", "retraite", "retirement", "prevoyance", "epargne-pension", "pension savings", "3eme pilier", "troisieme pilier", "assurance-vie", "life insurance"],
  ["chomage", "unemployment", "adem", "emploi", "job", "travail", "work", "employeur", "employer", "contrat de travail", "employment contract"],
  // money and tax
  ["impot", "impots", "tax", "taxes", "fiscal", "fiscalite", "acd", "declaration d'impot", "tax return", "classe d'impot", "tax class", "retenue", "withholding", "fiche de retenue", "tax card"],
  ["salaire", "salary", "wage", "pay", "brut", "gross", "net", "revenu", "income", "paie", "payslip", "fiche de paie", "smic", "salaire social minimum", "minimum wage"],
  ["banque", "bank", "compte bancaire", "bank account", "compte", "account", "iban", "carte bancaire", "virement", "transfer"],
  ["aide", "aides", "subvention", "subsidy", "allocation", "allowance", "prime", "bonus", "cheque-service", "aide au logement", "housing aid", "frontalier", "cross-border", "impatrie", "impatries", "expat", "expatriate"],
  // family and school
  ["ecole", "school", "scolarite", "schooling", "creche", "nursery", "daycare", "maison relais", "enfant", "enfants", "child", "children", "allocations familiales", "family allowance", "caisse pour l'avenir des enfants", "cae"],
  ["langue", "langues", "language", "languages", "luxembourgeois", "luxembourgish", "francais", "french", "allemand", "german", "anglais", "english", "cours", "course", "inl"],
  // utilities and daily life
  ["internet", "telephone", "phone", "mobile", "forfait", "operateur", "operator", "abonnement", "subscription", "wifi", "fibre"],
  ["dechets", "poubelle", "waste", "recycling", "recyclage", "tri", "garbage", "rubbish"],
  ["animal", "animaux", "chien", "dog", "chat", "cat", "pet", "pets", "puce", "microchip", "taxe sur les chiens", "dog tax"],
  ["vote", "voter", "elections", "election", "electoral", "listes electorales", "communales", "europeennes"],
];

/** The folded, stemmed form of a dictionary entry (a word or a phrase). */
function entryKey(entry) {
  return tokenize(entry).join(" ");
}

/** Built once: entry key → the set of group indexes it belongs to. */
const ENTRY_GROUPS = (() => {
  const index = new Map();
  DICTIONARY.forEach((group, g) => {
    for (const entry of group) {
      const key = entryKey(entry);
      if (!key) continue;
      if (!index.has(key)) index.set(key, new Set());
      index.get(key).add(g);
    }
  });
  return index;
})();

/** The longest phrase length in the dictionary, in tokens. */
const LONGEST_ENTRY = Math.max(...[...ENTRY_GROUPS.keys()].map((k) => k.split(" ").length));

/**
 * Expands a query's tokens with the dictionary. Returns { tokens, terms: Map<token, weight>, groups: [group indexes],
 * phrases: [matched entries], serves: Map<term, Set<own token>> (which of the reader's words each term stands for) }. The query's own tokens weigh 1; a synonym brought in by a group weighs
 * `synonymWeight`; a token that is both keeps 1. Phrases of up to LONGEST_ENTRY tokens are tried first,
 * longest first, so "garantie locative" lands in the deposit group before "garantie" alone does.
 */
export function expandQuery(query, { synonymWeight = 0.6 } = {}) {
  const tokens = tokenize(query);
  const terms = new Map();
  const groups = new Map(); // group index -> the own tokens that brought it in
  const phrases = [];
  const serves = new Map(); // term -> Set of own tokens it stands for
  const serve = (term, own) => {
    if (!serves.has(term)) serves.set(term, new Set());
    serves.get(term).add(own);
  };
  for (const t of tokens) {
    terms.set(t, 1);
    serve(t, t);
  }
  // phrases, longest first
  const used = new Array(tokens.length).fill(false);
  for (let len = Math.min(LONGEST_ENTRY, tokens.length); len >= 1; len--) {
    for (let i = 0; i + len <= tokens.length; i++) {
      if (used.slice(i, i + len).some(Boolean)) continue;
      const key = tokens.slice(i, i + len).join(" ");
      const hit = ENTRY_GROUPS.get(key);
      if (!hit) continue;
      for (const g of hit) {
        if (!groups.has(g)) groups.set(g, new Set());
        for (let k = i; k < i + len; k++) groups.get(g).add(tokens[k]);
      }
      phrases.push(key);
      for (let k = i; k < i + len; k++) used[k] = true;
    }
  }
  for (const [g, own] of groups) {
    for (const entry of DICTIONARY[g]) {
      for (const t of tokenize(entry)) {
        if (!terms.has(t)) terms.set(t, synonymWeight);
        for (const o of own) serve(t, o);
      }
    }
  }
  return { tokens, terms, groups: [...groups.keys()], phrases, serves };
}

// ---------------------------------------------------------------------------------------------
// Segmentation of an HTML page into sections by its headings (h1 to h3). Regex-based on purpose:
// it needs no DOM, so the same code runs in the browser and under node:test. Scripts, styles and
// templates are dropped first. A section carries the page URL, its anchor (the heading's own id,
// else the nearest id seen before it), its heading path and its text.
// ---------------------------------------------------------------------------------------------

const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ", laquo: "«", raquo: "»", rsquo: "’", lsquo: "‘", hellip: "…", eacute: "é", egrave: "è", agrave: "à", ccedil: "ç", ecirc: "ê", ocirc: "ô", ucirc: "û", icirc: "î", acirc: "â", euml: "ë", iuml: "ï", uuml: "ü", ugrave: "ù", oelig: "œ", ndash: "–", mdash: "—", deg: "°", euro: "€", copy: "©" };

/** Decodes HTML character references (named ones above, decimal and hexadecimal). */
export function decodeEntities(text) {
  return String(text).replace(/&(#x[0-9a-fA-F]+|#[0-9]+|[a-zA-Z]+);/g, (whole, body) => {
    if (body[0] === "#") {
      const code = body[1] === "x" || body[1] === "X" ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10);
      return Number.isFinite(code) && code > 0 && code < 0x110000 ? String.fromCodePoint(code) : whole;
    }
    return Object.hasOwn(ENTITIES, body) ? ENTITIES[body] : whole;
  });
}

const BLOCK_TAGS = new Set(["p", "div", "li", "ul", "ol", "br", "tr", "td", "th", "table", "section", "article", "header", "footer", "nav", "aside", "main", "dd", "dt", "dl", "blockquote", "figcaption", "summary", "details", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "pre", "label", "button", "option", "fieldset", "legend", "form"]);
const DROP_TAGS = ["script", "style", "noscript", "template", "svg", "iframe", "canvas", "textarea", "select"];

/** Collapses whitespace runs to one space and trims. */
export function squash(text) {
  return text.replace(/\s+/g, " ").trim();
}

/**
 * Splits a page into sections. `url` is the page's address (without fragment). Returns an array of
 * { page, anchor, headingPath, heading, level, text }. Text before the first heading becomes a
 * section headed by the page title (or the URL) when it is not empty.
 */
export function segmentHtml(html, url, { minChars = 40 } = {}) {
  let src = String(html).replace(/<!--[\s\S]*?-->/g, " ");
  for (const tag of DROP_TAGS) {
    src = src.replace(new RegExp(`<${tag}\\b[^>]*>[\\s\\S]*?<\\/${tag}\\s*>`, "gi"), " ");
  }
  const titleMatch = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(src);
  const title = titleMatch ? squash(decodeEntities(titleMatch[1])) : "";
  const bodyStart = src.search(/<body\b/i);
  if (bodyStart >= 0) src = src.slice(bodyStart);

  const sections = [];
  const path = []; // headings by level: path[0]=h1 text, path[1]=h2, path[2]=h3
  let current = { heading: title || url, level: 0, anchor: "", headingPath: title ? [title] : [], text: [] };
  let lastId = "";
  let inHeading = null; // { level, id, text: [] }

  const tagRe = /<\/?([a-zA-Z][a-zA-Z0-9-]*)([^>]*)>/g;
  let pos = 0;
  let m;
  const pushText = (raw) => {
    const t = decodeEntities(raw);
    if (inHeading) inHeading.text.push(t);
    else current.text.push(t);
  };
  const closeCurrent = () => {
    const text = squash(current.text.join(""));
    if (text.length >= minChars) {
      sections.push({ page: url, anchor: current.anchor, headingPath: [...current.headingPath], heading: current.heading, level: current.level, text });
    }
  };
  while ((m = tagRe.exec(src)) !== null) {
    if (m.index > pos) pushText(src.slice(pos, m.index));
    pos = tagRe.lastIndex;
    const closing = m[0][1] === "/";
    const name = m[1].toLowerCase();
    const attrs = m[2] ?? "";
    const idMatch = !closing ? /\sid\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))/i.exec(attrs) : null;
    const id = idMatch ? (idMatch[1] ?? idMatch[2] ?? idMatch[3] ?? "") : "";
    const level = /^h[1-3]$/.test(name) ? Number(name[1]) : 0;
    if (level && !closing) {
      // a heading starts: the previous section ends
      closeCurrent();
      inHeading = { level, id: id || lastId, text: [] };
      if (id) lastId = id;
      continue;
    }
    if (level && closing && inHeading) {
      const heading = squash(inHeading.text.join(""));
      path.length = inHeading.level - 1;
      path[inHeading.level - 1] = heading;
      const headingPath = path.filter((p) => typeof p === "string" && p.length > 0);
      current = { heading, level: inHeading.level, anchor: inHeading.id, headingPath, text: [] };
      inHeading = null;
      continue;
    }
    if (id) lastId = id;
    if (BLOCK_TAGS.has(name)) pushText(" ");
  }
  if (pos < src.length) pushText(src.slice(pos));
  closeCurrent();
  return sections;
}

/**
 * Sections from a knowledge object of the guide's shape (the shape is documented in the guide's own data
 * file header: a fiche has id, titre, resume, corps (paragraph strings and { h } sub-headings), aRetenir;
 * faq has { q, a }; timeline has { t }). Nothing of the guide is stored here: this function only turns
 * what the browser fetched into sections. Unknown shapes are ignored.
 */
export function segmentKnowledge(kb, origin) {
  const out = [];
  const base = origin.replace(/\/+$/, "") + "/";
  const str = (v) => (typeof v === "string" ? squash(v) : "");
  if (kb && Array.isArray(kb.fiches)) {
    for (const f of kb.fiches) {
      if (!f || typeof f.id !== "string" || typeof f.titre !== "string") continue;
      const page = `${base}#fiche/${f.id}`;
      const title = str(f.titre);
      let heading = title;
      let buffer = [str(f.resume)].filter(Boolean);
      let level = 1;
      const flush = () => {
        const text = squash(buffer.join(" "));
        if (text.length >= 40) out.push({ page, anchor: `fiche/${f.id}`, headingPath: heading === title ? [title] : [title, heading], heading, level, text });
        buffer = [];
      };
      if (Array.isArray(f.corps)) {
        for (const part of f.corps) {
          if (typeof part === "string") buffer.push(squash(part));
          else if (part && typeof part.h === "string") {
            flush();
            heading = str(part.h);
            level = 2;
          }
        }
      }
      flush();
      if (Array.isArray(f.aRetenir) && f.aRetenir.length) {
        heading = "À retenir";
        level = 2;
        buffer = f.aRetenir.filter((s) => typeof s === "string").map(squash);
        flush();
      }
      if (Array.isArray(f.tableaux)) {
        for (const tab of f.tableaux) {
          if (!tab || !Array.isArray(tab.lignes)) continue;
          heading = str(tab.titre) || title;
          level = 2;
          buffer = tab.lignes.flat().filter((s) => typeof s === "string").map(squash);
          flush();
        }
      }
    }
  }
  if (kb && Array.isArray(kb.faq)) {
    kb.faq.forEach((entry, i) => {
      if (!entry || typeof entry.q !== "string" || typeof entry.a !== "string") return;
      const text = squash(entry.a);
      if (text.length < 20) return;
      out.push({ page: `${base}#faq`, anchor: "faq", headingPath: ["Questions et réponses", squash(entry.q)], heading: squash(entry.q), level: 2, text, ordinal: i });
    });
  }
  if (kb && Array.isArray(kb.timeline)) {
    const text = squash(kb.timeline.map((s) => (s && typeof s.t === "string" ? s.t : "")).filter(Boolean).join(" "));
    if (text.length >= 40) out.push({ page: `${base}#parcours`, anchor: "parcours", headingPath: ["Parcours d'installation"], heading: "Parcours d'installation", level: 1, text });
  }
  return out;
}

/**
 * Sections from a guided fiche (window.FICHES.<id>): titre, resume, guide.reperes [{k,v,d}], guide.cas.items
 * [{t,d}], guide.onglets [{titre, blocs:[{note}|{etapes:[{t,d,ou,cout,obtenez}]}]}]. Only strings are read.
 */
export function segmentGuidedFiche(f, origin) {
  const out = [];
  if (!f || typeof f.id !== "string" || typeof f.titre !== "string") return out;
  const base = origin.replace(/\/+$/, "") + "/";
  const page = `${base}#fiche/${f.id}`;
  const title = squash(f.titre);
  const str = (v) => (typeof v === "string" ? squash(v) : "");
  const push = (heading, parts, level = 2) => {
    const text = squash(parts.filter(Boolean).join(" "));
    if (text.length >= 40) out.push({ page, anchor: `fiche/${f.id}`, headingPath: heading === title ? [title] : [title, heading], heading, level, text });
  };
  push(title, [str(f.resume), ...(Array.isArray(f.guide?.reperes) ? f.guide.reperes.map((r) => [str(r?.k), str(r?.v), str(r?.d)].filter(Boolean).join(" : ")) : [])], 1);
  if (Array.isArray(f.guide?.cas?.items)) push(str(f.guide.cas.titre) || "Votre cas", f.guide.cas.items.map((it) => [str(it?.t), str(it?.d)].filter(Boolean).join(". ")));
  for (const tab of f.guide?.onglets ?? []) {
    const parts = [];
    for (const bloc of tab?.blocs ?? []) {
      if (!bloc) continue;
      if (typeof bloc.note === "string") parts.push(squash(bloc.note));
      for (const step of bloc.etapes ?? []) {
        if (!step) continue;
        parts.push([str(step.t), str(step.d), Array.isArray(step.ou) ? step.ou.filter((s) => typeof s === "string").join(", ") : "", str(step.cout), str(step.obtenez)].filter(Boolean).join(" "));
      }
      for (const key of ["items", "points", "lignes"]) {
        if (Array.isArray(bloc[key])) parts.push(bloc[key].map((x) => (typeof x === "string" ? x : [str(x?.t), str(x?.d)].filter(Boolean).join(". "))).join(" "));
      }
    }
    push(str(tab?.titre) || title, parts);
  }
  return out;
}

// ---------------------------------------------------------------------------------------------
// BM25 over the sections. The index is built once; a query is the expanded term map.
// ---------------------------------------------------------------------------------------------

export function buildIndex(sections, { k1 = 1.2, b = 0.75 } = {}) {
  const docs = sections.map((s) => {
    const tf = new Map();
    // the heading counts twice: it names what the section is about
    const tokens = [...tokenize(s.headingPath.join(" ")), ...tokenize(s.headingPath.join(" ")), ...tokenize(s.text)];
    for (const t of tokens) tf.set(t, (tf.get(t) ?? 0) + 1);
    return { tf, length: tokens.length };
  });
  const df = new Map();
  for (const d of docs) for (const t of d.tf.keys()) df.set(t, (df.get(t) ?? 0) + 1);
  const avgLength = docs.length ? docs.reduce((a, d) => a + d.length, 0) / docs.length : 0;
  return { sections, docs, df, avgLength, k1, b, size: docs.length };
}

/** The BM25 idf, floored at a small positive value so a very common term still counts a little. */
function idf(index, term) {
  const n = index.df.get(term) ?? 0;
  const N = index.size;
  return Math.max(0.05, Math.log(1 + (N - n + 0.5) / (n + 0.5)));
}

/**
 * Scores every section against the expanded terms. `boostPage` (a page URL or fragment path) multiplies
 * the score of sections on that page. Returns the ranked list [{ section, score, relevance, matched: [terms] }]:
 * `relevance` is the score as a share of the mass the query could reach at most in this index (each known
 * term at its weight, saturated), so it compares across corpora of any size; 1 is a section holding every term.
 */
export function search(index, expansion, { boostPage = null, boost = 1.3, limit = 10 } = {}) {
  const { terms } = expansion;
  // the relevance mass a section could capture at most: every term the index knows, at its weight
  let attainable = 0;
  for (const [term, weight] of terms) {
    if ((index.df.get(term) ?? 0) > 0) attainable += weight * idf(index, term) * (index.k1 + 1);
  }
  const results = [];
  for (let i = 0; i < index.size; i++) {
    const d = index.docs[i];
    let score = 0;
    const matched = [];
    for (const [term, weight] of terms) {
      const f = d.tf.get(term);
      if (!f) continue;
      const denom = f + index.k1 * (1 - index.b + (index.b * d.length) / (index.avgLength || 1));
      score += weight * idf(index, term) * ((f * (index.k1 + 1)) / denom);
      matched.push(term);
    }
    if (score <= 0) continue;
    const section = index.sections[i];
    if (boostPage && onPage(section, boostPage)) score *= boost;
    results.push({ section, score, relevance: attainable > 0 ? Math.min(1, score / attainable) : 0, matched });
  }
  results.sort((a, b2) => b2.score - a.score || a.section.page.localeCompare(b2.section.page));
  return results.slice(0, limit);
}

/** Whether a section is on the page the reader is on: a URL, or a path such as "fiche/bail" or "prevoyance/". */
export function onPage(section, page) {
  if (!page) return false;
  const p = String(page).replace(/^#/, "");
  if (section.page === p) return true;
  const rel = section.page.replace(/^https?:\/\/[^/]+\//, "");
  return rel === p || rel === p.replace(/^\//, "") || rel === `#${p}` || section.anchor === p;
}

// ---------------------------------------------------------------------------------------------
// The verdict: a typed answer, computed by code from the ranked list and the query.
// ---------------------------------------------------------------------------------------------

export const VERDICTS = Object.freeze({
  FOUND: "found", // Trouvé dans le guide
  TWO_PAGES: "two_pages", // Deux pages possibles
  CLARIFY: "clarify", // Précisez
  NOT_IN_GUIDE: "not_in_guide", // Pas dans ce guide
});

export const THRESHOLDS = Object.freeze({
  minContentWords: 1, // fewer meaningful words: Précisez
  minQueryChars: 4,
  minRelevance: 0.2, // the best section captures less than a fifth of the query's reachable mass: Pas dans ce guide
  minCoverage: 0.34, // the share of the reader's own words the best section answers for, itself or through its synonyms
  closeMargin: 0.12, // top two within 12 % of each other, on different pages: Deux pages possibles
});

/**
 * Decides the verdict. `results` is the ranked list from `search`; `expansion` from `expandQuery`.
 * Returns { verdict, best, second, margin, searched: [words], reason, coverage }.
 */
export function decide(query, expansion, results, thresholds = THRESHOLDS) {
  const words = contentWords(query);
  const searched = [...expansion.terms.keys()];
  if (String(query).trim().length < thresholds.minQueryChars || words.length < thresholds.minContentWords) {
    return { verdict: VERDICTS.CLARIFY, best: null, second: null, margin: null, searched, reason: "too_short" };
  }
  const best = results[0] ?? null;
  if (!best || best.relevance < thresholds.minRelevance) {
    return { verdict: VERDICTS.NOT_IN_GUIDE, best: null, second: null, margin: null, searched, reason: best ? "below_threshold" : "no_match" };
  }
  const coverage = coverageOf(expansion, best.matched);
  if (coverage < thresholds.minCoverage) {
    return { verdict: VERDICTS.NOT_IN_GUIDE, best: null, second: null, margin: null, searched, reason: "words_not_covered", coverage };
  }
  // the second candidate on another page
  const second = results.find((r) => r.section.page !== best.section.page) ?? null;
  const margin = second ? (best.score - second.score) / best.score : 1;
  if (second && margin < thresholds.closeMargin) {
    return { verdict: VERDICTS.TWO_PAGES, best, second, margin, searched, reason: "close_scores", coverage };
  }
  return { verdict: VERDICTS.FOUND, best, second, margin, searched, reason: "clear_winner", coverage };
}

/** The share of the reader's own tokens that a matched term stands for (the token itself or one of its synonyms). */
export function coverageOf(expansion, matched) {
  const own = new Set(expansion.tokens);
  if (own.size === 0) return 0;
  const covered = new Set();
  for (const term of matched) for (const o of expansion.serves.get(term) ?? []) if (own.has(o)) covered.add(o);
  return covered.size / own.size;
}

// ---------------------------------------------------------------------------------------------
// The highlighter: the supporting passage, cut at sentence bounds around the first match, with each
// matched word marked on the original characters (through the fold map). Returns parts, never HTML.
// ---------------------------------------------------------------------------------------------

/**
 * Finds the matches of `terms` (stemmed, folded tokens) in `text`: [{ start, end }] in original offsets.
 * A text word matches a term when its stem equals the term.
 */
export function findMatches(text, terms) {
  const { folded, map } = fold(text);
  const wanted = new Set(terms);
  const matches = [];
  const re = /[\p{L}\p{N}]+/gu;
  let m;
  while ((m = re.exec(folded)) !== null) {
    const word = m[0];
    if (!wanted.has(stem(word)) && !wanted.has(word)) continue;
    const start = map[m.index];
    const lastFolded = m.index + word.length - 1;
    const end = map[lastFolded] + 1 + extraLength(text, map[lastFolded]);
    matches.push({ start, end });
  }
  return matches;
}

/** The original character at `index` may be two UTF-16 units (an astral character). */
function extraLength(text, index) {
  const code = text.codePointAt(index);
  return code > 0xffff ? 1 : 0;
}

/**
 * The passage: the sentences around the first match, up to about `maxChars`, as parts [{ text, matched }].
 * With no match, the start of the text. Cut points are sentence ends ('. ', '! ', '? ', ' ; ') when present.
 */
export function passage(text, terms, { maxChars = 320 } = {}) {
  const matches = findMatches(text, terms);
  let start = 0;
  let end = Math.min(text.length, maxChars);
  if (matches.length) {
    const first = matches[0].start;
    // back to the previous sentence end within maxChars before the match; else a word break within maxChars/3
    const floor = Math.max(0, first - maxChars);
    const before = text.slice(floor, first);
    const cut = Math.max(before.lastIndexOf(". "), before.lastIndexOf("! "), before.lastIndexOf("? "), before.lastIndexOf(" ; "));
    if (cut >= 0) start = floor + cut + 2;
    else {
      const near = Math.max(0, first - Math.floor(maxChars / 3));
      const space = text.indexOf(" ", near);
      start = near === 0 ? 0 : space >= 0 && space < first ? space + 1 : near;
    }
    // forward to a sentence end after maxChars from start, else to the text end or a word break
    end = Math.min(text.length, start + maxChars);
    if (end < text.length) {
      const tail = text.slice(start, end);
      const lastEnd = Math.max(tail.lastIndexOf(". "), tail.lastIndexOf("! "), tail.lastIndexOf("? "));
      if (lastEnd > maxChars / 2) end = start + lastEnd + 1;
      else {
        const space = tail.lastIndexOf(" ");
        if (space > 0) end = start + space;
      }
    }
  } else if (end < text.length) {
    const space = text.lastIndexOf(" ", end);
    if (space > 0) end = space;
  }
  const parts = [];
  let cursor = start;
  for (const mt of matches) {
    if (mt.end <= start || mt.start >= end) continue;
    if (mt.start > cursor) parts.push({ text: text.slice(cursor, mt.start), matched: false });
    parts.push({ text: text.slice(Math.max(mt.start, cursor), Math.min(mt.end, end)), matched: true });
    cursor = Math.min(mt.end, end);
  }
  if (cursor < end) parts.push({ text: text.slice(cursor, end), matched: false });
  return { parts, start, end, truncatedBefore: start > 0, truncatedAfter: end < text.length, matchCount: matches.length };
}

// ---------------------------------------------------------------------------------------------
// Discovery: the same-origin pages and data files a page links to.
// ---------------------------------------------------------------------------------------------

/**
 * The same-origin page links of an HTML page (href values), resolved against `baseUrl`, fragments and
 * queries removed, pages only (no .css, .js, images, PDFs), at most `limit`, in document order, each once.
 */
export function discoverPages(html, baseUrl, { limit = 40 } = {}) {
  const base = new URL(baseUrl);
  const out = [];
  const seen = new Set();
  const re = /<a\b[^>]*\shref\s*=\s*(?:"([^"]*)"|'([^']*)')/gi;
  let m;
  while ((m = re.exec(html)) !== null && out.length < limit) {
    const raw = (m[1] ?? m[2] ?? "").trim();
    if (!raw || raw.startsWith("#") || /^(mailto|tel|javascript):/i.test(raw)) continue;
    let url;
    try {
      url = new URL(raw, base);
    } catch {
      continue;
    }
    if (url.origin !== base.origin) continue;
    url.hash = "";
    url.search = "";
    if (/\.(css|js|mjs|json|png|jpe?g|gif|svg|webp|ico|pdf|xml|txt|woff2?|mp4|webm|zip)$/i.test(url.pathname)) continue;
    const key = url.href;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(key);
  }
  return out;
}

/**
 * The same-origin data scripts of a page: script src values whose file name says they carry a knowledge
 * base or a fiche (kb.js, fiches/*.js), resolved, queries kept (cache busting), each once.
 */
export function discoverDataScripts(html, baseUrl) {
  const base = new URL(baseUrl);
  const out = [];
  const seen = new Set();
  const re = /<script\b[^>]*\ssrc\s*=\s*(?:"([^"]*)"|'([^']*)')/gi;
  let m;
  while ((m = re.exec(html)) !== null) {
    const raw = (m[1] ?? m[2] ?? "").trim();
    let url;
    try {
      url = new URL(raw, base);
    } catch {
      continue;
    }
    if (url.origin !== base.origin) continue;
    if (!/(^|\/)(kb\.js|fiches\/[^/]+\.js)$/i.test(url.pathname)) continue;
    if (seen.has(url.href)) continue;
    seen.add(url.href);
    out.push(url.href);
  }
  return out;
}

/** A short label for a page URL: its fragment path (fiche/bail) or its path (prevoyance/), else the host. */
export function pageLabel(url) {
  try {
    const u = new URL(url);
    if (u.hash) return u.hash.slice(1);
    return u.pathname === "/" ? u.host : u.pathname.replace(/^\//, "");
  } catch {
    return String(url);
  }
}
