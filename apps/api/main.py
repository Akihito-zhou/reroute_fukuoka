from fastapi import FastAPI

from routes import router

app = FastAPI(title="Re-Route FUKUOKA API", version="0.1.0")
app.include_router(router)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"status": "ok"}
