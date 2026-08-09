.PHONY: help install test validate run report all clean audit sensitivity

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n",$$1,$$2}'

install:  ## install in editable mode with dev extras
	pip install -e ".[dev]"

validate:  ## check the agreement statistics against published reference values
	PYTHONPATH=src python3 -m rubricon.cli validate

test:  ## run the test suite
	PYTHONPATH=src python3 -m pytest tests/ -q

run:  ## run the full evaluation pipeline (offline, no API key)
	PYTHONPATH=src python3 -m rubricon.cli run

report:  ## render the markdown report and HTML dashboard
	PYTHONPATH=src python3 -m rubricon.cli report

audit:  ## verify every number quoted in docs/ traces to results/portfolio.json
	PYTHONPATH=src python3 scripts/audit_numbers.py

sensitivity:  ## perturb every hand-set assumption and report which verdicts survive
	PYTHONPATH=src python3 scripts/sensitivity_report.py

# 'sensitivity' is deliberately NOT part of 'all'. It takes several minutes and
# it always exits 0, so wiring it into the default build would add latency
# without adding a check. Run it before publishing a verdict, not on every edit.
all: validate test run report audit  ## full reproducible build

clean:
	rm -rf results/* .cache __pycache__ .pytest_cache
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
