"""VOICEVOX エンジンでナレーションの各行を音声合成する。

build/script.json（scene ごとの行のリスト）を読み、行ごとに
VOICEVOX の /audio_query と /synthesis を呼んで wav を作る。

声は四国めたん「ノーマル」（style id は起動時に /speakers から探す）。
話速・抑揚などは下の VOICE_PARAMS で固定する。

同じ読み上げ文＋パラメータなら同じ wav になるので、
(say, パラメータ) のハッシュをキーにして build/tts/<scene>_<k>.wav に
キャッシュする。すでにあれば作り直さない。

合成の前に、audio_query が返す kana（読み）を見て、
地名や専門用語の誤読がないか確認できるように、該当語を含む行の
読みを画面に出す。数字や単位の読みが変なときもここで気づける。

使い方:
    python tts.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
SCRIPT_JSON = HERE / "build" / "script.json"
TTS_DIR = HERE / "build" / "tts"

ENGINE_URL = "http://127.0.0.1:50021"
SPEAKER_NAME = "四国めたん"
STYLE_NAME = "ノーマル"

# 合成パラメータ（AudioQuery に上書きする値）
VOICE_PARAMS = {
    "speedScale": 1.15,
    "intonationScale": 1.1,
    "pitchScale": 0.0,
    "volumeScale": 1.0,
    "prePhonemeLength": 0.05,
    "postPhonemeLength": 0.05,
    "outputSamplingRate": 44100,
    "outputStereo": False,
}

# 読みを確認したい語とその想定読み（かな）
WATCH_WORDS = {
    "壱岐": "いき",
    "芦辺": "あしべ",
    "平戸": "ひらど",
    "加唐島": "かからしま",
    "糸島": "いとしま",
    "三隅": "みすみ",
    "佐伯": "さえき",
    "瀬戸内海": "せとないかい",
    "着水": "ちゃくすい",
    "再解析": "さいかいせき",
    "落下点": "らっかてん",
    "実施": "じっし",
}


def get_style_id(session: requests.Session) -> int:
    """/speakers から四国めたん「ノーマル」の style id を探す。"""
    r = session.get(f"{ENGINE_URL}/speakers", timeout=30)
    r.raise_for_status()
    for speaker in r.json():
        if speaker["name"] != SPEAKER_NAME:
            continue
        for style in speaker["styles"]:
            if style["name"] == STYLE_NAME:
                return style["id"]
    raise RuntimeError(f"{SPEAKER_NAME} の {STYLE_NAME} スタイルが見つかりません")


def cache_key(say: str) -> str:
    payload = json.dumps({"say": say, "params": VOICE_PARAMS}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def check_kana(scene_id: str, idx: int, say: str, query: dict) -> None:
    """audio_query の kana を見て、監視対象の語の読みや数字の読みを表示する。"""
    kana_parts = []
    for phrase in query.get("accent_phrases", []):
        for mora in phrase.get("moras", []):
            kana_parts.append(mora.get("text", ""))
        if phrase.get("pause_mora"):
            kana_parts.append(phrase["pause_mora"].get("text", ""))
    kana = "".join(kana_parts)

    hits = [w for w in WATCH_WORDS if w in say]
    if hits:
        print(f"  [kana] {scene_id}#{idx}: say={say!r}")
        print(f"         kana={kana!r}")
        for w in hits:
            print(f"         監視語 {w}（想定 {WATCH_WORDS[w]}）を含む -> 上の kana を確認")

    # 数字や単位が残っていないか（本来はかなに開いているはず）
    import re

    if re.search(r"[0-9０-９]", say):
        print(f"  [数字?] {scene_id}#{idx}: say に数字が残っています -> say={say!r}")


def synthesize_line(session: requests.Session, style_id: int, scene_id: str, idx: int, say: str) -> Path:
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    key = cache_key(say)
    out_path = TTS_DIR / f"{scene_id}_{idx}.wav"
    meta_path = TTS_DIR / f"{scene_id}_{idx}.key"

    if out_path.exists() and meta_path.exists() and meta_path.read_text(encoding="utf-8").strip() == key:
        return out_path

    q_resp = session.post(
        f"{ENGINE_URL}/audio_query",
        params={"text": say, "speaker": style_id},
        timeout=60,
    )
    q_resp.raise_for_status()
    query = q_resp.json()

    check_kana(scene_id, idx, say, query)

    query.update(VOICE_PARAMS)

    s_resp = session.post(
        f"{ENGINE_URL}/synthesis",
        params={"speaker": style_id},
        json=query,
        timeout=120,
    )
    s_resp.raise_for_status()

    out_path.write_bytes(s_resp.content)
    meta_path.write_text(key, encoding="utf-8")
    return out_path


def main() -> int:
    scenes = json.loads(SCRIPT_JSON.read_text(encoding="utf-8"))

    session = requests.Session()
    ver = session.get(f"{ENGINE_URL}/version", timeout=10).text
    style_id = get_style_id(session)
    print(f"VOICEVOX engine version={ver} style_id={style_id} ({SPEAKER_NAME}/{STYLE_NAME})")

    n_done = 0
    n_cached = 0
    for scene in scenes:
        scene_id = scene["id"]
        for idx, line in enumerate(scene["lines"]):
            say = line["say"]
            out_path = TTS_DIR / f"{scene_id}_{idx}.wav"
            key = cache_key(say)
            meta_path = TTS_DIR / f"{scene_id}_{idx}.key"
            was_cached = out_path.exists() and meta_path.exists() and meta_path.read_text(encoding="utf-8").strip() == key
            synthesize_line(session, style_id, scene_id, idx, say)
            if was_cached:
                n_cached += 1
            else:
                n_done += 1

    print(f"synthesized {n_done} lines, {n_cached} from cache, output dir={TTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
