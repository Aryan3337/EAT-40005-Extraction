"""Keep matching community survey responses together for CSV retrieval."""
import re


def question_key(text):
    text = re.sub(r'^\s*\d+[.)]\s*', '', text or '')
    return ' '.join(re.findall(r'\w+', text.casefold()))


def group_responses(matches, top_k):
    if top_k <= 0: return []
    if not matches: return []
    first = matches[0]
    if first.get('source_type') != 'community_data' or first.get('evidence_kind') != 'narrative':
        return matches[:top_k]
    key = question_key(first.get('question', ''))
    if not key: return matches[:top_k]
    family = [r for r in matches if r.get('source_type') == 'community_data'
              and r.get('evidence_kind') == 'narrative'
              and question_key(r.get('question', '')) == key]
    # Stable record order, independent of response length or repeated keywords.
    # A bounded top_k is still a sample: it must never imply consensus.
    family.sort(key=lambda r: (r.get('source_file', ''), r.get('record_id', '')))
    selected = {id(r) for r in family}
    return (family + [r for r in matches if id(r) not in selected])[:top_k]


def source_response_answer(records):
    """Render same-question survey responses verbatim, without LLM rewriting.

    Returns None for mixed evidence so ordinary synthesis keeps its behavior.
    This reports the selected sources only, not all community members.
    """
    if not records or any(r.get('source_type') != 'community_data'
                          or r.get('evidence_kind') != 'narrative' for r in records):
        return None
    keys = {question_key(r.get('question', '')) for r in records}
    if len(keys) != 1 or not next(iter(keys)):
        return None
    if any(not r.get('object', '').strip() or not r.get('paper_title', '').strip()
           for r in records):
        return None
    question = records[0]['question'].strip()
    lines = ['The retrieved community records contain the following participant responses.',
             f'Question: {question}']
    for record in records:
        lines.append(f"{record['paper_title'].strip()}: {record['object'].strip()}")
    lines.append('These responses apply to the cited records; they do not establish agreement across the whole community.')
    return '\n\n'.join(lines)
