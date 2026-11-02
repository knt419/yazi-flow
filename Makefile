PY ?= .venv/bin/python

.PHONY: install test test-unit test-probe venv clean

install:            ## build the patched yazi and link the launcher
	scripts/build.sh

test: test-unit test-probe

test-unit:          ## pure helpers: DSR parsing, anchor maths, binary lookup
	$(PY) tests/unit.py

test-probe: venv    ## PTY probe against the installed binary (POSIX only)
	$(PY) tests/probe.py

venv:
	@test -x $(PY) || { python3 -m venv .venv && .venv/bin/pip install -q -r tests/requirements.txt; }

clean:              ## drop the build tree (keeps the installed binary)
	rm -rf build/src/target

.DEFAULT_GOAL := install
