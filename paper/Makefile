.PHONY: pdf clean

# CLAUDE.md specifies `latexmk -pdf`; this environment has no texlive/sudo
# access, so tectonic (a self-contained engine, no system TeX install
# needed) is used instead - same result (main.pdf), verified working.
# If latexmk/texlive is installed later, `latexmk -pdf main.tex` is a
# drop-in replacement for the pdf target.
pdf:
	tectonic main.tex

clean:
	rm -f main.pdf
