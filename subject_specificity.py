#!/usr/bin/env python3
"""
subject_specificity.py -- shared logic for detecting AND automatically
correcting "subject collapse": triples whose Subject is the generic
community node (GaroCommunity/GaroPeople) even when their source sentence
names something more specific.

This is the single source of truth for both:
  - check_subject_specificity.py, the standalone report-only CLI audit tool
  - apply_subject_corrections(), called directly from the pipeline
    (main.py / run_page_pipeline.py) to rewrite subjects automatically,
    no manual/Cypher step involved.

WHY AUTOMATIC CORRECTION, AND WHY IT'S CONSERVATIVE:
Not every "flag" from the audit is safe to apply blindly -- validated
against the real garo_1 page-4 output, two categories of flag are NOT
trustworthy as an entity name:
  1. "attribution-phrase" flags (candidate is "some respondents", "the
     participants", etc.) -- these describe WHO reported the fact, not a
     better subject for the fact itself. Never auto-applied.
  2. Meta/self-referential or abstract candidates ("the passage", "the
     study", "conditions") -- these come from the model's own narration
     about the text, or from grammatically-real-but-semantically-empty
     subjects, and would make a worse KG node than GaroCommunity, not a
     better one. Caught by JUNK_CANDIDATE_LEMMAS below and never applied.
Only a "flag" whose candidate head lemma is NOT in that stoplist gets
auto-applied. Pronoun subjects and unparseable sentences are left alone
entirely (the model's original subject is kept) since there's no reliable
correction to make.

Every correction actually applied is returned as a log entry so the
pipeline can print and persist a record of what changed and why -- this
is full automation, not a silent one; nothing is manually reviewed, but
nothing is invisible either.
"""

import csv
import re
import sys
from typing import Any, Dict, List, Tuple

try:
    import spacy
except ImportError:
    print("spaCy is required: pip install spacy && python -m spacy download en_core_web_sm")
    sys.exit(1)

try:
    from Extraction_Check import ARTIFACT_KEYWORDS
except ImportError:
    ARTIFACT_KEYWORDS = ["respondent", "participant", "researcher"]

_NLP = None

def get_nlp():
    global _NLP
    if _NLP is None:
        try:
            _NLP = spacy.load("en_core_web_sm")
        except OSError:
            print("Model not found: python -m spacy download en_core_web_sm")
            sys.exit(1)
    return _NLP

COMMUNITY_HEAD_LEMMAS = {"community", "people", "garo", "garos", "mandi", "mandis"}
PRONOUN_LEMMAS = {"they", "these", "those", "it", "this", "he", "she", "we", "who", "which"}

# Demonstrative determiners ("this day", "that place") modifying an
# otherwise-ordinary noun head. Found via real data (page 5, re-run,
# extraction #2-4): "This day is a national holiday..." has head noun
# "day" -- not a pronoun, not in any junk list -- but "This" makes it an
# anaphoric reference back to whatever the PREVIOUS sentence named
# (Christmas Day), which this function has no way to resolve. Corrected
# to Subject="ThisDay", a deictic phrase, not a real entity. Rather than
# hand-listing every noun that could follow "this/that/these/those"
# (whack-a-mole, and "these problems" already needed its own JUNK_CANDIDATE_LEMMAS
# entry for the same underlying reason), this generalizes: ANY candidate
# subject headed by a noun with a demonstrative determiner is treated as
# unresolved co-reference and left uncorrected, the same as a pronoun.
DEMONSTRATIVE_LEMMAS = {"this", "that", "these", "those"}

# Self-referential / abstract heads that are grammatically real subjects but
# never sensible KG entities on their own. Found via real data: "The passage
# discusses..." and "As conditions improve..." both parse to a legitimate
# nsubj, but neither is a fact-worthy node.
JUNK_CANDIDATE_LEMMAS = {
    "passage", "study", "article", "paper", "text", "sentence", "section",
    "condition", "situation", "evidence", "data", "information", "fact",
    "thing", "report", "finding", "result", "point",
    # Indefinite-reference nouns ("Others were employed in various
    # services") -- functionally pronouns (referring back to unspecified
    # community members) but spaCy tags "Others" as NOUN, not PRON, so the
    # is_pronoun check alone missed it on real data (page 3, extraction #11).
    "other", "another", "one", "some", "many", "few", "several",
    # Abstract/collective nouns -- grammatically real subjects but not
    # sensible standalone KG entities, same category as "condition" above.
    # Found via real data (page 5, extractions #3-5): "These problems
    # include X, Y, Z" corrected all three to Subject="Problems", which is
    # a category label, not an entity distinct from GaroCommunity.
    "problem",
    # Same "category label restating the predicate" pattern as "problem",
    # a different lemma. Found via real data (garo_1 whole-paper run):
    # "Notable alterations that have occurred among Garos who have
    # converted to Christianity include the loss of traditional customs,
    # the shift in employment opportunities..." corrected 5 triples to
    # Subject="NotableAlterations", which just restates the predicate
    # (NOTABLE_ALTERATIONS) rather than naming a real entity.
    "alteration",
}

# Predicate substrings that describe a cognitive/intentional act -- belief,
# worship, conversion, being influenced, practicing a religion/tradition.
# Found via real data (page 5): "(DepartedSoul)-[BELIEVES_IN]->(...)" and
# "(Spirit)-[BELIEVES_IN]->(...)" -- both single-sentence, both pass every
# other guard, both still wrong, because the sentence's grammatical subject
# ("the spirit", "the departed soul") is the CONTENT of what's believed, not
# the believer. A soul or spirit can't hold a belief; the community can.
# Unlike WEARS (where "Garo men"/"Garo women" as the sentence's subject is a
# genuine improvement -- a person really can wear something), these
# predicates only make sense with an animate, community-level agent as
# Subject, and the sentence's own grammatical subject is not a reliable
# stand-in for that agent. Conservative response: never auto-correct a
# triple whose predicate matches one of these, regardless of how
# plausible-looking the candidate is.
AGENTIVE_PREDICATE_MARKERS = [
    "believ", "worship", "convert", "influenc", "practic", "follow",
    "consider", "faith", "aware", "skeptic",
]

# Leading determiners/quantifiers stripped when normalizing a candidate
# phrase into an entity name, e.g. "The traditional Garo houses" ->
# "TraditionalGaroHouses", not "TheTraditionalGaroHouses".
LEADING_DETERMINERS = {
    "the", "a", "an", "many", "some", "these", "those", "several", "other",
    "most", "certain", "various", "few", "all", "any",
}


def get_evidence_sentence(triple: Dict[str, Any]) -> str:
    """sentence_ref is the intended source; fall back to extracting the
    quoted sentence out of the raw passage field for blocks where the model
    dropped the '// ' prefix on the SENTENCE REF line (a parse_ollama_blocks()
    parsing gap that leaves sentence_ref empty and dumps everything into
    passage instead -- see kg_extractor.py)."""
    sent = (triple.get("sentence_ref") or "").strip()
    if sent:
        return sent.strip('"').strip("<>").strip()
    passage = triple.get("passage") or ""
    m = re.search(r'SENTENCE REF:\s*"(.*?)"', passage, re.DOTALL)
    if m:
        return m.group(1).strip()
    cleaned = re.sub(r'^//?\s*PASSAGE:.*?\n', '', passage, flags=re.DOTALL)
    cleaned = re.sub(r'SOURCE:.*$', '', cleaned, flags=re.DOTALL)
    return cleaned.strip().strip('"').strip("<>").strip()



# Named-entity types that mean "this is a cited external source, not a
# community entity" when they cover the sentence's grammatical subject --
# found via real data: "Major Playfair, a pioneering Garo scholar,
# describes..." and "Ball Ellen states that..." both have a PERSON as
# nsubj, and both got misapplied as the corrected Subject, attributing a
# community fact (an origin story) to the scholar who reported it rather
# than to the community itself. ORG included pre-emptively for the same
# citation pattern ("The Bangladesh Bureau of Statistics reports...").
CITATION_ENTITY_LABELS = {"PERSON", "ORG"}

# Verb lemmas describing a benefactive/dative act -- X is GIVEN/OFFERED/
# PROVIDED something. When the sentence's subject is the PATIENT of one of
# these verbs in the passive voice ("visitors ... may be offered a chair"),
# it's the RECIPIENT of the thing, not a possessor of it -- the opposite of
# what a HAS_-style predicate needs. Found via real data (garo_1
# whole-paper run): "(Visitors)-[HAS_HouseholdFurniture]->(CaneBottomedChair)"
# from "Occasionally, visitors of distinction may be offered a rough
# wooden seat or cane-bottomed chair" -- the household/community has the
# furniture and offers it to visitors; visitors don't possess it. Distinct
# from the earlier page-5 "TheirSoul" case ("their soul is believed to
# transform into a ghost"), which is also passive but the passive subject
# genuinely IS the thing undergoing the predicate's action (the soul
# itself transforms) -- "believe" isn't in this list for that reason.
BENEFACTIVE_VERB_LEMMAS = {"offer", "give", "provide", "present", "grant", "award", "afford"}


def get_sentence_subject(sentence: str):
    """Returns (head_lemma, noun_chunk_text, is_pronoun, is_cited_source,
    is_multi_sentence, is_demonstrative, is_passive_recipient) for the
    sentence's nsubj/nsubjpass, or (None, None, False, False, False, False,
    False) if none is found. is_cited_source is True when the subject is a
    named PERSON/ORG entity
    -- i.e. the sentence is citing who reported something, not describing
    the community itself. is_multi_sentence is True when the "sentence"
    text is actually more than one sentence -- found via real data (garo_1
    page 5, extraction #26/#30): when sentence_ref is a whole paragraph,
    grabbing the first nsubj in the text picks the subject of sentence 1
    even when the triple's Object was actually drawn from sentence 3 or 4,
    producing a confidently wrong pairing (e.g. "(ChristianMissionaries)-
    [STILL_PRACTICE_TRADITIONAL]->(Sangsarek)", reversed from the true
    fact that the COMMUNITY still practices Sangsarek). is_demonstrative is
    True when the candidate noun is modified by "this/that/these/those" --
    see DEMONSTRATIVE_LEMMAS above.

    When a sentence has more than one nsubj, the FIRST nsubj in token order
    is not necessarily the one the triple's fact is actually about. Found
    via real data (page 5 re-run, extraction #1): "When Christmas Day
    arrives regarding the Garo community, they attend church..." -- token
    order alone picks "Christmas Day" (nsubj of "arrives", an ADVERBIAL
    subordinate clause -- dep_ "advcl") ahead of "they" (nsubj of "attend",
    the sentence's ROOT verb), even though the claim being extracted is
    about the main clause. Subjects of an adverbial subordinate clause
    (dep_ "advcl" -- a "when/if/although X, Y" setup clause) are excluded
    in favor of any other candidate, since that pattern is reliably just
    scene-setting, not the fact being asserted.

    A RELATIVE clause (dep_ "relcl" -- "...the Garo community, WHICH
    requires X") is treated differently: NOT excluded, and in fact
    preferred over an earlier main-clause subject when both exist. Found
    via real data (garo_1 whole-paper run): "the services offered are not
    enough to meet the necessity of the Garo community, which requires
    sufficient communication, employment opportunities..." -- the ROOT
    clause's own subject ("services") was being auto-corrected onto 5
    triples that are actually about what the COMMUNITY requires (the
    relcl's subject, "which", correctly co-referring to "the Garo
    community"). Since "which"/"who"/"that" as a relative pronoun is
    already in PRONOUN_LEMMAS, letting it win here means these cases
    resolve to "inconclusive(pronoun)" and are correctly left uncorrected,
    exactly as they should be. Concretely: excluding only advcl-headed
    subjects, then taking the LAST remaining candidate in token order
    (rather than the first) resolves both real cases correctly -- in the
    Christmas Day sentence "they" is both the only non-advcl candidate AND
    the last token-wise; in the services sentence "which" is not excluded
    and appears after "services", so it wins.

    That "prefer the relative-clause subject" step is deliberately scoped
    to relcl specifically, not "prefer the later subject" in general.
    Found via real data (garo_1 whole-paper run): "The primary food of
    Garo people is rice, AND they especially enjoy dried fish..." and
    "the traditional Garo attire consists of dakmanda, daksari, and
    gandu, BUT nowadays, they also wear lungis..." both COORDINATE two
    independent main clauses with "and"/"but" (dep_ "conj", not "relcl")
    -- "food"/"attire" (the first, topic-setting clause) is what the
    triple's predicate/object is actually about, while the second clause
    ("they enjoy...", "they wear...") is a separate aside whose subject
    happens to be a pronoun. Blindly preferring the LAST candidate here
    would pick the pronoun and wrongly discard a correct, already-
    validated correction. So: a relcl-headed candidate (a subject
    genuinely embedded inside a clause describing/modifying another noun)
    is preferred when one exists; otherwise, among the remaining
    (non-advcl) candidates -- which are all coordinate top-level clauses
    -- the FIRST one wins, same as the sentence's own topic order."""
    if not sentence:
        return None, None, False, False, False, False, False
    doc = get_nlp()(sentence)
    is_multi_sentence = len(list(doc.sents)) > 1

    subj_tokens = [t for t in doc if t.dep_ in ("nsubj", "nsubjpass")]
    if not subj_tokens:
        return None, None, False, False, is_multi_sentence, False, False

    non_advcl_subjs = [t for t in subj_tokens if t.head.dep_ != "advcl"]
    candidates = non_advcl_subjs if non_advcl_subjs else subj_tokens
    relcl_candidates = [t for t in candidates if t.head.dep_ == "relcl"]
    token = relcl_candidates[-1] if relcl_candidates else candidates[0]

    is_pronoun = token.pos_ == "PRON" or token.lemma_.lower() in PRONOUN_LEMMAS
    is_cited_source = any(
        ent.label_ in CITATION_ENTITY_LABELS and ent.start <= token.i < ent.end
        for ent in doc.ents
    )
    is_demonstrative = any(
        child.dep_ == "det" and child.lemma_.lower() in DEMONSTRATIVE_LEMMAS
        for child in token.children
    )
    is_passive_recipient = (
        token.dep_ == "nsubjpass" and token.head.lemma_.lower() in BENEFACTIVE_VERB_LEMMAS
    )

    candidate_text = token.text
    for chunk in doc.noun_chunks:
        if chunk.root == token:
            candidate_text = chunk.text
            break

    # Appositive contamination: spaCy's noun_chunks can merge a preceding
    # comma-separated appositive into the same chunk as the real head
    # phrase that follows it, even though chunk.root correctly identifies
    # the true head token. Found via real data (garo_1 whole-paper run):
    # "According to Major Playfair, a pioneering Garo scholar, the Garo or
    # Granching' sub tribe first received..." -- chunk.root is "tribe"
    # (correct; not covered by the PERSON entity, so is_cited_source is
    # correctly False), but chunk.text spans back to "a pioneering Garo
    # scholar, the Garo or..." producing the nonsense entity name
    # "PioneeringGaroScholarThe". Truncating to the text after the LAST
    # comma recovers the real head phrase ("the Garo or Granching' sub
    # tribe"). Guarded so it only applies when the root token's own text
    # still appears in the truncated remainder -- never applied blindly.
    if "," in candidate_text:
        after_last_comma = candidate_text.rsplit(",", 1)[-1].strip()
        if after_last_comma and token.text in after_last_comma:
            candidate_text = after_last_comma

    return (token.lemma_.lower(), candidate_text, is_pronoun, is_cited_source,
            is_multi_sentence, is_demonstrative, is_passive_recipient)


def normalize_to_entity_name(candidate: str, max_words: int = 4) -> str:
    """'The traditional Garo houses' -> 'TraditionalGaroHouses'. Matches the
    CamelCase-noun-phrase convention make_extraction_prompt() already asks
    the model to use for Subject/Object, so corrected subjects stay
    consistent with (and MERGE-compatible against) normally-extracted ones.

    Possessive markers ("'s"/"'s") are stripped before tokenizing. Found
    via real data (garo_1 whole-paper re-run): "Garo community's health
    status" -- naive regex word-extraction splits the possessive apostrophe
    off from "s", leaving a spurious one-letter "s" token that then gets
    capitalized and CamelCased in as its own word, producing the garbled
    "GaroCommunitySHealth" instead of "GaroCommunityHealthStatus"."""
    candidate = re.sub(r"[’']s\b", "", candidate)
    words = re.findall(r"[A-Za-z0-9]+", candidate)
    while words and words[0].lower() in LEADING_DETERMINERS:
        words = words[1:]
    words = words[:max_words]
    return "".join(w[:1].upper() + w[1:] for w in words if w)


def classify_subject(triple: Dict[str, Any]) -> Dict[str, Any]:
    """Runs the audit for a single triple and returns its status plus the
    raw candidate info -- shared by the report-only CLI and the pipeline's
    auto-correction, so the two never drift out of sync with each other."""
    sentence = get_evidence_sentence(triple)
    (head, chunk, is_pronoun, is_cited_source, is_multi_sentence,
     is_demonstrative, is_passive_recipient) = get_sentence_subject(sentence)
    predicate_text = (triple.get("predicate") or "").lower()
    is_agentive_predicate = any(m in predicate_text for m in AGENTIVE_PREDICATE_MARKERS)

    if head is None:
        status = "no-parse"
    elif is_pronoun:
        status = "inconclusive(pronoun)"
    elif head in COMMUNITY_HEAD_LEMMAS:
        status = "ok"
    elif is_demonstrative:
        status = "inconclusive(demonstrative)"
    elif is_passive_recipient:
        status = "inconclusive(passive-recipient)"
    elif is_multi_sentence:
        status = "inconclusive(multi-sentence)"
    elif is_agentive_predicate:
        status = "flag(agentive-predicate)"
    elif is_cited_source:
        status = "flag(cited-source)"
    elif chunk and any(kw in chunk.lower() for kw in ARTIFACT_KEYWORDS):
        status = "flag(attribution-phrase)"
    elif head in JUNK_CANDIDATE_LEMMAS:
        status = "flag(junk-candidate)"
    else:
        status = "flag"

    return {
        "sentence": sentence,
        "head_lemma": head,
        "candidate_subject": chunk,
        "status": status,
    }


def apply_subject_corrections(
    triples: List[Dict[str, Any]],
    community_subjects: Tuple[str, ...] = ("GaroCommunity", "GaroPeople"),
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Mutates triples in place: for any triple whose subject is a generic
    community node AND whose audit status is a plain "flag" (not an
    attribution-phrase or junk-candidate), rewrites the subject to the
    normalized candidate entity name. Returns (triples, corrections_log) --
    corrections_log has one entry per triple actually changed, for printing
    / persisting, since this runs with no manual review step."""
    community_subjects_lower = {s.lower() for s in community_subjects}
    corrections = []

    for triple in triples:
        subj = (triple.get("subject") or "").strip()
        if subj.lower() not in community_subjects_lower:
            continue

        result = classify_subject(triple)
        if result["status"] != "flag":
            continue

        new_subject = normalize_to_entity_name(result["candidate_subject"])
        if not new_subject or new_subject.lower() == subj.lower():
            continue

        # Guard against self-loops: a sentence like "Wangala is considered
        # the most significant festival..." has "Wangala" as its own
        # grammatical subject, but the triple's Object is ALSO "Wangala"
        # (GaroCommunity)-[HAS_FESTIVAL_DESCRIPTION]->(Wangala) -- that's
        # not a real collapse, the community is a perfectly sensible
        # subject for a "the community holds this festival belief" fact.
        # Applying the correction here would create (Wangala)-[...]->
        # (Wangala), which is never correct. Found via real data (#46 in
        # the garo_1 page-4 run) -- skip whenever the candidate matches
        # the object, loosely (case/spacing-insensitive).
        existing_object = re.sub(r"[^a-z0-9]", "", (triple.get("object") or "").lower())
        candidate_norm = re.sub(r"[^a-z0-9]", "", new_subject.lower())
        if candidate_norm and candidate_norm == existing_object:
            continue

        corrections.append({
            "extraction_number": triple.get("extraction_number"),
            "old_subject": subj,
            "new_subject": new_subject,
            "predicate": triple.get("predicate"),
            "object": triple.get("object"),
            "candidate_phrase": result["candidate_subject"],
            "sentence": result["sentence"],
        })
        triple["subject"] = new_subject

    return triples, corrections


def write_corrections_log(corrections: List[Dict[str, Any]], log_path: str) -> None:
    """Persists every automatically-applied correction to a CSV so the
    automation leaves an audit trail even though no one reviews it before
    upload. One row per correction actually made (not one per candidate
    considered) -- if the list is empty, no file is written."""
    if not corrections:
        return
    fieldnames = ["extraction_number", "old_subject", "new_subject", "predicate",
                  "object", "candidate_phrase", "sentence"]
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in corrections:
            writer.writerow({k: c.get(k, "") for k in fieldnames})
