@echo off
REM Stock Monitor — Daily Price Fetcher
REM Scheduled to run at 6 PM IST via Windows Task Scheduler

cd /d "C:\Users\VinothRajapandian\Personal Claude\Stock Monitor"
python run.py prices >> logs\price_fetch.log 2>&1
