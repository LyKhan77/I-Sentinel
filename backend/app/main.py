from fastapi import FastAPI
from app.core.config import settings

app = FastAPI(title="I-Sentinel API", version="0.1.0")

@app.get("/api/v1/health")
def health(): return {"status": "ok"}
