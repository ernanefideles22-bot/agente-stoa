from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "ok"}

def helper():
    return True

@app.get("/ping")
async def ping():
    return {"ping": "pong"}
@app.get("/status")
async def status():
    return {"status": "ok"}
