"""Entry point – FastAPI app with MES simulator running as background task."""
import asyncio
import os
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from app.database import connect_and_init, disconnect
from app.mes.simulator import run as run_mes, stop as stop_mes
from app.api.routes import router
from app.ws.manager import manager as ws_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────
    await connect_and_init()
    sim_task = asyncio.create_task(run_mes())
    yield
    # ── Shutdown ──────────────────────────────────────────────
    stop_mes()
    sim_task.cancel()
    try:
        await sim_task
    except asyncio.CancelledError:
        pass
    await disconnect()
    print("[App] Shutdown complete.")


app = FastAPI(
    title="Semiconductor Process Simulation",
    description="MES + Station Agent + Time-Machine API + Real-time WS (v1.1)",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep-alive: accept any ping text from client
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8001"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
