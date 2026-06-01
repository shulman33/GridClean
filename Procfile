web: sh -c 'uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2'
release: alembic upgrade head
