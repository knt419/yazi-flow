PY ?= .venv/bin/python

.PHONY: install test venv clean

install:            ## build the patched yazi and link the launcher
	scripts/build.sh

test: venv          ## run the PTY probe against the installed binary
	$(PY) tests/probe.py

venv:
	@test -x $(PY) || { python3 -m venv .venv && .venv/bin/pip install -q -r tests/requirements.txt; }

clean:              ## drop the build tree (keeps the installed binary)
	rm -rf build/src/target

.DEFAULT_GOAL := install
