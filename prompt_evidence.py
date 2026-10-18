"""Consolidate shared research quotations for synthesis only, not retrieval/UI."""


def build_prompt_evidence(triples):
    evidence, groups = [], {}
    for triple in triples:
        fact = {
            "subject": triple.get("subject", ""),
            "relationship": triple.get("predicate", ""),
            "object": triple.get("object", ""),
        }
        quote = triple.get("sentence_ref", "")
        section = triple.get("source_section", "")
        source_file = triple.get("source_file", "")
        title = triple.get("paper_title", "")
        # Never combine community responses, anonymous evidence, or different
        # documents/locations merely because their wording happens to match.
        if (triple.get("source_type") == "research_paper"
                and str(quote).strip() and (source_file or title)):
            key = (source_file, title, str(triple.get("page_number", "")),
                   section, quote)
            if key not in groups:
                group = {
                    "source_context": quote,
                    "source_section": section,
                    "source_file": source_file,
                    "paper_title": title,
                    "page_number": triple.get("page_number", ""),
                    "facts": [],
                }
                groups[key] = group
                evidence.append(group)
            groups[key]["facts"].append(fact)
        else:
            evidence.append(dict(fact, source_context=quote, source_section=section))
    return evidence
