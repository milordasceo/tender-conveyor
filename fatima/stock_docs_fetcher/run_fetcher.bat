@echo off
cd /d "%~dp0"
chcp 65001 >nul
python stock_docs_fetcher.py
