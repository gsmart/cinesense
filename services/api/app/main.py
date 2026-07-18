from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.lookup import router as lookup_router

app = FastAPI(title="cineSense API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(lookup_router, prefix="/api/v1")


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}

