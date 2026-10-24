---
name: music-dupes
description: Use before importing or splitting an artist folder, or when the same album may exist more than once in a folder. Finds duplicate albums, applies the keep-and-delete-candidate ruleset, and lists deletion candidates for the user to remove by hand. Never deletes.
---

# music-dupes

## Run

```sh
uv run musicos dupes <artist-folder>
uv run musicos candidates
```

`dupes` is read-only on the music. It groups folders that look like the same album (same artist, album and disc; case, accents, punctuation and bracketed notes such as `(Reissue 2016)` are ignored), prints a report, and writes `beetsdir/logs/last-duplicates-report.md`. It also appends deletion candidates to `beetsdir/logs/deletion-candidates.jsonl`, once per folder.

`candidates` lists what is still waiting: reason, the copy that was kept, size, and a total.

## The ruleset

Priority, highest first:

1. FLAC tracks already split.
2. A single FLAC with a cue file.
3. Lossy tracks.

- A copy is a **deletion candidate** only when a strictly higher priority copy exists in the same group.
- Two copies at the top priority are a **tie**. Neither is marked. The user chooses.
- A lower priority copy with **more tracks** than the best copy is **review**, not a candidate. Deleting it could lose tracks.
- A group with a format outside the ranking (WAV, ALAC, APE and so on), or one FLAC with several cue sheets, is **review**. Nothing is marked.

## What you do

1. Run `dupes` on one artist folder, then `candidates`.
2. Report the groups, the candidates with their size, the ties and the reviews.
3. For a tie or a review, ask the user which copy to keep. Do not guess.
4. Do not delete, move or rename a candidate. Deleting is the last step of the batch: after `split`, `ingest`, the Plex rescan and the user's check of the result. Do not ask the user to delete before then. The user removes candidates by hand. A candidate whose folder is gone shows as done and is hidden. A candidate marked `stale` lost every copy that outranked it. Tell the user not to delete it. A candidate marked `unknown` is on a share that is not mounted. Ask the user to mount it and run `candidates` again.
5. Run `dupes` before `split`: do not split a cue rip that is a candidate. The batch order is `dupes`, choices, `split`, `ingest`, the user's check, then deletion.

## Notes

- Run `dupes` on an artist folder, not the whole share. It reads every audio file's tags over SMB.
