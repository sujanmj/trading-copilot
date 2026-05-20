web: cd backend && uvicorn api_server:app --host 0.0.0.0 --port $PORT
worker: cd backend && python master_scheduler.py
web: TZ=Asia/Kolkata python backend/api_server.py