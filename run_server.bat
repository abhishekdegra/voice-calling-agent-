@echo off
echo Starting Welfog Voice Calling Agent server on http://localhost:8080 ...
"%~dp0.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
pause
