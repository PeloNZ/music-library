---
name: music-ingest
description: Use when the user wants to bring new music files into the library: a folder on the NAS inbox, a downloaded album, or a batch of ripped or purchased tracks. Not for reorganising or fixing tags on music already in the library.
---

# music-ingest

## Run

```sh
uv run musicos ingest <source-folder>
```

The command:

1. Runs `musicos preflight` (`BEETSDIR`, share mount, plugins).
2. Checks that the source folder holds audio files.
3. Makes a batch id: `<YYYYMMDD-HHMM>-<slug of the folder name>`.
4. Runs `beet import --pretend` and prints the file list. It shows files, not matches.
5. Prints the exact `beet import` command. Every import is logged to `beetsdir/logs/import-<batch>.log` and tagged `musicos_batch=<batch>`.

## One artist folder: use `batch`

For an artist folder with several albums, run `uv run musicos batch <artist-folder>` first. It picks the kept albums and imports them in one run. See "Order of a batch" in the README. `ingest` stays for a single folder, such as a new download.

- Without `--apply` it only previews. With `--apply` it imports unattended, rescans Plex and runs `summary`.
- `summary` prints one `beet import` command for the albums beets skipped. The user runs it in their own terminal and answers the prompts.

## Choose a mode with the user

- **Assisted (default).** The user runs the printed command in their own terminal. beets' match prompts need a terminal and do not work through Claude's shell. Then run `uv run musicos summary <batch>`.
- **Unattended.** `uv run musicos ingest <source-folder> --unattended` runs the import with `-q --quiet-fallback skip`. Strong matches apply. Anything unsure is skipped and written to the log. Use it for bulk, low-stakes imports. The summary runs at the end.

Never run `beet import -q` with `quiet_fallback: asis`. It writes unverified tags.

## After the import

`summary` lists the albums in the batch and the ones with no MusicBrainz match. It adds one line to `beetsdir/logs/musicos-activity.log` and one `import` entry to `beetsdir/logs/changes.jsonl`, with the path of every imported item. Show the entry with `uv run musicos log --batch <batch>`.

1. Report the counts and name each album with no match.
2. Ask the user what to do with each one. Do not guess tags.
3. Suggest `music-organize` for placement next.

## Plex

After an import, `summary` and `ingest --unattended` rescan the Plex music library that holds `directory:`, once per batch, and log a `plex-refresh` entry. They skip with a reason when Plex is not set up or the folder is not in a Plex library. A failed rescan prints `WARN` and does not undo the import. Add `--no-plex-refresh` to skip it.

## Notes

- The source folder is not changed. `import.copy: yes` keeps the original files until the user approves move mode.
- A cue-sheet rip (one FLAC plus a `.cue`) imports as a single track. Split it first.
- Deleting deletion candidates is the last step of a batch, after the import, the Plex rescan and the user's check. See `music-dupes`.
