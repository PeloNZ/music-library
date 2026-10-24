from datetime import datetime
from pathlib import Path

from musicos.ingest import make_batch_id

WHEN = datetime(2026, 10, 24, 21, 40)


def test_batch_id_is_timestamp_and_folder_slug() -> None:
    assert (
        make_batch_id(WHEN, Path("/inbox/Gatecreeper-2019-Deserted"))
        == "20261024-2140-gatecreeper-2019-deserted"
    )


def test_batch_id_slug_drops_accents_and_punctuation() -> None:
    assert make_batch_id(WHEN, Path("/inbox/Motörhead (Live!)")) == (
        "20261024-2140-motorhead-live"
    )


def test_batch_id_slug_is_cut_at_40_characters() -> None:
    folder = Path("/inbox/Red Hot Chili Peppers - What Hits! (1992) {FLAC} vtwin88cube")

    assert make_batch_id(WHEN, folder) == (
        "20261024-2140-red-hot-chili-peppers-what-hits-1992-fla"
    )
