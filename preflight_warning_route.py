from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/status")
async def status():
    return {"status": "ok"}
