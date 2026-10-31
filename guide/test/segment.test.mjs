import test from "node:test";
import assert from "node:assert/strict";
import { segmentHtml, segmentKnowledge, segmentGuidedFiche, discoverPages, discoverDataScripts, decodeEntities, pageLabel } from "../engine.js";
import { PAGE_HTML, SECOND_PAGE_HTML, KNOWLEDGE, GUIDED, ORIGIN } from "./fixtures.mjs";

test("segmentHtml splits a page by h1 to h3, with the heading path and the nearest id", () => {
  const sections = segmentHtml(PAGE_HTML, `${ORIGIN}/`);
  assert.equal(sections[0].heading, "Guide de test", "the text before the first heading (the menu) stands under the title");
  assert.equal(sections[0].level, 0);
  const headed = sections.slice(1);
  assert.deepEqual(headed.map((s) => s.heading), ["Se loger", "La garantie locative", "Montant", "Sa voiture", "L’assurance du véhicule"]);
  const caution = headed[1];
  assert.equal(caution.anchor, "caution");
  assert.deepEqual(caution.headingPath, ["Se loger", "La garantie locative"]);
  assert.match(caution.text, /appelée caution, est versée au propriétaire/);
  const montant = headed[2];
  assert.equal(montant.anchor, "caution", "an h3 without an id takes the nearest id before it");
  assert.deepEqual(montant.headingPath, ["Se loger", "La garantie locative", "Montant"]);
  assert.equal(headed[3].anchor, "voiture", "a section id before the heading is the heading's anchor");
  assert.deepEqual(headed[4].headingPath, ["Sa voiture", "L’assurance du véhicule"], "a new h1 resets the deeper path");
  for (const s of sections) assert.equal(s.page, `${ORIGIN}/`);
});

test("segmentHtml drops scripts and styles and the short intro, and decodes entities", () => {
  const sections = segmentHtml(PAGE_HTML, `${ORIGIN}/`);
  const all = sections.map((s) => s.text).join(" ");
  assert.doesNotMatch(all, /pas un titre|color: red/);
  assert.doesNotMatch(sections.slice(1).map((s) => s.text).join(" "), /Intro trop courte/, "the intro belongs to the title section, not to a headed one");
  assert.match(all, /contrôle technique/);
  assert.equal(decodeEntities("&eacute;&#233;&#xE9;&amp;&unknown;"), "ééé&&unknown;");
});

test("segmentHtml keeps a page's text before the first heading under its title when long enough", () => {
  const html = `<html><head><title>Titre</title></head><body><p>${"Un texte sans titre assez long pour compter. ".repeat(3)}</p><h1>Suite</h1><p>${"Encore du texte pour la suite. ".repeat(3)}</p></body></html>`;
  const sections = segmentHtml(html, `${ORIGIN}/p/`);
  assert.equal(sections[0].heading, "Titre");
  assert.equal(sections[0].level, 0);
  assert.equal(sections[1].heading, "Suite");
});

test("segmentKnowledge reads fiches, faq and timeline of the documented shape and ignores broken entries", () => {
  const sections = segmentKnowledge(KNOWLEDGE, ORIGIN);
  const pages = new Set(sections.map((s) => s.page));
  assert.ok(pages.has(`${ORIGIN}/#fiche/banque`));
  assert.ok(pages.has(`${ORIGIN}/#faq`));
  assert.ok(pages.has(`${ORIGIN}/#parcours`));
  const banque = sections.filter((s) => s.page.endsWith("#fiche/banque"));
  assert.deepEqual(banque.map((s) => s.heading), ["Ouvrir un compte", "Les frais", "À retenir"]);
  assert.equal(banque[0].anchor, "fiche/banque");
  assert.match(banque[0].text, /compte bancaire est utile.*pièce d'identité/);
  assert.ok(!sections.some((s) => /ignoré/.test(s.text)), "a fiche with no string title is ignored");
  const faq = sections.filter((s) => s.page.endsWith("#faq"));
  assert.equal(faq.length, 1, "a one-word answer is too short");
  assert.equal(faq[0].heading, "Faut-il déclarer son chien ?");
});

test("segmentGuidedFiche reads reperes, cas and onglets", () => {
  const sections = segmentGuidedFiche(GUIDED, ORIGIN);
  assert.deepEqual(sections.map((s) => s.heading), ["Rouler à vélo", "Votre cas", "Étapes"]);
  assert.match(sections[0].text, /Aide : jusqu'à 600 € : pour un vélo électrique neuf/);
  assert.match(sections[2].text, /Gardez la facture originale\. Acheter chez un vendeur établi variable la facture/);
  assert.deepEqual(segmentGuidedFiche({ id: 1 }, ORIGIN), []);
});

test("discoverPages keeps same-origin pages once, in order, without assets, fragments or mail links", () => {
  const pages = discoverPages(PAGE_HTML, `${ORIGIN}/`);
  assert.deepEqual(pages, [`${ORIGIN}/mobilite/`]);
  assert.deepEqual(discoverPages(PAGE_HTML, `${ORIGIN}/`, { limit: 0 }), []);
});

test("discoverDataScripts keeps kb.js and fiches/*.js of the same origin, with their cache-busting query", () => {
  const scripts = discoverDataScripts(PAGE_HTML, `${ORIGIN}/`);
  assert.deepEqual(scripts, [`${ORIGIN}/app/kb.js?v=3`, `${ORIGIN}/app/fiches/vehicule.js`]);
});

test("pageLabel names a page by its fragment path, else its path, else its host", () => {
  assert.equal(pageLabel(`${ORIGIN}/#fiche/banque`), "fiche/banque");
  assert.equal(pageLabel(`${ORIGIN}/mobilite/`), "mobilite/");
  assert.equal(pageLabel(`${ORIGIN}/`), "example.test");
  const second = segmentHtml(SECOND_PAGE_HTML, `${ORIGIN}/mobilite/`);
  assert.equal(second[0].anchor, "top");
});
