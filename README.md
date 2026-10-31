# soufien.lu

The portfolio site served by GitHub Pages at <https://soufien.lu> (repository `SFHAJJI/sfhajji.github.io`).
Plain static HTML, CSS and vanilla JavaScript: no build step, no framework, no CDN script, no tracking.

## What is here

| Path | What it is |
|---|---|
| `index.html` | The landing page: three pieces of work and the CV. |
| `lex/index.html` | The case study "Lex : un système de recherche juridique construit comme un RAG d'entreprise". Every claim about Lex is checkable in the public repository `SFHAJJI/lex` or on <https://law.soufien.lu>; the deep links were verified by HTTP request on 31 October 2026. |
| `guide/` | "Assistant du guide nouveaux arrivants (démo)": a deterministic assistant over a public newcomer guide, running entirely in the visitor's browser. |
| `energy/index.html` | The Energy Copilot architecture case study, adapted from the repository `SFHAJJI/energy-copilot` (`docs/architecture-page.html`). The live deployment is offline; the page says so. |
| `cv/` | The CV in English and French (PDF) and a page linking both. |
| `assets/site.css`, `assets/theme.js` | Shared styles (light and dark by preference, with a toggle; works at 320 px; visible focus) and the theme toggle. |
| `404.html`, `CNAME`, `.nojekyll` | The not-found page, the custom domain, and the switch that keeps Pages from running Jekyll. |

## How the guide demo works

`guide/engine.js` is one ES module, used unchanged by the page (`guide/app.js`) and by the tests:

1. **Loading.** At load, the page fetches `https://lux-guide.github.io/` and the same-origin pages its home page links to (at most 40), plus the guide's data files (`kb.js`, `fiches/*.js`), which are evaluated inside a sandboxed `iframe` (opaque origin) that only posts plain data back. A progress line shows what was read and when. Nothing of the guide is stored in this repository: the guide has no licence, so it is only fetched at runtime by the visitor's browser (GitHub Pages serves `Access-Control-Allow-Origin: *`).
2. **Segmenting.** Each page is split by its `h1` to `h3` headings into sections carrying the page URL, the anchor (the heading's `id` or the nearest one before it), the heading path and the text. The data files' fiches become sections with the guide's own `#fiche/<id>` anchors.
3. **Retrieval.** Text is folded (NFD without marks, lower case, one apostrophe, œ → oe) with an offset map back to the original characters; stopwords are dropped and plurals stemmed. A hand-written FR/EN dictionary of domain synonyms (housing, vehicles, civil liability, registration, insurance, the commune, tax, health…) expands the query at weight 0.6, phrases first. BM25 (k1 = 1.2, b = 0.75) ranks the sections, the heading counted twice; the page the reader is on (`?page=fiche/bail`, `?page=prevoyance/`) is boosted ×1.3. The relevance shown is the share of the query's reachable mass a section captured.
4. **Typed answer card.** The verdict is computed by code: *Précisez* (under 4 characters or no content word), *Pas dans ce guide* (relevance under 0.2, or under a third of the reader's words covered by themselves or their synonyms) saying what was searched, *Deux pages possibles* (the top two within 12 % on different pages: both shown, the reader chooses), else *Trouvé dans le guide* with the margin. The supporting passage is cut at sentence bounds around the first match and its matched words are marked on the original text; a link opens the page at its anchor. Only the guide's own sentences are ever shown.

## Running the tests

```sh
npm test
# or
node --test "guide/test/*.test.mjs"
```

Node 20 or later, no dependency. The 26 tests cover segmentation, discovery, folding, tokens, the dictionary, BM25, the page boost, the four verdicts and their thresholds, and the highlighter, over synthetic fixtures written for the tests (`guide/test/fixtures.mjs`). Nothing is fetched during the tests, and no browser is used.

## Rules this site follows

- No person is named except the site's owner on the landing and CV pages; no e-mail address or contact detail.
- No third-party content is copied into the repository.
- Every claim about Lex is checkable in `SFHAJJI/lex` or on the live site, and says "not yet" where something is not done (the Lex assistant is built and switched off).

## Licence

MIT for the code of this site (`LICENSE`). The CVs are the owner's documents. The guide the demo reads belongs to its author.
