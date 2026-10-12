# レポートを作る。表は make_tables.py、図は figures.py で先に作っておく。
.PHONY: all clean
all: main.pdf

main.pdf: main.tex preamble.tex $(wildcard sections/*.tex) $(wildcard tables/*.tex) $(wildcard ../figures/*)
	latexmk -lualatex main.tex

clean:
	latexmk -C
