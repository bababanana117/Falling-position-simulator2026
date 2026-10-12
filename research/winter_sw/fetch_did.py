"""国土数値情報「人口集中地区（DID）」2020 年を都道府県ごとに取ってくる。

落下点が市街地に入るかの判定に使う。落下判定の範囲（北緯 24–38.5 度）にかかる
都府県だけを取る（北海道・青森・岩手・秋田は範囲外）。

出典: 国土交通省 国土数値情報（人口集中地区データ）
https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A16-2020.html

    python winter_sw/fetch_did.py
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from urllib.request import urlopen

log = logging.getLogger("winter_sw.did")

HERE = Path(__file__).resolve().parent
CACHE = HERE / "data" / "did"
URL = "https://nlftp.mlit.go.jp/ksj/gml/data/A16/A16-20/A16-20_{code:02d}_GML.zip"
#: 落下判定の範囲にかかる都道府県コード
PREFS = [4] + list(range(6, 48))


def fetch(code: int) -> Path:
    out = CACHE / f"A16-20_{code:02d}_DID.geojson"
    if out.exists():
        return out
    CACHE.mkdir(parents=True, exist_ok=True)
    zpath = CACHE / f"A16-20_{code:02d}_GML.zip"
    if not zpath.exists():
        with urlopen(URL.format(code=code), timeout=300) as r:
            data = r.read()
        tmp = zpath.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.rename(zpath)
    with zipfile.ZipFile(zpath) as z:
        name = next(n for n in z.namelist() if n.endswith("_DID.geojson"))
        out.write_bytes(z.read(name))
    zpath.unlink()
    log.info("got %s", out.name)
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    for code in PREFS:
        fetch(code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
