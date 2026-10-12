# Build the report. Needs TeX Live with jlreq + luatexja (TeX Live 2024 has both).
#
# Figures are read straight out of ../out/figures via \graphicspath, so there is
# no copy step. They are listed as prerequisites as well: without them, make
# skips latexmk entirely when only a figure was redrawn, and ships a PDF with
# the old picture in it.

.PHONY: all clean watch
all: main.pdf

FIGURES := $(wildcard ../out/figures/*/*.pdf)

main.pdf: main.tex preamble.tex refs.bib $(wildcard sections/*.tex) $(FIGURES)
	latexmk -lualatex main.tex

watch:
	latexmk -lualatex -pvc main.tex

clean:
	latexmk -C
	rm -f *.bbl *.run.xml
