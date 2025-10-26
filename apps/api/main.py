import os
from typing import Sequence

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import router

app = FastAPI(title="Re-Route FUKUOKA API", version="0.1.0")

allowed_origins_env = os.getenv("ALLOWED_ORIGINS")
if allowed_origins_env:
    origin_list: Sequence[str] = [
        origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()
    ]
else:
    origin_list = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(origin_list),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"status": "ok"}
