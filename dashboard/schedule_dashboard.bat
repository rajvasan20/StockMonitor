@echo off
REM Nifty 100 Dashboard — Daily 6 PM IST refresh
REM Schedule this via Windows Task Scheduler:
REM   1. Open Task Scheduler (taskschd.msc)
REM   2. Create Basic Task > Name: "Nifty 100 Dashboard"
REM   3. Trigger: Daily, Start time: 6:00 PM
REM   4. Action: Start a Program
REM      Program: "C:\Users\VinothRajapandian\Claude Apps\Stock Monitor\dashboard\schedule_dashboard.bat"
REM   5. Check "Run whether user is logged on or not"

cd /d "C:\Users\VinothRajapandian\Claude Apps\Stock Monitor"
python run.py dashboard

echo Dashboard generated at %date% %time% >> logs\dashboard_schedule.log
