.PHONY: report test lint
report:
	PYTHONPATH=src python -m reportbot.cli --month 2025-12 --no-email
test:
	pytest -q
lint:
	ruff check . && ruff format --check .
