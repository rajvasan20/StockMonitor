@echo off
REM Run this script as Administrator to create the scheduled task
schtasks /create /tn "StockMonitor_PriceFetch" /tr "C:\Users\VinothRajapandian\Personal Claude\Stock Monitor\scripts\fetch_prices.bat" /sc daily /st 18:00 /f
echo.
echo Task created: StockMonitor_PriceFetch (daily at 6:00 PM)
echo To verify: schtasks /query /tn "StockMonitor_PriceFetch"
pause
