---
name: music-lint
description: Use when doing a periodic health check of the library, or after a big organize pass, to surface misplaced files, duplicates, incomplete albums, unimported files, or albums that never matched MusicBrainz. Read-only. Fixing what it finds is a separate step that needs the user's decision.
---

# music-lint

## Run

```sh
uv run musicos lint
```

The command:

1. Runs `musicos preflight`. It stops when `BEETSDIR` is unset, the share is not mounted, or a configured plugin is not enabled.
2. Runs read-only checks: placement drift (`beet move --pretend`), duplicates, incomplete albums (`beet missing`), unimported files, path case mismatches, singletons, and albums with no MusicBrainz match.
3. Overwrites `beetsdir/logs/last-health-report.md` and appends one line to `beetsdir/logs/musicos-activity.log`.

Exit code 1 means preflight failed or a check could not run. Findings alone exit 0.

## After the run

1. Read `beetsdir/logs/last-health-report.md`.
2. Tell the user the count for each check and a few concrete examples.
3. Do not fix anything yourself. Each category needs the user's decision:
   - Placement drift: show the `beet move --pretend` output, then use `music-organize` after the user approves.
   - Duplicates, incomplete albums, unmatched imports: report only. Never delete or edit on your own.

## Notes

- Path case mismatches: the path in the database differs from the file on disk only in letter case, for example `CAKE/` in the database and `Cake/` on disk. The Mac and Samba treat both as one folder, so an artist spelled two ways lands in the first folder created. `beet unimported` lists these files as unimported. Lint moves them to their own category. Report them, and do not rename anything without the user's say-so.

- `beet unimported` reads every file under `directory:`. On the NAS share it takes minutes.
- Placement drift counts items, read from the `Moving N items` line beets prints to stderr.
- The script and its tests live in `musicos/lint.py` and `tests/test_lint.py`.
