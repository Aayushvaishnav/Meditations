"""Privacy-limited iCalendar snapshots of individual work blocks."""

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from app.models import Task, TimeBlock
from app.util import normalize_dt


def escape_text(value: str) -> str:
    if any(ord(char) < 32 and char not in '\t\r\n' or ord(char) == 127 for char in value):
        raise ValueError('Calendar TEXT contains forbidden control characters')
    return (value.replace('\\', '\\\\').replace('\r\n', '\n').replace('\r', '\n')
            .replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,'))


def fold_line(line: str) -> str:
    """Count UTF-8 octets, including the continuation space."""
    parts = []
    current = ''
    size = 0
    for char in line:
        width = len(char.encode('utf-8'))
        if size + width > 75:
            parts.append(current)
            current, size = ' ', 1
        current += char
        size += width
    parts.append(current)
    return '\r\n'.join(parts)


def timestamp(value: datetime) -> str:
    value = normalize_dt(value).replace(microsecond=0)
    return f'{value.year:04d}{value.month:02d}{value.day:02d}T{value.hour:02d}{value.minute:02d}{value.second:02d}Z'


def serialize_calendar(events: list[tuple[TimeBlock, Task]], *, exported_at: datetime) -> str:
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Journal//Meditations Calendar//EN', 'CALSCALE:GREGORIAN']
    for block, task in sorted(events, key=lambda event: event[0].id):
        identity = uuid5(NAMESPACE_URL, f'journal:time-block:{block.id}')
        modified_at = max(normalize_dt(block.updated_at), normalize_dt(task.updated_at))
        lines.extend(['BEGIN:VEVENT', f'UID:meditations-time-block-{identity}@journal.local',
                      f'DTSTAMP:{timestamp(exported_at)}', f'CREATED:{timestamp(block.created_at)}',
                      f'LAST-MODIFIED:{timestamp(modified_at)}'])
        if block.kind == 'all_day':
            lines.extend([f"DTSTART;VALUE=DATE:{block.start_date.isoformat().replace('-', '')}",
                          f"DTEND;VALUE=DATE:{block.end_date.isoformat().replace('-', '')}"])
        else:
            start, end = timestamp(block.start_at), timestamp(block.end_at)
            if end <= start:
                raise ValueError(f'Time block {block.id!r} has no positive interval at second precision')
            lines.extend([f'DTSTART:{start}', f'DTEND:{end}'])
            if block.timezone is not None:
                lines.append(f'X-JOURNAL-TIMEZONE:{escape_text(block.timezone)}')
        lines.extend([f'SUMMARY:{escape_text(task.title)}',
                      'STATUS:CANCELLED' if task.status == 'canceled' else 'STATUS:CONFIRMED',
                      'END:VEVENT'])
    lines.append('END:VCALENDAR')
    return '\r\n'.join(fold_line(line) for line in lines) + '\r\n'
