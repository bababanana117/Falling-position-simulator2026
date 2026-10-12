"""記事を公開前に検査する。

画像は `../images/<slug>/...` の相対パスで書く（この形に統一する）。
形が揃っていない参照は Markdown としては正しいので警告も出ない。
ここでは「拾えたかどうか」ではなく「あるべき形か」を見る。

    python check.py
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARTICLES = HERE / "articles"
IMAGES = HERE / "images"

IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
REF_USE = re.compile(r"(?<!!)\[[^\]]+\]\[([a-zA-Z0-9_-]+)\]")
REF_DEF = re.compile(r"^\[([a-zA-Z0-9_-]+)\]:\s*(\S+)", re.MULTILINE)
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def check(path: Path) -> list[str]:
    bad: list[str] = []
    text = path.read_text(encoding="utf-8")
    slug = path.stem

    def fail(msg: str) -> None:
        bad.append(f"{path.name}: {msg}")

    # --- frontmatter ---------------------------------------------------
    head = FRONTMATTER.match(text)
    if not head:
        fail("frontmatter が無い")
        return bad
    fm = head.group(1)
    for key in ("title", "emoji", "type", "topics", "published"):
        if not re.search(rf"^{key}:", fm, re.MULTILINE):
            fail(f"frontmatter に {key} が無い")
    if not 12 <= len(slug) <= 50:
        fail(f"slug の長さ {len(slug)} が 12--50 の外")
    if not re.fullmatch(r"[a-z0-9_-]+", slug):
        fail("slug に使えない文字がある")
    topics = re.search(r"^topics:\s*\[(.*)\]", fm, re.MULTILINE)
    if topics and len([t for t in topics.group(1).split(",") if t.strip()]) > 5:
        fail("topics が 5 個を超えている")
    emoji = re.search(r'^emoji:\s*"(.+)"', fm, re.MULTILINE)
    if emoji and len(emoji.group(1)) != 1:
        fail("emoji は 1 文字でなければならない")

    # --- 画像 -----------------------------------------------------------
    for alt, src in IMAGE.findall(text):
        if not src.startswith("../images/"):
            fail(f"画像パスが ../images/ で始まっていない: {src}")
            continue
        if not (ARTICLES / src).resolve().exists():
            fail(f"画像が無い: {src}")
        if not alt.strip():
            fail(f"alt が空: {src}")
    folder = IMAGES / slug
    if folder.exists():
        used = {s for _, s in IMAGE.findall(text)}
        for png in sorted(folder.glob("*.png")):
            if f"../images/{slug}/{png.name}" not in used:
                fail(f"未使用の画像: {png.name}")

    # --- リンク ---------------------------------------------------------
    for label, href in LINK.findall(text):
        if href.startswith(("./", "../")):
            fail(f"相対リンクは Zenn で解決しない: [{label}]({href})")
    defined = {name for name, _ in REF_DEF.findall(text)}
    for ref in REF_USE.findall(text):
        if ref not in defined:
            fail(f"参照リンク [{ref}] の定義が無い")

    # --- 記法 -----------------------------------------------------------
    for name, opener in (("message", ":::message"), ("details", ":::details")):
        opened = len(re.findall(rf"^{re.escape(opener)}", text, re.MULTILINE))
        if opened and text.count("\n:::\n") + text.endswith("\n:::") < 1:
            fail(f"{name} ブロックが閉じていない可能性")
    if re.search(r"^```mermaid", text, re.MULTILINE) and "```\n" not in text:
        fail("mermaid ブロックが閉じていない")

    # --- 強調が閉じられるか（CommonMark の right-flanking 規則）-----------
    # 閉じる ** の直前が約物で、直後が文字だと、その ** は閉じ記号として
    # 認められず ** がそのまま出る。日本語では「。**次の文」で起きやすい。
    for m in re.finditer(r"\*\*([^*\n]+)\*\*", text):
        inner, after_pos = m.group(1), m.end()
        after = text[after_pos] if after_pos < len(text) else "\n"
        last = inner[-1]
        if (unicodedata.category(last).startswith("P")
                and not after.isspace()
                and not unicodedata.category(after).startswith("P")):
            line = text[:m.start()].count("\n") + 1
            fail(f"{line} 行目: 強調が閉じない。"
                 f"「{last}」を ** の外に出す —— …{inner[-12:]}**{after}")
    return bad


def main() -> int:
    problems: list[str] = []
    for path in sorted(ARTICLES.glob("*.md")):
        found = check(path)
        mark = "NG" if found else "ok"
        text = path.read_text(encoding="utf-8")
        figures = len(IMAGE.findall(text))
        print(f"  [{mark}] {path.stem:36} 図 {figures:2} 本文 {len(text):6} 字")
        problems += found
    if problems:
        print("\n問題:")
        for p in problems:
            print("   ", p)
        return 1
    print("\n問題なし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
