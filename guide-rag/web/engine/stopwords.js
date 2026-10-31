// Port of guide_rag/question/stopwords.py: stop words, pronouns and light stemming for FR / EN / DE.
// Kept in one module so the vote that detects the language and the filter that keeps content words
// read the same lists.

const words = (text) => new Set(text.split(/\s+/).filter(Boolean));

export const FR_STOP_WORDS = words(`
    le la les l un une des du de d au aux et ou ou est sont ce cet cette ces c je j tu il elle
    nous vous ils elles me m te t se s mon ma mes ton ta tes son sa ses notre votre leur leurs qui
    que qu quoi dont quel quelle quels quelles comment pourquoi quand combien ne pas plus pour par
    sur sous dans en avec sans chez vers entre a y on faut faire fait peut peux puis dois doit
    avoir ai as ont ete etre suis es sommes etes si la ici tres tout tous toute toutes aussi comme
    mais donc or ni lequel laquelle lesquels lesquelles meme bien encore deja apres avant
    depuis jusque jusqu lors afin alors ainsi autre autres chaque quelque quelques celui celle ceux
    celles cela ca ceci moi toi lui eux mien tien sien
`);

export const EN_STOP_WORDS = words(`
    the a an and or of to in on at for with by from is are was were be been being am do does did
    can could should would will may might must shall i you he she it we they me him her us them
    my your his its our their mine yours this that these those what which who whom whose how when
    where why not no yes if then than so as about into over under up down out all any some more
    most there here very just also only too need want get got have has had make made take one
`);

export const DE_STOP_WORDS = words(`
    der die das den dem des ein eine einen einem einer eines und oder ist sind war waren sein ich
    du er sie es wir ihr mein meine meinen dein deine seine ihre unser euer wie was wer wo wann
    warum welche welcher welches wieviel nicht kein keine zu in an auf fur mit von bei nach aus
    uber unter vor um durch auch noch schon hier da dort dies diese dieser dieses muss kann darf
    soll will mochte brauche habe hat haben werden wird man als ob dass viel viele alle alles
    geht gehen machen mache tun bekomme bekommen mich sich dich euch uns ihnen ihm
`);

export const STOP_WORDS_BY_LANGUAGE = { fr: FR_STOP_WORDS, en: EN_STOP_WORDS, de: DE_STOP_WORDS };

export const ALL_STOP_WORDS = new Set([...FR_STOP_WORDS, ...EN_STOP_WORDS, ...DE_STOP_WORDS]);

// Pronouns and demonstratives a reader uses in place of the subject ("c'est quoi ça ?").
export const PRONOUNS = words(`
    ca cela ceci celui celle ceux celles lui eux it this that these those one es das dies dieses
    diese der jenes
`);

// Multi-word pronoun phrases, accent-folded; matched on the folded text before tokenising.
export const PRONOUN_PHRASES = [
  "celui-la",
  "celle-la",
  "celui-ci",
  "celle-ci",
  "celui la",
  "celle la",
  "this one",
  "that one",
  "the one",
];

// Words that stand in for the subject but are not stop words anywhere ("et pour les autres ?").
export const EMPTY_CONTENT_WORDS = words(`
    chose choses truc trucs thing things stuff ding dinge page pages seite
`);

/** A folded token that any of the three lists holds. */
export function is_stop_word(token) {
  return ALL_STOP_WORDS.has(token);
}

/**
 * Light stemming for matching only: plural and feminine endings, nothing clever. Tokens of four
 * letters or fewer are left alone: short tokens are abbreviations and codes ("rc", "cns", "bail").
 */
export function stem(token) {
  if (token.length <= 4) return token;
  if (token.endsWith("aux") && token.length > 5) return token.slice(0, -3) + "al";
  if (token.endsWith("x") || (token.endsWith("s") && !token.endsWith("ss"))) token = token.slice(0, -1);
  if (token.endsWith("e") && token.length > 4) token = token.slice(0, -1);
  return token;
}
