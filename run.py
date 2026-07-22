import subprocess
import time
import os

def run_services():
    # Start Backend
    print("Starting Flask Backend...")
    backend_process = subprocess.Popen(["py", "backend/app.py"], cwd=os.getcwd())
    
    # Start Frontend (Using python http.server as a simple alternative if npm/vite is restricted)
    print("Starting Frontend Server...")
    frontend_process = subprocess.Popen(["py", "-m", "http.server", "8000"], cwd=os.path.join(os.getcwd(), "frontend"))
    
    print("\n" + "="*30)
    print("PingThePanchayat is ACTIVE!")
    print("Frontend: http://localhost:8000")
    print("Backend API: http://localhost:5000")
    print("="*30)
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
        backend_process.terminate()
        frontend_process.terminate()

if __name__ == "__main__":
    run_services()
