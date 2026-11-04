"""
Domino Model API — Wind Correction Predict Function
=====================================================
This script is deployed as a Domino Model API endpoint.

Domino calls the `predict()` function with the JSON request body.
The function loads the appropriate aircraft model and returns corrections.

Deployment in Domino:
1. Go to Publish → Model APIs → New Model
2. Select this file (model_api.py) and function name: predict
3. Select environment with PyTorch + scikit-learn
4. Ensure model artifacts are in /mnt/artifacts/ or accessible path

Request format:
{
    "data": {
        "aircraft_id": "x47b",
        "speed": 200.0,
        "heading": 45.0,
        "pitch": 2.0,
        "roll": -5.0,
        "vertical_velocity": 0.5,
        "wind_dir": 90.0,
        "wind_speed": 25.0,
        "turbulence": 0.6
    }
}

Response format:
{
    "corrections": {
        "heading_correction": 3.2,
        "throttle_correction": -12.5,
        "pitch_correction": 1.1
    },
    "aircraft": "X-47B UCAV",
    "model_version": "v1"
}
"""

import numpy as np
import torch
import torch.nn as nn
import pickle
import os

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
# LOAD MODELS AT STARTUP (runs once when Domino container starts)
# ============================================================
# Domino places artifacts at /mnt/artifacts/ or the project directory
ARTIFACT_DIR = os.environ.get("DOMINO_ARTIFACTS_DIR", "/mnt/artifacts")
if not os.path.exists(ARTIFACT_DIR):
    ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "models")

AIRCRAFT_NAMES = {
    "x47b": "X-47B UCAV",
    "cessna172": "Cessna 172 Skyhawk",
    "mq9_reaper": "MQ-9 Reaper",
}

models = {}
scalers = {}

for aircraft_id in AIRCRAFT_NAMES:
    model_path = os.path.join(ARTIFACT_DIR, f"wind_correction_{aircraft_id}.pt")
    scaler_path = os.path.join(ARTIFACT_DIR, f"feature_scaler_{aircraft_id}.pkl")

    if os.path.exists(model_path) and os.path.exists(scaler_path):
        model = WindCorrectionNet()
        model.load_state_dict(torch.load(model_path, map_location="cpu"))
        model.eval()
        models[aircraft_id] = model

        with open(scaler_path, "rb") as f:
            scalers[aircraft_id] = pickle.load(f)

        print(f"Loaded model: {aircraft_id}")
    else:
        print(f"Model not found for {aircraft_id}: {model_path}")

print(f"Ready to serve {len(models)} aircraft models")


# ============================================================
# PREDICT FUNCTION — called by Domino for each API request
# ============================================================
def predict(data: dict) -> dict:
    """
    Domino Model API predict function.

    Args:
        data: Dict with aircraft state and wind conditions

    Returns:
        Dict with correction values
    """
    aircraft_id = data.get("aircraft_id", "x47b")

    if aircraft_id not in models:
        return {
            "error": f"No model loaded for aircraft '{aircraft_id}'",
            "available": list(models.keys())
        }

    model = models[aircraft_id]
    scaler = scalers[aircraft_id]

    # Build feature vector (must match training feature order)
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

    # Normalize with the same scaler used during training
    features_scaled = scaler.transform(features)

    # Run inference
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
        "model_version": "v1",
    }
