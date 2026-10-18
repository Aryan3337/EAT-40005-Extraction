"""Combine table candidates and source-rechecked narrative evidence locally."""
import argparse
import csv
import json
from pathlib import Path
from community_narratives import extract_narratives


def combine(tables, narratives, documents, output):
    with tables.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    required = {'record_id', 'source_type', 'review_status', 'sentence_ref', 'time_period'}
    if not required.issubset(fields):
        raise ValueError('Use the version 02 table candidate CSV')
    if any(r['source_type'] != 'community_data' or r['review_status'] != 'candidate' for r in rows):
        raise ValueError('Unexpected table record status or source type')
    for field in ['evidence_kind', 'question', 'reported_section']:
        if field not in fields: fields.append(field)
    for row in rows: row['evidence_kind'] = 'table'
    count = 0
    paths = sorted(narratives.glob('community_*_narratives.json'))
    if not paths: raise ValueError('No narrative files found')
    for number, path in enumerate(paths, 1):
        data = json.loads(path.read_text(encoding='utf-8'))
        records = data['records']
        if not records: raise ValueError('Empty narrative file needs review')
        names = {r['source_file'] for r in records}
        if len(names) != 1: raise ValueError('Mixed sources in narrative file')
        name = next(iter(names))
        if Path(name).name != name: raise ValueError('Invalid source filename')
        fresh = extract_narratives(documents / name)
        if data != fresh:
            raise ValueError('Narrative evidence differs from original document')
        for r in records:
            if r['review_flags']: raise ValueError('Flagged narrative needs review')
            title = f'Community record {number:02d}'
            rows.append({
                'subject': f"{title} / {r['question']}",
                'predicate': 'REPORTED_RESPONSE',
                'object': r['response'],
                'sentence_ref': f"{title}. Section: {r['section_heading']}. Question: {r['question']}\nRecorded response (verbatim): {r['response']}",
                'source_section': r['source_section'],
                'confidence': 'Transcription checked; candidate interpretation',
                'paper_title': title, 'source_type': 'community_data',
                'source_file': name, 'page_number': '', 'record_id': r['record_id'],
                'review_status': 'candidate',
                'verification_scope': 'exact paragraph transcription; not independent factual validation',
                # Narrative time meaning needs question-specific handling; do
                # not guess a historical interval from answer wording.
                'time_period': '', 'evidence_kind': 'narrative',
                'question': r['question'], 'reported_section': r['section_heading'],
            })
            count += 1
    ids = [r['record_id'] for r in rows]
    if len(ids) != len(set(ids)): raise ValueError('Duplicate record IDs')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)
    return len(rows)-count, count


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tables', type=Path, required=True)
    p.add_argument('--narratives-dir', type=Path, required=True)
    p.add_argument('--documents-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    t,n = combine(a.tables,a.narratives_dir,a.documents_dir,a.output)
    print(f'Saved {t} table + {n} narrative = {t+n} candidate records locally.')
    print('No model calls or database uploads. Records remain candidates.')


if __name__ == '__main__': main()
