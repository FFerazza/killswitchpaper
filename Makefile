# Pipeline entrypoints. Every target is idempotent and resumable.
# PY defaults to the venv interpreter; override with `make PY=python3 ...`
# or run BGP targets inside Docker (see RUNNING.md).

PY ?= .venv/bin/python

.PHONY: test population bgp-ribs bgp-events ioda ripestat ripestat-compare analysis test-week docker-image

test:
	$(PY) -m pytest -q

population:
	$(PY) -m src.population

bgp-ribs:
	$(PY) -m src.bgp ribs

bgp-events:
	$(PY) -m src.bgp events

# D-012 secondary series (RouteViews + direct-fetched RIS); Docker only.
bgp-ribs-ris:
	$(PY) -m src.bgp ribs-ris

ioda:
	$(PY) -m src.ioda

ripestat:
	$(PY) -m src.ripestat fetch

ripestat-compare:
	$(PY) -m src.ripestat compare

analysis:
	$(PY) -m src.analysis

docker-image:
	docker build -t killswitch-pipeline .

# Milestone 1: one test week around the P2 boundary (2026-02-25 -> 03-03),
# validated against RIPEstat on the sample ASNs.
test-week:
	$(PY) -m src.bgp ribs --window test_week
	$(PY) -m src.bgp events --window feb2026_onset
	$(PY) -m src.ioda --window test_week
	$(PY) -m src.ripestat fetch
	$(PY) -m src.analysis --only bgp_vs_ioda
	$(PY) -m src.ripestat compare
