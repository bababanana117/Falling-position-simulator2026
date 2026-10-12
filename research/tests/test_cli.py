"""Command line surface.

The important one is that ``--dry-run`` really is dry: a fixture makes any attempt
to open a socket an error, so a regression that starts downloading during a plan
fails the test rather than the user's bandwidth.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from windclim import cli


def test_parser_builds() -> None:
    assert cli.build_parser().prog == "windclim"


def test_year_range_parsing() -> None:
    assert list(cli._years("2016-2025")) == list(range(2016, 2026))
    assert list(cli._years("2016")) == [2016]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("1", [1]), ("1,3,5", [1, 3, 5]), ("1-3", [1, 2, 3]), ("1-2,12", [1, 2, 12])],
)
def test_month_list_parsing(text: str, expected: list[int]) -> None:
    assert cli._ints(text) == expected


def test_dry_run_lists_every_request_and_opens_no_socket(
    capsys, tmp_path: Path, no_sockets
) -> None:
    rc = cli.main(
        ["fetch", "--dry-run", "--years", "2016-2025", "--cache", str(tmp_path)]
    )
    assert rc == 0
    urls = capsys.readouterr().out.strip().splitlines()
    assert len(urls) == 2160
    assert all(u.startswith("https://tds.gdex.ucar.edu/") for u in urls)


def test_dry_run_skips_what_is_already_cached(capsys, tmp_path: Path, no_sockets) -> None:
    from windclim.fetch import cache

    tasks = cache.plan_tasks(("ugrd",), "anl_p", [2016], months=[1])
    nc = cache.cache_path(tmp_path, tasks[0])
    nc.parent.mkdir(parents=True, exist_ok=True)
    part = cache.part_path(nc)
    part.write_bytes(b"x" * 64)
    cache.finalize(part, nc, {"url": tasks[0].url, "shape": [20, 38, 49, 49]})

    cli.main(
        ["fetch", "--dry-run", "--years", "2016", "--months", "1",
         "--vars", "ugrd", "--cache", str(tmp_path)]
    )
    urls = capsys.readouterr().out.strip().splitlines()
    assert len(urls) == 5
    assert tasks[0].url not in urls


def test_unknown_region_is_rejected() -> None:
    with pytest.raises(SystemExit):
        cli.main(["aggregate", "--region", "okinawa"])


def test_stats_path_encodes_period_and_convention() -> None:
    args = cli.build_parser().parse_args(
        ["aggregate", "--region", "hokkaido", "--years", "2016-2025"]
    )
    path = cli._stats_path(Path("/out"), "hokkaido", args)
    assert path.name == "jra3q_windclim_hokkaido_2016-2025_v1.nc"

    args_jst = cli.build_parser().parse_args(
        ["aggregate", "--region", "hokkaido", "--years", "2016-2025", "--convention", "jst"]
    )
    assert cli._stats_path(Path("/out"), "hokkaido", args_jst).name.endswith("_jst_v1.nc")


def test_compare_says_what_is_missing(tmp_path: Path) -> None:
    args = cli.build_parser().parse_args(["compare", "--out", str(tmp_path)])
    with pytest.raises(SystemExit, match="aggregated first"):
        cli._cmd_compare(args)
