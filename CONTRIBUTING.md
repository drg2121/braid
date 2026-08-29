# Contributing

## Never commit a backup

`.jwlibrary` files contain personal study data — notes, highlights, bookmarks.
They are in `.gitignore`. If you need a sample for a bug report, use
`braid inspect --json`, which reports counts and no content, or build a
synthetic archive with the `BackupBuilder` in `tests/conftest.py`.

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/ruff check src tests
```

## Adding support for a new schema version

1. Add the version to `SUPPORTED_SCHEMA_VERSIONS` in `src/braid/archive.py`.
2. Diff the new schema against `tests/fixtures/schema_v16.sql`.
3. For each new or changed table, decide its identity key and add it to the
   merge order in `Merger._merge_db`. Parents before children.
4. Add a test that merges two libraries differing only in that table, and a test
   that the merge stays idempotent.

## The rule the merge lives by

The merge is additive and idempotent. Merging the same source twice must add
nothing the second time, and no code path may delete a row that came from the
base. `test_merging_is_idempotent` and `test_nothing_is_ever_deleted_from_the_base`
guard both properties — if a change makes them fail, the change is wrong.
