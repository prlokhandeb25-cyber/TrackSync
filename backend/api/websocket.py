import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from backend.api.routes import sim_engine

ws_router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                pass

manager = ConnectionManager()

@ws_router.websocket("/ws/state")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            if sim_engine:
                if sim_engine.is_running:
                    sim_engine.tick(delta_sim_min=1.0 * sim_engine.speed_multiplier)
                snapshot = sim_engine.get_state_snapshot()
                await websocket.send_text(json.dumps(snapshot))
            await asyncio.sleep(0.25)  # 4 Hz update rate
    except WebSocketDisconnect:
        manager.disconnect(websocket)
