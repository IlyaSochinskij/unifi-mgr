@echo off
.venv\Scripts\python.exe -m pytest -m "fast or not slow" --no-cov -q %*
