@echo off
REM One-click Shopify OAuth install for Windows cmd + PowerShell.
REM
REM Reads SHOPAI_SHOPIFY_* from .env automatically (no export
REM required); starts the helper on localhost:9000; prints
REM the authorize URL you paste into a browser.
REM
REM Usage (double-click or from any shell):
REM     scripts\shopify_install.cmd
REM
REM Prereqs: Python in PATH, .env populated with
REM SHOPAI_SHOPIFY_CLIENT_ID + SHOPAI_SHOPIFY_CLIENT_SECRET
REM + SHOPAI_SHOPIFY_URL.

setlocal
cd /d "%~dp0\.."
set "PYTHONPATH=%CD%"
python scripts\shopify_oauth_install.py %*
endlocal
