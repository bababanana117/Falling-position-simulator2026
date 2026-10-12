# Build the talk. `make` = figures -> latexmk -> check.
#
# Figures are regenerated from ../research/out (CSV and NetCDF) by
# make_figures.py; the deck never reads the report's figures directly because
# the slide palette and font sizes differ.

PY       := $(HOME)/anaconda3/envs/jra3q/bin/python
LATEXMK  := latexmk -lualatex
RESEARCH := ../research
SLIDES   := $(wildcard slides/*.tex)
DATA     := $(wildcard $(RESEARCH)/out/csv/*.csv) $(wildcard $(RESEARCH)/out/netcdf/*_v1.nc)

.PHONY: all figures check watch clean
all: main.pdf check

figures: figures/.stamp
figures/.stamp: make_figures.py $(DATA)
	$(PY) make_figures.py && touch $@

main.pdf: main.tex beamerthemewindclim.sty refs.tex latexmkrc $(SLIDES) title-slide-background.png $(wildcard figures/*.pdf)
	$(LATEXMK) main.tex

check: main.pdf
	$(PY) check.py main.pdf --log main.log --out preview

watch:
	$(LATEXMK) -pvc main.tex

clean:
	latexmk -C
	rm -rf preview figures/.stamp
