#!/usr/bin/env python3
"""AlphaReader offline entities CSV importer (schema P0, PostgreSQL 16).

Usage from backend root:
  python scripts/import_entities_seed.py /path/to/AlphaReader_entities_seed_2025-2026.csv
  python scripts/import_entities_seed.py /path/to/AlphaReader_entities_seed_2025-2026.csv --apply

Default mode validates input without changing database. It preserves existing
mention_count, first_seen_at, last_seen_at, created_at, embeddings and IDs.
"""
import argparse
import asyncio
import csv
import io
import uuid
from pathlib import Path

from sqlalchemy import text

HEADERS = [
    'id','canonical_name','entity_type','aliases','embedding','embedding_model',
    'mention_count','is_generic','first_seen_at','last_seen_at','created_at',
]
TYPES = {'org', 'person', 'place', 'asset', 'commodity', 'concept'}


def validate(path):
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        rd = csv.DictReader(f)
        if rd.fieldnames != HEADERS:
            raise ValueError(f'Unexpected CSV headers: {rd.fieldnames!r}')
        rows = list(rd)
    names = set()
    for i, row in enumerate(rows, 2):
        uuid.UUID(row['id'])
        name = row['canonical_name'].strip()
        if not name or len(name)>128 or name in names:
            raise ValueError(f'bad/duplicate name at row {i}: {name!r}')
        if row['entity_type'] not in TYPES:
            raise ValueError(f'invalid type row {i}')
        if row['is_generic'].lower() not in {'true','false'}:
            raise ValueError(f'invalid is_generic row {i}')
        if row['embedding'] or row['embedding_model']:
            raise ValueError(f'embedding is intentionally blank; row {i}')
        if row['mention_count'] != '0':
            raise ValueError(f'mention_count must start at 0 in offline seeds; row {i}')
        if not row['aliases'].startswith('{') or not row['aliases'].endswith('}'):
            raise ValueError(f'bad PostgreSQL array literal row {i}')
        names.add(name)
    return rows

SQL = text('''
INSERT INTO entities (
  id, canonical_name, entity_type, aliases,
  embedding, embedding_model, mention_count, is_generic,
  first_seen_at, last_seen_at, created_at
) VALUES (
  CAST(:id AS uuid), :name, :etype, CAST(:aliases AS varchar[]),
  CAST(NULL AS real[]), NULL, 0, :generic,
  CAST(NULL AS timestamptz), CAST(NULL AS timestamptz), now()
)
ON CONFLICT (canonical_name) DO UPDATE SET
  aliases = ARRAY(
    SELECT DISTINCT a
    FROM unnest(
       COALESCE(entities.aliases, ARRAY[]::varchar[]) ||
       COALESCE(EXCLUDED.aliases, ARRAY[]::varchar[])
    ) AS a
    ORDER BY a
  ),
  entity_type = COALESCE(entities.entity_type, EXCLUDED.entity_type)
''')

def parse_pg_array(literal: str) -> list[str]:
    """解析 PostgreSQL varchar[] 字面量，如 {"a","b"} -> ['a','b']."""
    s = (literal or '').strip()
    if not s or s == '{}':
        return []
    if not (s.startswith('{') and s.endswith('}')):
        raise ValueError(f'bad PG array literal: {literal!r}')
    inner = s[1:-1]
    if not inner:
        return []
    return [x for x in next(csv.reader(io.StringIO(inner)))]

async def apply(rows):
    from app.database import async_session
    # Single transaction: any error cancels the batch.
    async with async_session() as db:
        for row in rows:
            await db.execute(SQL, {
                'id': row['id'], 'name': row['canonical_name'],
                'etype': row['entity_type'], 'aliases': parse_pg_array(row['aliases']),
                'generic': row['is_generic'].lower() == 'true',
            })
        await db.commit()
    print(f'Committed {len(rows)} entity UPSERTs.')
    print('Existing IDs, observations, embeddings and is_generic are preserved.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('csv_path', type=Path)
    parser.add_argument('--apply', action='store_true', help='Actually write to PostgreSQL')
    args = parser.parse_args()
    rows = validate(args.csv_path)
    from collections import Counter
    print('Validated', len(rows), 'rows', dict(Counter(r['entity_type'] for r in rows)))
    if not args.apply:
        print('DRY RUN ONLY. Add --apply to write to the configured AlphaReader database.')
        return
    asyncio.run(apply(rows))

if __name__ == '__main__':
    main()
