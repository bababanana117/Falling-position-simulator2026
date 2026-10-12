"""Sphinx configuration for the Hokkaido wind database manual.

Two decisions here are not obvious and must not be "tidied up" later.

**The document class is ltjsbook, not jlreq.** jlreq is the obvious choice for
a Japanese document and switching to it looks like an improvement. It breaks
the build. Sphinx
loads ``titlesec`` unconditionally in ``sphinxlatexstyleheadings.sty`` and
calls ``\\titleformat{\\section}``; titlesec works by patching
``\\@startsection``, of which jlreq.cls has none and ltjsbook.cls has eleven.
With jlreq the headings come out unformatted or the run dies outright.
``ltjsbook.cls`` loads luatexja itself, which is why the font setup below is
so short.

**Sphinx has no lualatex + Japanese combination.** ``sphinx.builders.latex
.constants`` knows ``('platex','ja')`` and ``('xelatex','ja')`` but not
``('lualatex','ja')``, so left alone it emits polyglossia, fontspec and
FreeSerif, and never loads luatexja. Every package that would conflict is
therefore blanked below, and the font setup goes in ``fontpkg`` rather than
``preamble`` because ``fontpkg`` is expanded before ``\\usepackage{sphinx}``
whereas ``preamble`` lands after hyperref, which is too late.

Set ``HOKKAIDO_DOCS_ENGINE=uplatex`` to fall back to Sphinx's own Japanese
path if a TeX installation ever lacks luatexja.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "_ext"))

project = "JRA-3Q 北海道 高層風 統計データベース"
author = "西濱大将"
copyright = f"{date.today().year}, {author}"
version = release = "1.0"
language = "ja"

extensions = [
    "sphinx.ext.mathjax",
    "sphinx.ext.doctest",
    "duckdbdoc",
]

#: The database the schema chapter describes. Read at build time so the manual
#: cannot drift from the artefact it documents.
duckdbdoc_database = str(
    Path(__file__).resolve().parent.parent / "jra3q_hokkaido_wind_2016-2025_v1.duckdb"
)
duckdbdoc_sql_dir = str(Path(__file__).resolve().parent / "_sql")

# doctest blocks get the database path without having to guess the working
# directory sphinx-build was started from.
doctest_global_setup = f"""
import duckdb, numpy as np
DB = {duckdbdoc_database!r}
con = duckdb.connect(DB, read_only=True)
"""
doctest_global_cleanup = "con.close()"

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
templates_path = ["_templates"]
html_static_path = ["_static"]
html_theme = "furo"
html_title = "北海道 高層風 統計データベース"
numfig = True
numfig_format = {"table": "表 %s", "figure": "図 %s", "code-block": "リスト %s"}

# Japanese has no inter-word spaces, so a long ``literal`` in running text must
# be allowed to break; furo's default would push it past the margin.
html_css_files = ["overrides.css"]

# ------------------------------------------------------------------ LaTeX --
_engine = os.environ.get("HOKKAIDO_DOCS_ENGINE", "lualatex")
latex_engine = "uplatex" if _engine == "uplatex" else "lualatex"
latex_documents = [(
    "index",
    "hokkaido-wind-duckdb.tex",
    "JRA-3Q 北海道 高層風 統計データベース 利用手引",
    author,
    "manual",
)]
latex_logo = None
latex_show_urls = "footnote"
latex_table_style = ["booktabs"]

if latex_engine == "lualatex":
    latex_docclass = {"manual": "ltjsbook", "howto": "ltjsarticle"}
    latex_elements = {
        "papersize": "a4paper",
        "pointsize": "10pt",
        "babel": "",
        "polyglossia": "",
        "inputenc": "",
        "cmappkg": "",
        "fontenc": "",
        "fncychap": "",
        "fontsubstitution": "",
        "textgreek": "",
        "geometry": r"\usepackage[margin=25mm,includefoot]{geometry}",
        "fontpkg": r"""
\usepackage[haranoaji,deluxe]{luatexja-preset}
\usepackage{unicode-math}
\setmainfont{TeX Gyre Termes}
\setsansfont{TeX Gyre Heros}
\setmonofont{TeX Gyre Cursor}[Scale=MatchLowercase]
\setmathfont{TeX Gyre Termes Math}
""",
        "preamble": r"""
\usepackage{needspace}
% A code block that would be split across a page break with fewer than six
% lines on the first page is pushed whole to the next page instead.
\makeatletter
\let\hok@orig@VerbatimEnvironment\FV@BeginVerbatimEnvironment
\makeatother
% Japanese inside a verbatim block otherwise gets Latin inter-character
% spacing from luatexja's default jacharrange; SQL comments are Japanese here.
\ltjsetparameter{jacharrange={-2,-3}}
\setlength{\parindent}{1\zw}
% A long snake_case identifier in a narrow table cell has nowhere to break
% and runs past the rule. Allow a break after an underscore inside inline
% literals; \sphinxcode is what docutils wraps every ``literal`` in.
% A long snake_case identifier in a narrow table cell has nowhere to break and
% runs past the rule. Allow a break after an underscore or a hyphen, but at a
% high penalty: running text has better places to break, so an identifier
% there stays whole, while a table cell with no alternative splits rather than
% overflowing. \sphinxhyphen is what Sphinx emits for a hyphen, and it
% normally forbids breaking outright.
\let\hokUnderscore\_
\protected\def\_{\hokUnderscore\penalty9000\hspace{0pt}}
\protected\def\sphinxhyphen{-\penalty9000\hspace{0pt}}
% The index is listed twice in the table of contents: ltjsbook's theindex
% environment adds a line, and Sphinx's sphinxtheindex wrapper adds another
% right after. Sphinx's is the one to keep -- it comes with the
% \phantomsection the hyperlink needs -- so the first \addcontentsline inside
% theindex is swallowed and the macro restored immediately.
\makeatletter
\AtBeginDocument{%
  \let\hok@theindex\theindex
  \def\theindex{%
    \let\hok@addcontentsline\addcontentsline
    \def\addcontentsline##1##2##3{\let\addcontentsline\hok@addcontentsline}%
    \hok@theindex}%
}
\makeatother
""",
        "sphinxsetup": (
            "verbatimwithframe=false,"
            "VerbatimColor={HTML}{F7FAFD},"
            "VerbatimBorderColor={HTML}{D7E3EE},"
            "TitleColor={HTML}{1A3A5C},"
            "InnerLinkColor={HTML}{1A5C8A},"
            "OuterLinkColor={HTML}{1A5C8A}"
        ),
        "tableofcontents": r"\sphinxtableofcontents",
    }
else:  # pragma: no cover -- the documented escape hatch
    latex_elements = {"papersize": "a4paper", "pointsize": "10pt"}

# Mathjax only affects HTML; the PDF gets LaTeX maths directly from the writer.
mathjax3_config = {"tex": {"inlineMath": [["\\(", "\\)"]]}}
