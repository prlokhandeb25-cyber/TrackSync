import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router as api_router, init_api_services
from backend.api.websocket import ws_router
from backend.data.ingest import TimetableIngester
from backend.data.synth_tasks import TaskGenerator
from backend.sim.simulator import SimulatorEngine

app = FastAPI(
    title="RailBlock AI API",
    description="AI-Powered Automatic Block Planning for Indian Railways API Engine",
    version="1.0.0"
)

# Enable CORS for Vite frontend (http://localhost:5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.include_router(ws_router)

@app.on_event("startup")
def startup_event():
    config_path = "config/network/central_line.yaml"
    ingester = TimetableIngester(config_path)
    trains = ingester.generate_synthetic_timetable(seed=42)
    tasks = TaskGenerator.generate_weekly_planned_tasks(ingester.network, num_tasks=35, seed=42)

    sim = SimulatorEngine(ingester.network, trains, tasks)
    sim.log_event("RailBlock AI Simulation Engine initialized on Central Main Line corridor.", "INFO")
    init_api_services(sim)

@app.get("/")
def root():
    return {"message": "RailBlock AI Engine Active", "status": "ONLINE"}
