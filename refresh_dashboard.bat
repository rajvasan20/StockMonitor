@echo off
cd /d "C:\Users\VinothRajapandian\Personal Claude\Stock Monitor"
"C:\Users\VinothRajapandian\AppData\Local\Programs\Python\Python312\python.exe" run.py dashboard >> "C:\Users\VinothRajapandian\Personal Claude\Stock Monitor\logs\scheduled_refresh.log" 2>&1
