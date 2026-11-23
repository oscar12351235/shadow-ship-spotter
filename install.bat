@echo off
setlocal

where uv >nul 2>&1
if errorlevel 1 (
  echo uv is required but not installed. 1>&2
  exit /b 1
)

uv sync --python 3.12 --all-groups
set "UV_EXIT_CODE=%ERRORLEVEL%"
if not "%UV_EXIT_CODE%"=="0" exit /b %UV_EXIT_CODE%

echo Installed. Try: uv run pytest
