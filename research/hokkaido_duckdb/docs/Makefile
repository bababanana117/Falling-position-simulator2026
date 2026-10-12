# Build the manual. `make` runs the checks first, then HTML, then PDF.
#
# The doctests in distributions.rst open the real database and recompute a
# log-likelihood from the stored constants. If they fail, the manual is
# describing a distribution the database does not contain, so the build stops
# there rather than producing a document that is wrong.

SPHINXOPTS    ?= -W --keep-going -n
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = .
BUILDDIR      = _build
DB            = ../jra3q_hokkaido_wind_2016-2025_v1.duckdb

FIGSRC        = make_figures.py
FIGSTAMP      = _figures/.stamp

.PHONY: all figures doctest html pdf latex clean help

all: figures doctest html pdf

# The figures are drawn from the database, so they are rebuilt when either the
# database or the drawing script changes.
figures: $(FIGSTAMP)

$(FIGSTAMP): $(FIGSRC) $(DB)
	python $(FIGSRC)
	@touch $(FIGSTAMP)

$(DB):
	@echo "データベース $(DB) がありません。"
	@echo "配布物に同梱されているはずのファイルです。展開し直すか、"
	@echo "入力を揃えたうえで python -m hokduck.build --stage all を実行してください。"
	@false

doctest: $(DB) $(FIGSTAMP)
	$(SPHINXBUILD) -b doctest "$(SOURCEDIR)" "$(BUILDDIR)/doctest" $(SPHINXOPTS)

html: $(DB) $(FIGSTAMP)
	$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html" $(SPHINXOPTS)

latex: $(DB) $(FIGSTAMP)
	$(SPHINXBUILD) -b latex "$(SOURCEDIR)" "$(BUILDDIR)/latex" $(SPHINXOPTS)

pdf: latex
	$(MAKE) -C "$(BUILDDIR)/latex" LATEXMKOPTS="-interaction=nonstopmode -halt-on-error" all-pdf
	@cp "$(BUILDDIR)/latex/hokkaido-wind-duckdb.pdf" .
	@echo "できあがり: docs/hokkaido-wind-duckdb.pdf"

clean:
	rm -rf "$(BUILDDIR)" hokkaido-wind-duckdb.pdf _figures

help:
	@echo "make          doctest, HTML, PDF をこの順に作る"
	@echo "make figures  データベースから図を描き直す"
	@echo "make doctest  distributions.rst の検算だけ走らせる"
	@echo "make html     HTML だけ"
	@echo "make pdf      PDF だけ (LuaLaTeX)"
	@echo "make clean    出力を消す"
	@echo ""
	@echo "HOKKAIDO_DOCS_ENGINE=uplatex make pdf  で upLaTeX に切り替わる"
