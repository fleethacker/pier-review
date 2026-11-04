"""
Local FastAPI Model Server — Wind Correction
=============================================
For local development/testing. Serves the same PyTorch models
that would be deployed to Domino Model Registry in production.

Run: python model_server.py
Serves on: http://localhost:5051

Endpoints:
  POST /wind-correct  — Get wind correction for aircraft state
  GET  /health         — Health check
  GET  /models         — List loaded models

This mirrors the Domino Model API predict() function but runs locally
via FastAPI so you don't need a Domino instance for development.
"""

import os
import numpy as np
import torch
import torch.nn as nn
import pickle
from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware

# ============================================================
# MODEL DEFINITION (must match training architecture exactly)
# ============================================================
CORRECTION_RANGES = {"heading": 15.0, "throttle": 50.0, "pitch": 10.0}


class WindCorrectionNet(nn.Module):
    def __init__(self, input_dim=9, hidden_dims=[128, 64, 32], output_dim=3, dropout=0.1):
        super().__init__()
        layers = []
        prev_dim = input_dim
        for h_dim in hidden_dims:
            layers.extend([nn.Linear(prev_dim, h_dim), nn.ReLU(), nn.Dropout(dropout)])
            prev_dim = h_dim
        layers.extend([nn.Linear(prev_dim, output_dim), nn.Tanh()])
        self.network = nn.Sequential(*layers)
        self.register_buffer('output_scale', torch.tensor([
            CORRECTION_RANGES["heading"], CORRECTION_RANGES["throttle"], CORRECTION_RANGES["pitch"]
        ]))

    def forward(self, x):
        return self.network(x) * self.output_scale


# ============================================================
# FASTAPI APP
# ============================================================
app = FastAPI(title="Wind Correction Model Server (Local)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

AIRCRAFT_NAMES = {
    "x47b": "X-47B UCAV",
    "cessna172": "Cessna 172 Skyhawk",
    "mq9_reaper": "MQ-9 Reaper",
}

MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
models = {}
scalers = {}


@app.on_event("startup")
async def load_models():
    """Load all available aircraft models at startup."""
    for aircraft_id in AIRCRAFT_NAMES:
        model_path = os.path.join(MODEL_DIR, f"wind_correction_{aircraft_id}.pt")
        scaler_path = os.path.join(MODEL_DIR, f"feature_scaler_{aircraft_id}.pkl")

        if os.path.exists(model_path) and os.path.exists(scaler_path):
            model = WindCorrectionNet()
            model.load_state_dict(torch.load(model_path, map_location="cpu", weights_only=True))
            model.eval()
            models[aircraft_id] = model

            with open(scaler_path, "rb") as f:
                scalers[aircraft_id] = pickle.load(f)

            print(f"Loaded: {AIRCRAFT_NAMES[aircraft_id]} ({aircraft_id})")
        else:
            print(f"Not found: {aircraft_id} (run 02_training.ipynb first)")

    print(f"\n{len(models)} models ready for inference")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "models_loaded": list(models.keys()),
        "count": len(models),
    }


@app.get("/models")
async def list_models():
    """List all loaded models with their aircraft details."""
    return {
        aircraft_id: {
            "name": AIRCRAFT_NAMES[aircraft_id],
            "loaded": True,
        }
        for aircraft_id in models
    }


@app.post("/wind-correct")
async def wind_correct(data: dict = Body(...)):
    """
    Predict optimal wind corrections for the given aircraft state.

    Request body:
    {
        "aircraft_id": "x47b",
        "speed": 200.0,         # km/h
        "heading": 45.0,        # degrees
        "pitch": 2.0,           # degrees
        "roll": -5.0,           # degrees
        "vertical_velocity": 0.5,
        "wind_dir": 90.0,       # degrees
        "wind_speed": 25.0,     # m/s
        "turbulence": 0.6       # 0-1
    }

    Response:
    {
        "corrections": {
            "heading_correction": 3.2,
            "throttle_correction": -12.5,
            "pitch_correction": 1.1
        }
    }
    """
    aircraft_id = data.get("aircraft_id", "x47b")

    if aircraft_id not in models:
        return {
            "error": f"No model for '{aircraft_id}'",
            "available": list(models.keys()),
            "corrections": {"heading_correction": 0, "throttle_correction": 0, "pitch_correction": 0}
        }

    model = models[aircraft_id]
    scaler = scalers[aircraft_id]

    wind_dir_rad = np.radians(data.get("wind_dir", 0))
    features = np.array([[
        data.get("speed", 200),
        data.get("heading", 0),
        data.get("pitch", 0),
        data.get("roll", 0),
        data.get("vertical_velocity", 0),
        np.sin(wind_dir_rad),
        np.cos(wind_dir_rad),
        data.get("wind_speed", 0),
        data.get("turbulence", 0),
    ]])

    features_scaled = scaler.transform(features)

    with torch.no_grad():
        input_tensor = torch.FloatTensor(features_scaled)
        corrections = model(input_tensor).numpy()[0]

    return {
        "corrections": {
            "heading_correction": round(float(corrections[0]), 3),
            "throttle_correction": round(float(corrections[1]), 3),
            "pitch_correction": round(float(corrections[2]), 3),
        },
        "aircraft": AIRCRAFT_NAMES.get(aircraft_id, aircraft_id),
    }


@app.get("/wind-tunnel")
async def wind_tunnel(
    aircraft_id: str = "x47b",
    aircraft_speed: float = 200,   # Aircraft TAS in m/s (cruise speed)
    wind_speed: float = 0,         # Environmental wind in m/s
    wind_dir: float = 0,           # Wind direction relative to aircraft (0=head, 90=cross)
    pitch: float = 0,              # Aircraft pitch angle in degrees
    yaw: float = 0,                # Aircraft yaw angle in degrees
):
    """
    Serve pre-computed CFD flow field data for the wind tunnel visualization.

    ALL data is pre-computed by the simulation notebook (03_cfd_simulation.ipynb)
    running on the Ray cluster. This endpoint NEVER runs the solver.
    It looks up the nearest matching pre-computed scenario from stored files.

    The UI sliders (aircraft_speed, wind_speed, wind_dir, pitch, yaw) are
    filters that select the closest available pre-computed flow field.
    """
    import glob

    flow_dir = os.path.join(os.path.dirname(__file__), "flow_fields")

    # Try to load pre-computed flow field (nearest match)
    if os.path.exists(flow_dir):
        files = glob.glob(os.path.join(flow_dir, f"{aircraft_id}_*.json"))
        if files:
            # Find closest match by parameter distance
            best_file = None
            best_dist = float('inf')
            for f in files:
                name = os.path.basename(f).replace('.json', '')
                parts = name.split('_')
                try:
                    f_as = float(parts[1].replace('as', ''))
                    f_ws = float(parts[2].replace('ws', ''))
                    f_wd = float(parts[3].replace('wd', ''))
                    dist = abs(f_as - aircraft_speed) + abs(f_ws - wind_speed) + abs(f_wd - wind_dir)
                    if dist < best_dist:
                        best_dist = dist
                        best_file = f
                except (IndexError, ValueError):
                    continue

            if best_file and best_dist < 100:
                import json as json_mod
                with open(best_file) as fh:
                    data = json_mod.load(fh)
                data["source"] = "pre-computed"
                data["file"] = os.path.basename(best_file)
                return data

    # No pre-computed data found for this exact scenario.
    # Return error — ALL data must be pre-computed by the simulation notebook.
    # The model server NEVER runs the solver.
    return {
        "error": f"No pre-computed flow field for aircraft_speed={aircraft_speed}, "
                 f"wind_speed={wind_speed}, wind_dir={wind_dir}. "
                 f"Run 03_cfd_simulation.ipynb on Ray cluster to generate data.",
        "available_files": [f for f in os.listdir(flow_dir)] if os.path.exists(flow_dir) else [],
        "streamlines": [],
        "frames": [],
    }


if __name__ == "__main__":
    import uvicorn
    print("Starting Wind Correction Model Server...")
    print("  Local:  http://localhost:5051")
    print("  Docs:   http://localhost:5051/docs")
    uvicorn.run(app, host="0.0.0.0", port=5051)
