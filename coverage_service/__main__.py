import uvicorn
from .app import app

if __name__ == "__main__":
    # 0.0.0.0 -> reachable over the LAN at http://<host-LAN-IP>:8900
    uvicorn.run(app, host="0.0.0.0", port=8900)
