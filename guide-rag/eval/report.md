# Evaluation per question type

Generated 2026-10-31T11:46:09Z on index `1d1bbf848338` with pipeline `guide-rag/0.1`.
46 questions; ok 100 %; quote fidelity 100 %; median 942.9 ms.

| type | n | ok | level-0 | retrieval | found | fidelity | not-found ok | clarify | median ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| factual | 10 | 100 % | 100 % | 100 % | 90 % | 100 % | 90 % | 0 % | 615.4 |
| listing | 8 | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | 0 % | 1083.1 |
| amount | 4 | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | 0 % | 1200.1 |
| date | 2 | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | 0 % | 1258.2 |
| yes/no | 4 | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | 0 % | 945.2 |
| address/phone | 2 | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | 0 % | 1208.6 |
| typo | 2 | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | 0 % | 1287.5 |
| EN | 3 | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | 0 % | 896.4 |
| DE | 2 | 100 % | 100 % | 100 % | 50 % | 100 % | 50 % | 0 % | 1207.3 |
| on-page | 2 | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | 0 % | 1101.7 |
| compound | 1 | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | 0 % | 1111.2 |
| vague | 2 | 100 % | - | - | 50 % | 100 % | 100 % | 100 % | 1036.2 |
| out-of-scope | 4 | 100 % | - | - | 0 % | 100 % | 100 % | 0 % | 693.3 |

## Questions

| id | type | ok | question | verdict | primary | expected |
|---|---|---|---|---|---|---|
| g01 | factual | ok | combien de temps pour déclarer son arrivée à la commune | answer | arrivee#l2-l4 | arrivee#arrivee#s1|arrivee#s2 |
| g02 | factual | ok | quelle classe d'impôt pour un célibataire sans enfant | answer | impots_classes#l2-l6 | impots_classes#impots_classes#s1 l2-6 |
| g03 | factual | ok | délai pour l'installation d'internet | answer | telecom#l5-l6 | telecom#telecom#s1|telecom#s2 |
| g04 | factual | ok | comment obtenir luxtrust moins cher | answer | luxtrust#l9-l9 | luxtrust#luxtrust#s1|luxtrust#s2|luxtrust#s4 |
| g05 | factual | ok | qui verse les allocations familiales | answer | allocations#l2-l4 | allocations#allocations#s1 l2-5 |
| g06 | factual | ok | comment contester une facture | answer | reclamation#l2-l3 | reclamation#reclamation#s1|reclamation#s2 |
| g07 | factual | ok | quel est le délai de carence de la complémentaire santé | not_found | assurance_sante#l6-l6 | assurance_sante#assurance_sante#s2 |
| g08 | factual | ok | combien de jours de congé légal par an | answer | conges#l2-l4 | conges#conges#s1 l2-4 |
| g09 | factual | ok | comment immatriculer ma voiture | answer | vehicule#l4-l5 | vehicule#vehicule#s1 l1-5 |
| g10 | factual | ok | quel est le numéro d'urgence | answer | sante_pratique#l2-l3 | sante_pratique#sante_pratique#s1 l2-3 |
| g11 | listing | ok | quels documents pour ouvrir un compte bancaire | answer | banque#l2-l5 | banque#banque#s1 l2-5 |
| g12 | listing | ok | quels documents apporter à la commune | answer | arrivee#l12-l13 | arrivee#arrivee#s4|Ce qu'il faut apporter|arrivee#s1 |
| g13 | listing | ok | quelles pièces pour le dossier de location | answer | recherche_logement#l5-l5 | recherche_logement#recherche_logement#s2|recherche_logement#s1 |
| g14 | listing | ok | quelles garanties couvre l'assurance habitation | answer | assurance_habitation#l2-l3 | assurance_habitation#assurance_habitation#s2|assurance_habitation#s1 |
| g15 | listing | ok | quelles sont les trois classes d'impôt | answer | impots_classes#l2-l6 | impots_classes#impots_classes#s1 |
| g16 | listing | ok | quels documents réclamer avant de signer une assurance habitation | answer | assurance_habitation#l9-l10 | assurance_habitation#assurance_habitation#s4|assurance_habitation#s1 |
| g45 | listing | ok | quelles sont les étapes pour immatriculer un véhicule importé | answer | vehicule#l14-l14 | vehicule#Étapes|vehicule#s1|Votre cas |
| g46 | listing | ok | quels sont les trois délais après l'arrivée | answer | arrivee#l6-l8 | arrivee#Trois délais, pas un seul|arrivee#s1|arrivee#s5 |
| g17 | amount | ok | combien coûte l'immatriculation | answer | vehicule#l2-l5 | vehicule#vehicule#s1|Coûts l1-5 |
| g18 | amount | ok | montant de base des allocations familiales | answer | allocations#l2-l5 | allocations#allocations#s1|allocations#s2 |
| g19 | amount | ok | plafond de l'avantage de la TVA à 3 % | answer | achat#l5-l7 | achat#achat#s2|achat#s1|achat#s3 |
| g20 | amount | ok | combien de mois de loyer pour la garantie locative | answer | bail#l2-l3 | bail#bail#s1|bail#s5 l2-3 |
| g21 | date | ok | depuis quand les transports publics sont-ils gratuits | answer | transport#l2-l5 | transport#transport#s1 l2-3 |
| g22 | date | ok | depuis quelle date la garantie locative est plafonnée à deux mois | answer | bail#l2-l3 | bail#bail#s1|bail#s5 |
| g23 | yes/no | ok | est-ce que la double nationalité est admise | answer | nationalite#l2-l4 | nationalite#nationalite#s1 l2-3 |
| g24 | yes/no | ok | est-ce qu'un permis de conduire européen reste valable | answer | permis#l2-l5 | permis#permis#s1 |
| g25 | yes/no | ok | est-ce que les transports publics sont gratuits | answer | transport#l2-l5 | transport#transport#s1 |
| g26 | yes/no | ok | est-ce que l'assurance responsabilité civile est obligatoire pour une voiture | answer | assurance_auto#l2-l3 | assurance_auto#assurance_auto#s1|assurance_auto#s4|assurance_auto#s5 |
| g27 | address/phone | ok | où déposer la demande d'enregistrement du permis de conduire | answer | permis#l2-l5 | permis#permis#s1 l2-5 |
| g28 | address/phone | ok | quel numéro de téléphone pour les urgences | partial | sante_pratique#l2-l3 | sante_pratique#sante_pratique#s1 |
| g29 | typo | ok | comment imatriculer ma voitur | answer | vehicule#l4-l5 | vehicule#vehicule#s1 |
| g30 | typo | ok | garanti locativ plafonée à combien de mois | answer | bail#l2-l3 | bail#bail#s1|bail#s5 |
| g31 | EN | ok | how do I register my car | answer | vehicule#l4-l5 | vehicule#vehicule#s1 |
| g32 | EN | ok | how many days of annual leave | answer | conges#l2-l4 | conges#conges#s1|conges#s3 |
| g33 | EN | ok | is a local bank account mandatory | answer | banque#l2-l4 | banque#banque#s1|banque#s2 |
| g34 | DE | ok | wie melde ich mich bei der Gemeinde an | answer | arrivee#l2-l4 | arrivee#arrivee#s1|arrivee#s2|arrivee#s4 |
| g35 | DE | ok | ist mein Führerschein in Luxemburg gültig | not_found | permis#l2-l5 | permis#permis#s1|permis#s2 |
| g36 | on-page | ok | combien de temps pour l'immatriculation | answer | vehicule#l2-l5 | vehicule#vehicule#s1 l1-5 |
| g37 | on-page | ok | et pour les plaques ? | answer | vehicule#l129-l129 | vehicule#Réserver un numéro, puis faire les plaques|vehicule#s1 |
| g38 | compound | ok | combien coûte l'immatriculation et quel est le délai | answer | vehicule#l2-l5 | vehicule#vehicule#s1 l1-5 |
| g39 | vague | ok | ça marche comment ? | absent:ambiguous_question | - | clarify |
| g40 | vague | ok | assurance | answer | assurance_auto#l3-l3 | clarify |
| g41 | out-of-scope | ok | où acheter un sapin de noël | absent:concept_not_found | - | absent |
| g42 | out-of-scope | ok | quel est le meilleur restaurant de Luxembourg | absent:concept_found_but_off_topic | - | absent |
| g43 | out-of-scope | ok | comment adopter un chien | absent:concept_not_found | - | absent |
| g44 | out-of-scope | ok | horaires de la piscine municipale | absent:concept_not_found | - | absent |
