install:
	pip install -r requirements/dev.txt

run:
	uvicorn app.main:app --reload

test:
	pytest
