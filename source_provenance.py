"""Normalize recorded provenance without guessing titles or source categories."""
import re


def provenance_fields(record):
    def read(key):
        value = record.get(key)
        return '' if value is None else str(value).strip()

    page = read('page_number')
    if not re.fullmatch(r'[1-9][0-9]*', page):
        # Only an explicit page marker is safe; section numbers are not pages.
        match = re.fullmatch(r'Page\s+([1-9][0-9]*)', read('source_section'), re.I)
        page = match.group(1) if match else ''
    source_type = read('source_type').lower().replace('-', '_').replace(' ', '_')
    if source_type not in {'research_paper', 'community_data'}:
        source_type = ''
    return {
        'paper_title': read('paper_title'),
        'source_file': read('source_file'),
        'page_number': page,
        'source_type': source_type,
    }
