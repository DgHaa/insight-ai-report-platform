@echo off
cd /d D:\DJY\project\Insight
"C:\Users\Dong\AppData\Local\Programs\Python\Python312\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8080 >> backend.log 2>> backend.err.log
