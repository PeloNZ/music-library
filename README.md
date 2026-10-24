# music-library

Repair a music library with [beets](https://beets.io/), driven from Claude Code, played by Plex.

- Identify unknown tracks by acoustic fingerprint (AcoustID, through the beets `chroma` plugin).
- Fill missing tags and album art.
- Split album FLAC rips (one FLAC plus a `.cue` file) into tracks.
- Organise files on disk as `Album Artist/Year - Album/NN Title`.
- Tell Plex to rescan after a change.

The library lives on the NAS, which this Mac reaches through the `media` share, mounted at `/Volumes/media`. The library folder is `/Volumes/media/jbod2/media/music`, and the inbox and holding folders are next to it. Use that one share only, never the separate `music` share: every move is then a rename and nothing is copied between shares. beets runs on this Mac. Plex runs on the NAS.

Built on [MusicOS](https://github.com/fernandohermida/MusicOS) by Fernando Hermida (MIT). The skills, docs and `scripts/library_snapshot.py` come from it. See `LICENSE`.

## Design

- beets owns the tags in the files. Plex reads them. This repo never writes tags through Plex.
- Steps with one correct answer are scripts in `musicos/`, with tests in `tests/`. Run them with `uv run musicos <command>`.
- Steps that need judgement stay in the skills in `.claude/skills/`: pick a match, approve a move, write a query, review a duplicate.
- Every command that changes files runs `--pretend` first and writes a log.

## Repository layout

| Path | Contents |
|---|---|
| `.claude/skills/` | Claude Code skills (from MusicOS) |
| `musicos/` | Scripts, run as `uv run musicos <command>` |
| `tests/` | pytest tests for `musicos/` |
| `beetsdir/` | `BEETSDIR`. `config.example.yaml` is tracked. `config.yaml`, `library.db`, `logs/` are gitignored. |
| `beetsdir-test/` | `BEETSDIR` for the test copy (gitignored) |
| `music-test/` | Test copy of about 20 albums (gitignored) |
| `docs/` | beets cheatsheet, layout, setup notes (from MusicOS) |
| `scripts/library_snapshot.py` | `beet export` wrapper (from MusicOS) |
| `.venv/` | Python dependencies (gitignored, made by `uv sync`) |
| `Brewfile` | System tools: `fpcalc`, `flac`, `shnsplit`, `cuetag.sh` |

## Set up

Needs macOS, [Homebrew](https://brew.sh) and [uv](https://docs.astral.sh/uv/). Fingerprint matching needs no AcoustID key: beets uses its own.

```sh
brew bundle                  # system tools
uv sync                      # beets and plugin dependencies into .venv
export BEETSDIR="$PWD/beetsdir"   # add to ~/.zshrc, with the full path
cp beetsdir/config.example.yaml beetsdir/config.yaml   # then edit it
```

Always set `BEETSDIR`. Without it, beets writes its config and database to `~/.config/beets`.

Edit `beetsdir/config.yaml`:

- `directory: /Volumes/media/jbod2/media/music`

Mount the share: Finder → Go → Connect to Server → `smb://192.168.0.63/media`. The terminal app needs access to network volumes: System Settings → Privacy & Security → Files and Folders (or Full Disk Access). Check with `ls /Volumes/media`.

The `plex` commands read `PLEX_URL` and `PLEX_TOKEN`. Plex here has two music-type libraries (`Music` and `Audiobook`), so also set `PLEX_SECTION=Music` or pass `--section`. `folders` and the post-import rescan need a path map from each Mac mount to its server path: `PLEX_PATH_MAP=/Volumes/media=/data`. Put them in an env file at the repo root, one `KEY=value` per line (`#` comments and an `export ` prefix are allowed). The file is gitignored. `musicos` loads it on every run, and a variable already set in the shell wins. A bad line stops the run and names only its line number. Never commit the token.

Check the tools:

```sh
uv run beet version
fpcalc -version && shnsplit -v && which cuetag.sh cuebreakpoints && flac --version
```

## Develop

```sh
uv run pytest
uv run ruff format . && uv run ruff check .
uv run mypy musicos
```

Write the test first. Mock only the network, the clock, the file system and subprocess calls to `beet`.

## Logs

All in `beetsdir/logs/` (gitignored).

| File | Contents |
|---|---|
| `changes.jsonl` | One JSON line per action that changed files or tags: `time`, `action`, then fields. Read it with `uv run musicos log`. |
| `musicos-activity.log` | One text line per run of `lint`, `ingest` or `summary`: that it ran, with counts. |
| `import-<batch>.log` | Written by `beet import -l`: albums beets skipped or imported as-is. `import-<batch>-retry.log` holds the decisions on the skipped albums. |

`uv run musicos log` options: `--batch ID`, `--action NAME`, `--since YYYY-MM-DD`, `--last N`, `--json` (raw entries). It needs `BEETSDIR` but not the mounted share.

`changes.jsonl` holds one entry for each change a command makes: `split`, `ingest`, `folders --apply`, `clean-appledouble --apply` and `plex refresh`. An import entry holds the batch, the source folder (only for `ingest --unattended`), the album and flagged counts, and the path of every imported item. A split entry holds the source and the track count. Each command added later that changes files must append its own entries.

## Duplicate albums

`uv run musicos dupes <artist-folder>` groups folders that look like the same album, applies this ruleset, and appends deletion candidates to `beetsdir/logs/deletion-candidates.jsonl`. `uv run musicos candidates` lists what is still waiting. The user deletes candidates by hand. Nothing is deleted by `musicos`.

Priority, highest first:

1. FLAC tracks already split.
2. A single FLAC with a cue file.
3. Lossy tracks.

| Case | Result |
|---|---|
| A strictly higher priority copy exists | the lower copy is a **deletion candidate** |
| Two copies share the top priority | **tie**: neither is marked, the user chooses |
| A lower priority copy has more tracks than the best copy | **review**: not marked, deleting it could lose tracks |
| The group holds a format outside the ranking (WAV, ALAC, APE), or a FLAC with several cue sheets | **review**: nothing is marked |

Each log entry has a status read from the disk: `open`, `stale` (every copy that outranked it is gone, so it is no longer safe to delete) `done` (the folder is gone, hidden unless `candidates --all`) or `unknown` (the share is not mounted, so nothing can be told). `dupes` refuses a folder on a share that is not mounted.

## Order of a batch

One artist folder is one batch. Deleting is the last step.

1. `dupes`: find the groups and record the candidates.
2. The user picks a copy for each tie or review. Recording an open candidate in the log is the pick.
3. `split` each kept cue rip. A cue rip that is a candidate is not split.
4. `batch <artist-folder> --apply`: one unattended import of every kept album, then the Plex rescan and `summary`. Then `lint`.
5. The user decides the albums beets skipped, with the command that `summary` prints.
6. The user checks the result in Plex.
7. The user deletes the candidates by hand. Nothing is deleted before step 6.

`uv run musicos batch <artist-folder>` is a dry run. It decides from the disk and the candidates log, and adds new deletion candidates to the log as `dupes` does:

| Folder | Result |
|---|---|
| Not in a group | imported |
| Open deletion candidate | left out, never touched |
| Stale candidate, or a FLAC with several cue sheets | left out: review |
| One copy left in a group | that copy is imported |
| Several copies left in a group | none imported: choose one, then run again |
| A kept FLAC + cue rip | left out: split it first |
| Beets already holds the folder | left out |

It prints the folders, the size that copy mode adds, and the `beet import --pretend` list. `--apply` runs one `beet import -i -R -q --quiet-fallback skip`. Strong matches apply. A weak match is skipped and logged, never guessed. `-i` skips a folder beets imported before, and `-R` retries a skipped one, so running `batch` again after you fix a decision imports only what is left. The preview skips imported folders too, but the list of folders and the size still count them. beets keeps a history of imported folders in `beetsdir/state.pickle`: to import a folder again after you remove it from beets, run `beet import -I` on it. `ingest` does not use `-i`.

Known limit: a multi-disc album in `CD1/` and `CD2/` folders is passed to beets as two folders. Import it with `ingest` on its parent folder.

## Rules

- Do not change the real library until the test copy passes.
- Run `--pretend` before every `beet import` and `beet move`.
- Pass `-W` to `beet modify` when you change only the database.
- Keep `import.copy: yes` until move mode is approved. Copy mode needs free space on the share equal to the size of each batch.
- Write every import run to a log file.
- Every command that changes files or tags appends to `changes.jsonl`.
- Never copy between shares. `split` refuses unless the source, the inbox and the holding folder are on one share, and it moves by rename.
- Keep source FLAC and `.cue` files until the split tracks are confirmed correct.
- Deleting deletion candidates is the last step of a batch, after the import is checked.

## Status

Done: tools installed, dependencies in `.venv`, MusicOS skills and docs copied in.

Open:

- The library at `/Volumes/media/jbod2/media/music` is already in `Artist/Album` folders (191 top-level entries). It has name variants to merge (`motorhead` and `Motörhead`, `Goo Goo Dolls` and `The Goo Goo Dolls`, `Goji.Ra` and `GojiRa`), release-named folders (`Red Hot Chili Peppers - What Hits! (1992) {FLAC} ...`), `desktop.ini`, and `sync.ffs_db` (a FreeFileSync database). Check what else syncs this share before any `beet move`.
- `musicos/` has twelve commands: `preflight` (`BEETSDIR`, the share mount, enabled plugins), `lint` (preflight, read-only health checks, a report and a log line), `ingest <folder> [--unattended] [--no-plex-refresh]` (preflight, source check, dry run, then the import command; unattended runs it), `gaps` (preflight, then a report of albums with no album artist, year, genre or art, with name and path; guesses nothing), `summary <batch>` (albums in an import batch, those with no MusicBrainz match, and those the importer skipped), `split <folder> --inbox DIR --holding DIR [--apply]` (finds FLAC + cue rips; dry run unless `--apply`), `plex sections` (lists Plex libraries and their folders) and `plex refresh [--section ID|TITLE]` (rescans a music library; needs `BEETSDIR` to log it), `folders --inbox DIR --holding DIR [--path-map MAC=SERVER] [--apply]` (makes inbox and holding folders that Plex ignores; dry run unless `--apply`) `dupes ROOT` (read-only on the music: groups folders that look like the same album, applies the duplicate ruleset below, writes `beetsdir/logs/last-duplicates-report.md` and appends deletion candidates to `deletion-candidates.jsonl`; run it on an artist folder before importing it), `candidates [--all]` (lists the deletion candidates still waiting for you), `clean-appledouble ROOT [--apply]` (finds the macOS `._` shadow files this Mac leaves on the share and deletes them with `--apply`; only files with the AppleDouble header, dry run by default) and `log` (shows the change log). All but `log`, `plex` and `folders` run preflight first; all exit 1 on failure. `split`, `ingest`, `folders --apply`, `clean-appledouble --apply` and `plex refresh` record in the change log. After an import, `ingest --unattended` and `summary` rescan the Plex music library that holds beets' `directory`, and log it. If Plex is not set up, or the folder is not in a Plex library (the local test library), they print why and skip. A failed rescan prints `WARN` and never undoes the import. Next: move and tag-write commands that log their changes.
- `docs/` and the skills still describe the MusicOS letter layout, the `limit` plugin (deprecated in beets 2.14, not enabled here), and manual steps. Each is rewritten as its script lands.
