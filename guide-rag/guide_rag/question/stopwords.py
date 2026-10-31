"""Stop words, pronouns and light stemming for FR / EN / DE.

Kept in one module so the vote that detects the language and the filter that keeps content words
read the same lists. The lists are short on purpose: a stop word removed by mistake is a lost
keyword, so only function words that never carry the subject of a question are listed.
"""

from __future__ import annotations

FR_STOP_WORDS: frozenset[str] = frozenset(
    """
    le la les l un une des du de d au aux et ou ou est sont ce cet cette ces c je j tu il elle
    nous vous ils elles me m te t se s mon ma mes ton ta tes son sa ses notre votre leur leurs qui
    que qu quoi dont quel quelle quels quelles comment pourquoi quand combien ne pas plus pour par
    sur sous dans en avec sans chez vers entre a y on faut faire fait peut peux puis dois doit
    avoir ai as ont ete etre suis es sommes etes si la ici tres tout tous toute toutes aussi comme
    mais donc or ni lequel laquelle lesquels lesquelles meme bien encore deja apres avant
    depuis jusque jusqu lors afin alors ainsi autre autres chaque quelque quelques celui celle ceux
    celles cela ca ceci moi toi lui eux mien tien sien
    """.split()
)

EN_STOP_WORDS: frozenset[str] = frozenset(
    """
    the a an and or of to in on at for with by from is are was were be been being am do does did
    can could should would will may might must shall i you he she it we they me him her us them
    my your his its our their mine yours this that these those what which who whom whose how when
    where why not no yes if then than so as about into over under up down out all any some more
    most there here very just also only too need want get got have has had make made take one
    """.split()
)

DE_STOP_WORDS: frozenset[str] = frozenset(
    """
    der die das den dem des ein eine einen einem einer eines und oder ist sind war waren sein ich
    du er sie es wir ihr mein meine meinen dein deine seine ihre unser euer wie was wer wo wann
    warum welche welcher welches wieviel nicht kein keine zu in an auf fur mit von bei nach aus
    uber unter vor um durch auch noch schon hier da dort dies diese dieser dieses muss kann darf
    soll will mochte brauche habe hat haben werden wird man als ob dass viel viele alle alles
    geht gehen machen mache tun bekomme bekommen mich sich dich euch uns ihnen ihm
    """.split()
)

STOP_WORDS_BY_LANGUAGE: dict[str, frozenset[str]] = {
    "fr": FR_STOP_WORDS,
    "en": EN_STOP_WORDS,
    "de": DE_STOP_WORDS,
}

ALL_STOP_WORDS: frozenset[str] = FR_STOP_WORDS | EN_STOP_WORDS | DE_STOP_WORDS

# Pronouns and demonstratives a reader uses in place of the subject ("c'est quoi ça ?").
# They are also stop words; the clarification rule looks for them before the content-word rule.
PRONOUNS: frozenset[str] = frozenset(
    """
    ca cela ceci celui celle ceux celles lui eux it this that these those one es das dies dieses
    diese der jenes
    """.split()
)

# Multi-word pronoun phrases, accent-folded; matched on the folded text before tokenising.
PRONOUN_PHRASES: tuple[str, ...] = (
    "celui-la",
    "celle-la",
    "celui-ci",
    "celle-ci",
    "celui la",
    "celle la",
    "this one",
    "that one",
    "the one",
)

# Words that stand in for the subject but are not stop words anywhere ("et pour les autres ?").
# They carry no topic, so the keyword rule ignores them too.
EMPTY_CONTENT_WORDS: frozenset[str] = frozenset(
    """
    chose choses truc trucs thing things stuff ding dinge page pages seite
    """.split()
)


def is_stop_word(token: str) -> bool:
    """A folded token that any of the three lists holds."""
    return token in ALL_STOP_WORDS


def stem(token: str) -> str:
    """Light stemming for matching only: plural and feminine endings, nothing clever.

    One rule for every language, applied to the question and to the dictionary variants alike,
    so a match never depends on the detected language. What matters is that it is stable, not
    that it is linguistically right. Tokens of four letters or fewer are left alone: short tokens
    are abbreviations and codes ("rc", "cns", "bail", "taxe").
    """
    if len(token) <= 4:
        return token
    # "animaux" -> "animal"; "travaux" -> "traval" (stable, both sides agree).
    if token.endswith("aux") and len(token) > 5:
        return token[:-3] + "al"
    if token.endswith("x") or (token.endswith("s") and not token.endswith("ss")):
        token = token[:-1]
    # "locatives" -> "locativ" and "locative" -> "locativ": the feminine e goes too.
    if token.endswith("e") and len(token) > 4:
        token = token[:-1]
    return token
