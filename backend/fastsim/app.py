"""FastAPI application factory (single-process MVP per dev doc chapter 4)."""
from __future__ import annotations

import argparse
import logging
import pathlib
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router, ws_router, manager as _manager_slot, get_manager
from .core.manager import SessionManager

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

FRONTEND_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "frontend"


def create_app(profiles_dir: Optional[str] = None,
               scenarios_dir: Optional[str] = None,
               recordings_dir: Optional[str] = None) -> FastAPI:
    base = pathlib.Path(__file__).resolve().parent.parent
    profiles_dir = profiles_dir or str(base / "profiles")
    scenarios_dir = scenarios_dir or str(base / "scenarios")
    recordings_dir = recordings_dir or str(base / "recordings")
    pathlib.Path(recordings_dir).mkdir(parents=True, exist_ok=True)

    m = SessionManager(profiles_dir=profiles_dir, scenarios_dir=scenarios_dir)
    # inject manager into routes module
    import fastsim.api.routes as routes
    routes.manager = m

    app = FastAPI(title="FastSim", version="0.1.0",
                  description="SECS/GEM simulator & EAP test platform")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
    app.include_router(ws_router)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await m.shutdown()

    # frontend static files
    if FRONTEND_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

        @app.get("/")
        async def index():
            return FileResponse(FRONTEND_DIR / "index.html")

    app.state.manager = m
    return app


app = None  # created lazily by main()


def main() -> None:
    global app
    parser = argparse.ArgumentParser(description="FastSim server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--profiles", default=None)
    parser.add_argument("--scenarios", default=None)
    args = parser.parse_args()
    app = create_app(profiles_dir=args.profiles, scenarios_dir=args.scenarios)

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
