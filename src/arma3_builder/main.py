"""FastAPI entrypoint."""
from __future__ import annotations

import os

from fastapi import FastAPI

from .api.routes import router

app = FastAPI(
    title="arma3-builder",
    version="0.1.0",
    description="Multi-agent campaign generator for Arma 3 (Real Virtuality 4)",
)
app.include_router(router)


def run() -> None:
    import uvicorn  # local import keeps test imports cheap

    uvicorn.run(
        "arma3_builder.main:app",
        host=os.environ.get("ARMA3_HOST", "0.0.0.0"),
        port=int(os.environ.get("ARMA3_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":  # pragma: no cover
    run()
