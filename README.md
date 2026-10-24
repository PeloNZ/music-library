# music-library

Repair a music library with [beets](https://beets.io/), driven from Claude Code, played by Plex.

- Identify unknown tracks by acoustic fingerprint (AcoustID, through the beets `chroma` plugin).
- Fill missing tags and album art.
- Split album FLAC rips (one FLAC plus a `.cue` file) into tracks.
- Organise files on disk as `Album Artist/Year - Album/NN Title`.
- Tell Plex to rescan after a change.

The library lives on a NAS share, mounted on this Mac at `/Volumes/music`. beets runs on this Mac. Plex runs on the NAS.

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
| `Brewfile` | System tools: `fpcalc`, `flac`, `shnsplit`, `cuetag` |

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

- `directory: /Volumes/music`

Mount the share: Finder → Go → Connect to Server → `smb://192.168.0.63/music`. The terminal app needs access to network volumes: System Settings → Privacy & Security → Files and Folders (or Full Disk Access). Check with `ls /Volumes/music`.

Plex scripts read `PLEX_URL` and `PLEX_TOKEN` from the environment. Never put the token in the repo.

Check the tools:

```sh
uv run beet version
fpcalc -version && shnsplit -v && cuetag && flac --version
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
| `import-<batch>.log` | Written by `beet import -l`: albums beets skipped or imported as-is. |

`uv run musicos log` options: `--batch ID`, `--action NAME`, `--since YYYY-MM-DD`, `--last N`, `--json` (raw entries). It needs `BEETSDIR` but not the mounted share.

Today `changes.jsonl` records imports: batch, source folder (only for `ingest --unattended`), album and flagged counts, and the path of every imported item. Each command added later that changes files must append its own entries: old and new paths for a move, old and new values for a tag write, source and tracks for a split.

## Rules

- Do not change the real library until the test copy passes.
- Run `--pretend` before every `beet import` and `beet move`.
- Pass `-W` to `beet modify` when you change only the database.
- Keep `import.copy: yes` until move mode is approved. Copy mode needs free space on the share equal to the size of each batch.
- Write every import run to a log file.
- Every command that changes files or tags appends to `changes.jsonl`.
- Keep source FLAC and `.cue` files until the split tracks are confirmed correct.

## Status

Done: tools installed, dependencies in `.venv`, MusicOS skills and docs copied in.

Open:

- The library at `/Volumes/music` is already in `Artist/Album` folders (191 top-level entries). It has name variants to merge (`motorhead` and `Motörhead`, `Goo Goo Dolls` and `The Goo Goo Dolls`, `Goji.Ra` and `GojiRa`), release-named folders (`Red Hot Chili Peppers - What Hits! (1992) {FLAC} ...`), `desktop.ini`, and `sync.ffs_db` (a FreeFileSync database). Check what else syncs this share before any `beet move`.
- `musicos/` has five commands: `preflight` (`BEETSDIR`, the share mount, enabled plugins), `lint` (preflight, six read-only health checks, a report and a log line), `ingest <folder> [--unattended]` (preflight, source check, dry run, then the import command; unattended runs it), `summary <batch>` (albums in an import batch, and those with no MusicBrainz match) and `log` (shows the change log). All but `log` run preflight first; all exit 1 on failure. Next: `gaps`, `split`, `plex-refresh`, and move and tag-write commands that log their changes.
- `docs/` and the skills still describe the MusicOS letter layout, the `limit` plugin (deprecated in beets 2.14, not enabled here), and manual steps. Each is rewritten as its script lands.
