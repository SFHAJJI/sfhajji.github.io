# Dictionary changelog

The expert dictionary is a versioned asset (SPEC §0 rule 6). Every entry here says why a row of
`concepts.yaml`, `keywords.yaml` or `abbreviations.yaml` exists. Models may propose rows; a person
merges them by pull request, with a line below.

## 2026-10-31 — seed

**Why these concepts.** The corpus is a newcomer-to-Luxembourg guide, so the seed lists what a
newcomer asks in the first months, grouped by the topics of SPEC §1 (housing, vehicle, liability,
administration, health, work, money, other). 65 concepts:

- housing (11): logement, bail, garantie_locative, loyer, etat_des_lieux, colocation,
  charges_locatives, agence_immobiliere, preavis, proprietaire, locataire.
- vehicle (10): voiture, immatriculation, carte_grise, controle_technique, permis_de_conduire,
  vignette, assurance_auto, snca, importation_vehicule, stationnement.
- liability (5): responsabilite_civile, degat_des_eaux, sinistre, franchise, assurance_habitation.
- administration (9): commune, biergercenter, certificat_de_residence, inscription_commune,
  titre_de_sejour, matricule, carte_identite, guichet, demenagement.
- health (7): cns, ccss, medecin, carte_securite_sociale, mutuelle, urgences, hopital.
- work (8): contrat_de_travail, adem, fiche_retenue_impot, classe_impot, declaration_impot,
  salaire, chomage, conge.
- money (5): compte_bancaire, iban, luxtrust, garantie_bancaire, carte_bancaire.
- other (10): transports_gratuits, mkaart, cfl, velo, ecole, cours_de_langue, energie, internet,
  dechets, animaux. Mobility, school, utilities and daily life sit under `other` because SPEC §1
  closes the topic list and `scope_filters.topic` must compare with `corpus_index.topic`.

**Why these variants.** Each concept has a French primary variant (the guide's main language), an
English variant, and a German one where the German word is certain (administrative German is the
Luxembourg usage, e.g. "Anmeldung", "Mietkaution", "Führerschein"). Secondary variants are the
words a reader types instead of the guide's word ("caution" for the rental deposit, "mairie" for
the commune, "MOT" for the inspection). Generic words shared by several concepts carry a low
weight so that they match but never decide alone: "assurance / insurance" (0.5) is a variant of
assurance_auto, responsabilite_civile and mutuelle; "registration" (0.7) of immatriculation and
inscription_commune; "tax" (0.6) of fiche_retenue_impot. These shared single words are what the
clarification rule `single_term_multiple_concepts` fires on.

**Why the weights.** Primary = 1.0, always. Secondary = 0.9 for a synonym the guide may itself use,
0.8 for a near synonym, 0.7 or lower for a generic word. The question parser multiplies by 0.6
(SPEC §2) when it expands a matched concept.

**What was deliberately left out.** No person's name, no company, no brand of insurer or bank. Words
that are typed-answer cues ("téléphone", "adresse", "combien") are not variants of any concept,
otherwise a phone question would match the internet concept.

**Abbreviations** (`abbreviations.yaml`): the short forms a reader types, each with one expansion:
RC, CNS, CCSS, ADEM, CT, SNCA, SNCT, CFL, INL, SSM, CDI, CDD, EDL, TVA, VAT, ID, NIF, SSN, TÜV,
KFZ. When a short form has two meanings the newcomer-guide meaning wins and the note says so (CT
is the vehicle inspection, not the employment contract).

**Match rules the file relies on** (in `guide_rag/question/dictionary.py`): whole-word, accent-folded,
lightly stemmed (plural and feminine endings), stop words dropped inside phrases ("fiche de
retenue d'impôt" matches "fiche retenue impôt"); a longer phrase hides the shorter words it
contains ("assurance auto" is not "assurance"); one match per concept and place even when a word
is a variant in two languages ("commune").

## 2026-10-31 — growth from the first real runs (50 documents, 426 headings)

The series' loop: a miss becomes a dictionary entry, with the question or the document that
motivated it. Nothing here was written by a model.

**Renamed.** `inscription_commune` becomes `declaration_arrivee`: the guide's own word is
"déclaration d'arrivée" (document "Les huit premiers jours"; the index tags it so). Grown with
"déclarer son arrivée", "s'inscrire à la commune", "enregistrement", "enregistrement à la
commune", "registre de la population", "arrivée"; EN "register at the commune", "arrival
declaration", "arrival"; DE "Ankunftserklärung". Motivating questions: "s'inscrire à la commune",
"enregistrement à la commune", "registre".

**Merged.** `garantie_bancaire` (money) is gone: in this guide the bank guarantee is how the rental
deposit is paid ("Signer un bail › La garantie bancaire, un piège de calendrier"), so "garantie
bancaire", "caution bancaire", "bank guarantee", "Bankgarantie" are secondary variants of
`garantie_locative`, which also gains "rental guarantee". Motivating question: "deposit / rental
guarantee / garantie bancaire".

**Split.** Childcare leaves `ecole` for its own `garde_enfants` (document "Garde d'enfants et
chèque-service"): crèche, chèque-service, maison relais, assistante parentale, garderie; childcare,
nursery, daycare, service voucher, after-school care; Kinderbetreuung, Kita, Krippe. `ecole` gains
"scolariser", "scolarité", "école publique / internationale / européenne", "enrolment",
"enrollment", "international school", "european school", "Einschulung" (document "Scolariser ses
enfants").

**New concept `impots`** (money) takes the generic tax words that were secondary variants of
`fiche_retenue_impot` and `declaration_impot` ("impôts", "impôt", "tax", "income tax",
"administration des contributions"), plus "fiscalité", "fiscal", "contributions directes", "ACD",
"taxes", "taxation", "tax office", "Steuern", "Einkommensteuer". `classe_impot` and
`declaration_impot` move from work to money, where the index files "Classes d'impôt" and "Ce qui
réduit votre impôt"; `fiche_retenue_impot` stays under work (the employer applies it) and gains
"fiche de retenue".

**Variants added to existing concepts**, each from a question of the first runs:
- `immatriculation`: "immatriculer son véhicule", "car registration", "register a car", "register
  my car", "number plate", "licence plate", "plates" ("register my car", "plates").
- `responsabilite_civile`: "RC familiale", "responsabilité civile vie privée", "RC vie privée",
  "assurance responsabilité civile", "third-party insurance", "personal liability".
- `bail`: "rental contract", "tenancy". `commune`: "hôtel de ville", LB "Gemeng".
- `cns`: "assurance maladie", "caisse de maladie", "remboursements", "health fund".
- `permis_de_conduire`: "échange de permis", "permis étranger", "exchange a licence".
- `transports_gratuits`: "gratuité des transports", "mobilité", "free transport", LB "Mobilitéit".
- `salaire`: "salaire net / brut", "brut", "net", "net salary", "gross salary", "gross" (document
  "Salaire, coût de la vie et indexation"; question "combien je gagne net").
- `medecin`: "soins", "pharmacie", "se soigner", "pharmacy", "healthcare" ("Se soigner au quotidien").
- `cours_de_langue`: "langues", "langue", "intégration", "contrat d'accueil et d'intégration",
  "languages", "integration", "learn luxembourgish", "Sprachen", "Integration" ("Langues et intégration").
- `internet`: "télécom", "telecom", "connexion", "fibre" ("Internet et téléphonie"). `energie`:
  "fournisseur", "raccordement". `adem`: "emploi", "chercher un emploi", "offre d'emploi", "job",
  "job search", "employment", "Stellensuche" ("Chercher un emploi"). `compte_bancaire`: "moyens de
  paiement", "means of payment" ("Banque et moyens de paiement").

**New concepts from document titles** (title → concept): "Acheter un logement" → `achat_immobilier`
(with "taxe sur la valeur ajoutée" so the TVA abbreviation reaches it); "Déduire les intérêts
d'emprunt" → `pret_immobilier` and `interets_hypothecaires`; "Ce qui réduit votre impôt",
"Économies et avantages fiscaux" → `deduction_fiscale`; "Épargne et retraite", "Conseil fiscal"
(111bis, épargne-logement) → `epargne_retraite`; "Allocations familiales" → `allocations_familiales`;
"Nationalité luxembourgeoise" → `nationalite`; "Habiter en France, en Belgique ou en Allemagne" →
`frontalier`; "Régime des impatriés" → `impatries`; "Exercer en indépendant" → `independant`;
"Simulateurs" (chèques-repas) → `cheques_repas`; "Salaire, coût de la vie et indexation" →
`cout_de_la_vie`; the tax pages' "crédit d'impôt" → `credit_impot`; "Contester une facture ou un
service" → `reclamation`; "Logement abordable et à coût modéré" → `logement_abordable`; "Emménager
et meubler" → `emmenagement` (EN primary "move in", not "moving", which stays with `demenagement`);
"Simulateurs", "Du brut au net" → `simulateur`. Tool pages (Assistant, Comparateur, Paramètres,
jeux, Fiches pratiques, Questions et réponses, Parcours, Accueil, the maps) carry no concept of
their own: their subject is the concepts they list.

**Weak words** (`weak_words.yaml`, new): generic verbs and nouns that never identify a topic
(acheter, faire, obtenir, documents, besoin, get, need, find, papers, kaufen, Unterlagen, …). The
parser keeps them as keywords with weight 0.3 and `weak: true`; retrieval reads the same list.
Motivating questions: "comment obtenir des documents", "where do I get the papers".

**Second pass of the title audit.** "Comment fonctionne l'administration" reached no concept:
`guichet` (the administrative portal) gains "administration", "démarches administratives",
"administratif", "public administration", "paperwork", "Verwaltung", "Behörden". "Les huit
premiers jours" reached none: `declaration_arrivee` gains "huit premiers jours", "premiers jours",
"huit jours", "first days", "first eight days". "Assurer son véhicule / son logement" reached only
`voiture` / `logement`: `assurance_auto` gains "assurer son véhicule", "assurer sa voiture", "insure
a car"; `assurance_habitation` gains "assurer son logement", "insure a home". The German "Rente"
was removed from `epargne_retraite`: stemmed, it collided with the English "rent" of `loyer`;
"Rentenversicherung" replaces it. Tool pages are the only titles left without a concept.

**From the evaluation over the real corpus (46 golden questions).** "Quelles garanties couvre
l'assurance habitation" must reach `assurance_habitation › Ce que couvre réellement un contrat`:
the concept gains the fiche's own words "couvrir le logement", "couverture du logement",
"couverture", "garanties du contrat", "cover the home", "coverage"; `logement` gains the bare
"habitation" and "dwelling" so habitation ↔ logement are reachable while "assurance habitation"
(a longer phrase) still wins. German "wie melde ich mich bei der Gemeinde an": `declaration_arrivee`
gains "melden", "melde", "sich anmelden", "bei der Gemeinde anmelden", "Anmeldung bei der Gemeinde",
"Wohnsitz anmelden"; "mich", "sich", "dich", "euch", "uns", "ihnen", "ihm" become German stop
words; "Luxembourg / Luxemburg / Lëtzebuerg" become weak words in every language (the whole corpus
is about it). "ça marche comment ?": "marche", "marcher", "fonctionne", "fonctionner",
"fonctionnement", "work", "works", "working", "funktioniert", "funktionieren" become weak words, and
the clarification rule says pronoun_only when a pronoun is the only non-weak thing in the question.
Second look at g14: the bare "couverture" / "coverage" were withdrawn (they hit the comparateur's
"matrice de couverture" line, the wrong page); the expected section's own words come in instead:
"incendie", "bris de glace", "vol", "socle de garanties", "exclusions", "fire", "theft".
`assurance_habitation` moves from liability to housing, the topic under which the index files
"Assurer son logement". Superlatives and size words ("meilleur", "mieux", "bon", "best", "better",
"beste", "gut", "neu", …) become weak words: "le meilleur restaurant" must not answer from "au
meilleur prix".
