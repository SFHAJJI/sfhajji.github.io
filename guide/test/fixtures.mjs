// Synthetic fixtures written for these tests. Nothing here comes from the newcomer guide or any other site.

export const ORIGIN = "https://example.test";

export const PAGE_HTML = `<!doctype html>
<html lang="fr"><head><title>Guide de test</title>
<style>h1 { color: red }</style>
<script>window.X = "<h2>pas un titre</h2>";</script>
</head>
<body>
<nav id="menu"><a href="#logement">Logement</a> <a href="/mobilite/">Mobilité</a> <a href="https://autre.test/page">Ailleurs</a>
<a href="app/styles.css">css</a> <a href="/mobilite/">doublon</a> <a href="mailto:x@y.z">mail</a></nav>
<script src="app/kb.js?v=3"></script><script src="app/fiches/vehicule.js"></script><script src="app/ui.js"></script>
<script src="https://cdn.test/lib.js"></script>
<main>
<p>Intro trop courte.</p>
<section id="logement">
<h1>Se loger</h1>
<p>Trouver un logement demande du temps. Le loyer se paie chaque mois et le bail fixe les conditions de la location.</p>
<h2 id="caution">La garantie locative</h2>
<p>La garantie locative, souvent appel&eacute;e caution, est vers&eacute;e au propri&eacute;taire ou bloqu&eacute;e sur un compte bancaire. Elle est rendue &agrave; la fin du bail si le logement est en bon &eacute;tat.</p>
<h3>Montant</h3>
<p>Le montant de la garantie est plafonn&eacute; &agrave; deux mois de loyer dans la plupart des cas, hors charges.</p>
</section>
<section id="voiture">
<h1>Sa voiture</h1>
<p>Un v&eacute;hicule import&eacute; doit &ecirc;tre immatricul&eacute; dans les six mois. Le contr&ocirc;le technique est obligatoire avant la demande de plaques.</p>
<h2>L&rsquo;assurance du v&eacute;hicule</h2>
<p>L&rsquo;assurance responsabilit&eacute; civile automobile est obligatoire. Elle couvre les dommages caus&eacute;s aux tiers, pas ceux de votre propre voiture.</p>
</section>
</main>
</body></html>`;

export const SECOND_PAGE_HTML = `<!doctype html><html><head><title>Mobilit&eacute;</title></head><body>
<h1 id="top">Se d&eacute;placer</h1>
<p>Les transports publics sont gratuits pour tous. Le tram et les bus desservent la capitale et les lignes de train relient les communes.</p>
<h2>Le v&eacute;lo</h2>
<p>Un v&eacute;lo vol&eacute; est parfois couvert par l&rsquo;assurance habitation, selon le contrat et sa franchise. V&eacute;rifiez les exclusions avant de d&eacute;clarer un sinistre.</p>
</body></html>`;

export const KNOWLEDGE = {
  fiches: [
    {
      id: "banque",
      titre: "Ouvrir un compte",
      resume: "Un compte bancaire est utile dès la première semaine pour recevoir le salaire.",
      corps: [
        "La banque demande une pièce d'identité et un justificatif de domicile.",
        { h: "Les frais" },
        "Les frais de tenue de compte varient selon la banque et le type de carte bancaire choisi.",
      ],
      aRetenir: ["Comparer les frais avant de signer.", "Demander un IBAN luxembourgeois pour le salaire."],
    },
    { id: "cassé", titre: 42, corps: ["ignoré"] },
  ],
  faq: [
    { q: "Faut-il déclarer son chien ?", a: "Oui, le chien est déclaré à la commune, qui perçoit une taxe annuelle et exige une assurance responsabilité civile." },
    { q: "Court", a: "Non." },
  ],
  timeline: [{ t: "Semaine 1 : déclaration d'arrivée à la commune." }, { t: "Semaine 2 : affiliation à la caisse de maladie et ouverture du compte." }],
};

export const GUIDED = {
  id: "velo",
  titre: "Rouler à vélo",
  resume: "Le vélo est un moyen de transport encouragé par des aides.",
  guide: {
    reperes: [{ k: "Aide", v: "jusqu'à 600 €", d: "pour un vélo électrique neuf" }],
    cas: { titre: "Votre cas", items: [{ t: "Vélo neuf", d: "La demande se fait en ligne après l'achat, avec la facture." }] },
    onglets: [
      { id: "etapes", titre: "Étapes", blocs: [{ note: "Gardez la facture originale." }, { etapes: [{ t: "Acheter", d: "chez un vendeur établi", cout: "variable", obtenez: "la facture" }] }] },
    ],
  },
};
