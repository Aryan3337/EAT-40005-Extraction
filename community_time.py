"""Explicit temporal matching for the community table CSV prototype."""
import re


def requested_periods(question):
    q = question.casefold()
    periods = set()
    if re.search(r'\b50\s*[/–-]\s*60\s+years?\s+ago\b', q):
        periods.add('50_60_years_ago')
    if re.search(r'\b10\s*[/–-]\s*20\s+years?\s+ago\b', q):
        periods.add('10_20_years_ago')
    if re.search(r'\b(now|currently|present day)\b', q):
        periods.add('current')
    return periods


def period_from_heading(heading):
    periods = requested_periods(heading)
    return next(iter(periods)) if len(periods) == 1 else ''


def filter_community_periods(records, question):
    periods = requested_periods(question)
    if not periods:
        return list(records)
    # In this mixed corpus prototype, untimed research-paper records retain
    # existing behavior. Community evidence must explicitly match the period.
    return [r for r in records if r.get('source_type') != 'community_data'
            or r.get('time_period') in periods]
