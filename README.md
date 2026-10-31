# soufien.lu

The portfolio site served by GitHub Pages at <https://soufien.lu> (repository `SFHAJJI/sfhajji.github.io`).
Plain static HTML, CSS and vanilla JavaScript: no build step, no framework, no CDN script, no tracking.

## What is here

| Path | What it is |
|---|---|
| `index.html` | The landing page: three pieces of work and the CV. |
| `lex/index.html` | The case study "Lex : un système de recherche juridique construit comme un RAG d'entreprise". Every claim about Lex is checkable in the public repository `SFHAJJI/lex` or on <https://law.soufien.lu>; the deep links were verified by HTTP request on 31 October 2026. |
| `lux-guide-assistant/` | "Assistant du guide « Vivre au Luxembourg »": an assistant inside the public newcomer guide, which recognises the fiche being read, opens the right fiche when the answer is elsewhere, and highlights the passage that carries it. Served from its own repository, `SFHAJJI/lux-guide-assistant`, at <https://sfhajji.github.io/lux-guide-assistant/>; the landing page links to it. |
| `energy/index.html` | The Energy Copilot architecture case study, adapted from the repository `SFHAJJI/energy-copilot` (`docs/architecture-page.html`). The live deployment is offline; the page says so. |
| `cv/` | The CV in English and French (PDF) and a page linking both. |
| `assets/site.css`, `assets/theme.js` | Shared styles (light and dark by preference, with a toggle; works at 320 px; visible focus) and the theme toggle. |
| `404.html`, `CNAME`, `.nojekyll` | The not-found page, the custom domain, and the switch that keeps Pages from running Jekyll. |

## Rules this site follows

- No person is named except the site's owner on the landing and CV pages; no e-mail address or contact detail.
- No third-party content is copied into the repository.
- Every claim about Lex is checkable in `SFHAJJI/lex` or on the live site, and says "not yet" where something is not done (the Lex assistant is built and switched off).

## Licence

MIT for the code of this site (`LICENSE`). The CVs are the owner's documents.
