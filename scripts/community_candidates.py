"""Create contextual candidate records from source-checked community tables.

No model calls or database writes. Requires original Word files to recheck the
source before accepting the transcription decisions. Output is not approved KG.
"""
import argparse
import csv
import json
from pathlib import Path
from community_tables import extract_document
from community_time import period_from_heading

FIELDS = ['subject', 'predicate', 'object', 'sentence_ref', 'source_section',
          'confidence', 'paper_title', 'source_type', 'source_file', 'page_number',
          'record_id', 'review_status', 'verification_scope', 'time_period']


def candidate(record, number):
    headers = ' | '.join(record['column_headers'])
    title = f'Community record {number:02d}'
    # Preserve the entire recorded response; splitting commas would risk
    # changing local names, qualifications and list structure.
    context = f"{record['context_kind']}: {record['row_context']}"
    evidence = (f'{title}. Table row context: {context}. '
                f'Question / time-period heading: {headers}. '
                f"Recorded response (verbatim): {record['response']}")
    return {
        'subject': f"{title} / {context}",
        'predicate': 'REPORTED_RESPONSE',
        'object': record['response'],
        'sentence_ref': evidence,
        'source_section': record['source_section'],
        'confidence': 'Transcription checked; candidate interpretation',
        'paper_title': title,
        'source_type': 'community_data',
        'source_file': record['source_file'],
        'page_number': '',
        'record_id': record['record_id'],
        'time_period': period_from_heading(headers) if record['context_kind'] == 'resource_category' else '',
        'review_status': 'candidate',
        'verification_scope': 'exact table transcription; not independent factual validation',
    }


def convert(input_dir, documents_dir, decisions_path, output):
    decisions = json.loads(decisions_path.read_text(encoding='utf-8'))['decisions']
    accepted = {}
    for decision in decisions:
        key = decision['record_id']
        if key in accepted:
            raise ValueError('Duplicate decision ID')
        accepted[key] = decision['transcription_status']
    paths = sorted(input_dir.glob('community_*_evidence.json'))
    if not paths:
        raise ValueError('No evidence files found')
    candidates, seen = [], set()
    for number, path in enumerate(paths, 1):
        payload = json.loads(path.read_text(encoding='utf-8'))
        if payload.get('warnings'):
            raise ValueError(f'Document {number}: layout warnings require review')
        records = payload['records']
        if not records:
            continue
        filenames = {r['source_file'] for r in records}
        if len(filenames) != 1:
            raise ValueError('Evidence file mixes source documents')
        filename = next(iter(filenames))
        if Path(filename).name != filename:
            raise ValueError('Source must be a filename')
        fresh, warnings = extract_document(documents_dir / filename)
        if warnings:
            raise ValueError('Original document needs layout review')
        source_map = {r['record_id']: r for r in fresh}
        if {r['record_id'] for r in records} != set(source_map):
            raise ValueError('Evidence coverage differs from original document')
        for record in records:
            key = record['record_id']
            if key in seen:
                raise ValueError('Duplicate evidence ID')
            seen.add(key)
            original = source_map[key]
            for field in ['document_sha256', 'source_file', 'source_section',
                          'row_context', 'column_headers', 'response',
                          'context_kind', 'review_flags']:
                if record.get(field) != original.get(field):
                    raise ValueError('Evidence changed since source verification')
            if record['review_flags'] or accepted.get(key) != 'passed':
                raise ValueError('Evidence lacks a passed transcription check')
            candidates.append(candidate(record, number))
    if not candidates:
        raise ValueError('No candidates generated')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(candidates)
    return len(candidates)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-dir', type=Path, required=True)
    p.add_argument('--documents-dir', type=Path, required=True)
    p.add_argument('--decisions', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    count = convert(a.input_dir, a.documents_dir, a.decisions, a.output)
    print(f'Saved {count} contextual candidate records locally. No database upload.')
    print('Table evidence only; narrative paragraphs are not included.')


if __name__ == '__main__':
    main()
