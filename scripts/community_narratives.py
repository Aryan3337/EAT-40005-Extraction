"""Read explicitly labelled question/answer paragraphs locally, without inference."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from docx import Document

ANSWER = re.compile(r'\bAnswer\s*:', re.I)
SECTION = re.compile(r'^Section\s*[-:]?\s*\d+\b', re.I)


def extract_narratives(path):
    doc = Document(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    records, unclassified = [], []
    section = ''
    metadata_count = 0
    for index, paragraph in enumerate(doc.paragraphs, 1):
        raw = paragraph.text.strip()
        if not raw:
            continue
        if SECTION.match(raw):
            section = raw
            metadata_count += 1
            continue
        match = ANSWER.search(raw)
        if not match:
            # Keep non-answer paragraphs available for review: do not silently
            # classify unmarked narrative responses as headings or discard them.
            unclassified.append({'paragraph_number': index, 'text': raw})
            continue
        question, response = raw[:match.start()].strip(), raw[match.end():].strip()
        flags = []
        if not question: flags.append('missing_question')
        if not response: flags.append('missing_response')
        if not section: flags.append('missing_section')
        if ANSWER.search(response): flags.append('multiple_answer_markers')
        records.append({
            'record_id': f'{digest[:12]}-p{index}',
            'document_sha256': digest,
            'source_file': path.name,
            'source_type': 'community_data',
            'source_section': f'{section} / paragraph {index}',
            'page_number': '',
            'paragraph_number': index,
            'section_heading': section,
            'question': question,
            'response': response,
            'verbatim_paragraph': raw,
            'review_status': 'pending',
            'review_flags': flags,
        })
    return {'status': 'unreviewed_narrative_evidence', 'records': records,
            'unclassified_paragraphs': unclassified,
            'section_heading_count': metadata_count}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-dir', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    a = p.parse_args()
    files = sorted(f for f in a.input_dir.iterdir()
                   if f.suffix.lower() == '.docx' and not f.name.startswith('~$'))
    if not files: p.error('No Word documents found')
    a.output_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for n, path in enumerate(files, 1):
        data = extract_narratives(path)
        target = a.output_dir / f'community_{n:02d}_narratives.json'
        with target.open('x', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        count = len(data['records'])
        total += count
        flagged = sum(bool(r['review_flags']) for r in data['records'])
        print(f'Document {n}: {count} question/answer records; {flagged} flagged; '
              f"{len(data['unclassified_paragraphs'])} other paragraphs retained for classification")
    print(f'Saved {total} narrative evidence records locally. No model calls or database uploads.')


if __name__ == '__main__': main()
