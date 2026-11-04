# X-47B UCAV Drone Operations Platform

**Domino Data Lab Demo** — A single integrated solution demonstrating three pillars of enterprise AI:

1. **Ray Cluster (HPC)** — Distributed Navier-Stokes CFD simulation across 30+ nodes, generating millions of flight scenarios for ML training
2. **Traditional ML** — Per-aircraft neural networks trained on simulation data for real-time wind correction, tracked via MLflow, deployed through Domino Model Registry
3. **Generative AI** — OpenAI GPT produces human-readable intelligence reports from YOLO ISR detection results with location-aware threat assessment

Built as a military-grade drone flight simulator with real-time ISR, mission planning, AI autopilot, and CFD wind tunnel analysis for Navy operational demonstration.

## How It Demonstrates Domino Capabilities

| Domino Capability | Implementation in This Demo |
|---|---|
| **Ray Cluster (HPC)** | 3D Navier-Stokes CFD simulation distributed across cluster nodes. Each wind condition × aircraft angle × speed combination is an independent Ray task. 15,000+ simulations per aircraft type. Scales linearly with cluster size. |
| **Traditional ML** | PyTorch neural networks trained on simulation data to predict optimal flight corrections. One model per aircraft (different aerodynamics = different models). Tracked in MLflow with hyperparameters, metrics, artifacts. Deployed via Domino Model Registry. |
| **Generative AI** | OpenAI GPT analyzes YOLO detection results with geographic context to produce operational intelligence reports. Includes threat level assessment, area characterization, and actionable recommendations. |
| **MLflow Integration** | Per-aircraft experiments, model versioning, artifact logging, model registry with stage transitions |
| **Model Serving** | Domino Model APIs via `model_api.py` predict function. FastAPI for local development. |
| **Domino Apps** | Flight simulator hosted as a Domino App — full interactive web application accessible to stakeholders without local setup |
| **Reproducibility** | Jupyter notebooks with documented pipelines, parquet data storage, version-controlled configs |

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Domino Data Lab Platform                      │
│                                                                 │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ Ray Cluster  │  │ MLflow       │  │ Model Registry         │ │
│  │ (HPC)        │  │ Tracking     │  │ (Model APIs)           │ │
│  │              │  │              │  │                        │ │
│  │ CFD Solver   │  │ Experiments  │  │ wind-correction-x47b   │ │
│  │ Wind Sims    │  │ Metrics      │  │ wind-correction-cessna │ │
│  │ Particle     │  │ Artifacts    │  │ wind-correction-mq9    │ │
│  │ Tracking     │  │ Comparisons  │  │                        │ │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬────────────┘ │
│         │                 │                      │              │
│         ▼                 ▼                      ▼              │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │              Training Data (Parquet)                   │ │
│  │         Simulation Results → ML Features → Models           │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────┬───────────────────────────────────────┘
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
     ┌────────────┐ ┌──────────┐ ┌───────────┐
     │ YOLO ISR   │ │ ML Wind  │ │ CFD Wind  │
     │ + OpenAI   │ │ Correct  │ │ Tunnel    │
     │ (port 5050)│ │ (port    │ │ Data      │
     │            │ │  5051)   │ │ (files)   │
     └─────┬──────┘ └────┬─────┘ └─────┬─────┘
            │             │             │
            └─────────────┼─────────────┘
                          ▼
              ┌───────────────────────┐
              │  Flight Simulator UI  │
              │  (Cesium + React)     │
              │  http://localhost:4000 │
              └───────────────────────┘
```

## Core Capabilities

### Flight Simulation
- **X-47B UCAV** with full 6-DOF physics (speed, heading, pitch, roll, altitude, collision detection)
- **Google Photorealistic 3D Tiles** via Cesium for real-world terrain at global scale
- **Military tactical UI** with telemetry bar, heading compass tape, targeting reticle, status bar
- **Terrain collision detection** with configurable grace periods
- **Wind physics** applied to flight dynamics with configurable direction, speed, and turbulence

### ISR (Intelligence, Surveillance, Reconnaissance)

**YOLO (You Only Look Once)** is a real-time object detection neural network that processes an entire image in a single forward pass, outputting bounding boxes and class probabilities simultaneously. Unlike two-stage detectors (R-CNN), YOLO treats detection as a regression problem — dividing the image into a grid and predicting boxes + classes for each cell in one shot.

**Model**: We use **YOLOv8m-OBB** (medium, Oriented Bounding Box) from Ultralytics, specifically trained on the **DOTA (Dataset for Object Detection in Aerial Images)** dataset. The OBB variant outputs rotated bounding boxes rather than axis-aligned ones — critical for aerial imagery where objects like vehicles, ships, and runways appear at arbitrary angles from overhead.

**DOTA Classes** (15): plane, ship, storage tank, baseball diamond, tennis court, basketball court, ground track field, harbor, bridge, large vehicle, small vehicle, helicopter, roundabout, soccer ball field, swimming pool

**Model Sizes Available** (accuracy vs speed tradeoff):

| Model | Params | mAP50 | Use Case |
|-------|--------|-------|----------|
| YOLOv8n-OBB | ~3M | 78.0 | Fast, low accuracy |
| YOLOv8s-OBB | ~11M | 79.5 | Good balance |
| **YOLOv8m-OBB** | **~26M** | **80.5** | **Currently used** |
| YOLOv8l-OBB | ~44M | 80.7 | Higher accuracy |
| YOLOv8x-OBB | ~68M | 81.0 | Maximum accuracy, slower |

Upgrade path: swap `yolov8m-obb.pt` → `yolov8x-obb.pt` in `main.py` for +0.5 mAP at 2.5x inference cost.

**Per-Class Confidence Thresholds**: Not all detections are equally reliable from aerial imagery. We apply class-specific minimum confidence scores:

| Class Group | Threshold | Reason |
|---|---|---|
| `small vehicle`, `large vehicle` | 5% | Vehicles are the primary detection target; low threshold catches all |
| Everything else (ship, helicopter, plane, harbor, swimming pool, baseball diamond, etc.) | 70% | These classes produce frequent false positives from aerial textures; high threshold reduces noise |

**Geographic Deduplication**: When the drone scans overlapping areas, the same vehicle may be detected in multiple passes. We deduplicate by:
1. Converting each detection's bounding box center from image pixels to approximate world lat/lon using the scan's center coordinates and Mapbox zoom level
2. For each new detection, checking if an object of the same class exists within ~30m (0.0003° in lat/lon) in the accumulated results
3. If a match is found, it's counted as the same object; otherwise it's a new unique target

This produces a **unique object count** displayed in the ISR Tracking panel, separate from the raw detection count.

**Satellite Imagery**: Fetched from Mapbox Static Images API (`satellite-v9` style) at the drone's current position. The image is:
- Zoomed based on drone altitude above ground (computed via Cesium `clampToHeight`)
- Rotated to match the drone's heading (bearing parameter in the Mapbox URL)
- Offset slightly forward in the direction of travel to show what's ahead

**GenAI Intel Analysis**: After an ISR mission or free-flight session, all detection data is sent to OpenAI GPT with:
- Per-waypoint/scan detection summaries (e.g., "WP-03: 5 small vehicle, 1 large vehicle")
- Geographic location from Mapbox reverse geocoding (e.g., "Tehran, Iran")
- Prompt requesting operational intelligence format with threat level and recommendations
- Response: structured JSON with `summary`, `threat_level` (low/medium/high), `recommendations[]`

### Mission Planning & Execution
- **Waypoint placement** with WASD cursor, green route lines, military-themed labels (WP-01, WP-02, etc.)
- **5 AI flight profiles**: NOE (terrain-hugging), Stealth (low & slow), Recon (standard ISR), High Altitude (max safety), Fast Transit (600 km/h)
- **Autopilot** with Heun RK2 integration, pulse-and-coast steering, CFL-limited advection
- **ISR auto-scan** at each waypoint with YOLO detection logging
- **Mission summary** with per-waypoint intel breakdown and AI-generated analysis
- **Free-flight ISR tracking** accumulates detections during manual flight with VIEW INTEL REPORT anytime

### ML Wind Correction Pipeline
- **Ray cluster simulation** generates training data across wind parameter grid (direction, speed, turbulence, aircraft heading)
- **Per-aircraft neural networks** (X-47B, Cessna 172, MQ-9 Reaper) learn optimal corrections
- **Proper aerodynamic decomposition**: V_aero = V_aircraft + V_wind, effective alpha/beta computation
- **Stability derivative force model**: C_L_alpha, C_Y_beta, C_m_alpha, C_n_beta for realistic perturbations
- **MLflow experiment tracking** with per-aircraft model registry for Domino Data Lab deployment
- **Dual deployment**: Domino Model API (production) + local FastAPI (development)

### CFD Wind Tunnel
- **3D Navier-Stokes solver** based on Jos Stam's Stable Fluids (SIGGRAPH 1999)
- **mesh2sdf** for non-watertight GLB mesh → signed distance field conversion
- **Lagrangian particle tracking** with RK4 integration through time-varying velocity field
- **Three.js visualization** with the actual X-47B GLB model, velocity-colored particles, orbital camera
- **Pre-computed on Ray cluster** — app serves stored flow fields instantly, never computes on demand
- **Physical coordinate alignment** between simulation grid and visualization model

## Project Structure

```
packages/
├── web/                          # Frontend (Vite + React + TypeScript + Cesium)
│   ├── src/
│   │   ├── cesium/               # 3D engine
│   │   │   ├── vehicles/         # Aircraft physics, AutoPilot, WindSystem
│   │   │   ├── bridge/           # GameBridge (Cesium ↔ React events/methods)
│   │   │   ├── physics/          # WindSystem
│   │   │   ├── builder/          # Mission planning cursor, ObjectManager
│   │   │   └── objects/          # Waypoint entities
│   │   └── react/
│   │       ├── features/
│   │       │   ├── hud/          # TelemetryBar, StatusBar, Reticle
│   │       │   ├── detection/    # ISR panel, YOLO detection hook
│   │       │   ├── mission/      # MissionStatusPanel, MissionSummary, MissionTracker
│   │       │   ├── minimap/      # Mapbox navigation map
│   │       │   ├── tracking/     # Flight path recording
│   │       │   ├── wind/         # Wind control panel
│   │       │   ├── windtunnel/   # CFD wind tunnel 3D visualization
│   │       │   └── builder/      # Mission planning HUD
│   │       └── layouts/          # PlayModeUI, BuilderModeUI
│   └── public/
│       └── x47b.glb              # X-47B UCAV 3D model
│
├── python-yolo/                  # YOLO + OpenAI service (FastAPI, port 5050)
│   ├── main.py                   # /detect (YOLO), /analyze (OpenAI), /health
│   └── requirements.txt
│
└── ml/                           # ML pipeline
    ├── aircraft_profiles.py      # X-47B, Cessna 172, MQ-9 Reaper specs
    ├── cfd_solver.py             # 3D Navier-Stokes (Stam Stable Fluids)
    ├── mesh_utils.py             # GLB → SDF via mesh2sdf
    ├── aero_forces.py            # Stability derivative force model
    ├── model_server.py           # ML inference + wind tunnel data (FastAPI, port 5051)
    ├── model_api.py              # Domino Model API predict function
    ├── 01_simulation.ipynb       # Ray wind simulation pipeline
    ├── 02_training.ipynb         # ML training with MLflow
    ├── flow_fields/              # Pre-computed CFD data (JSON)
    ├── models/                   # Trained PyTorch models + scalers
    └── data/                     # Simulation parquet files
```

## Quick Start

### Prerequisites
- Node.js 18+
- Python 3.9+
- API tokens: Mapbox, Cesium Ion, OpenAI

### Setup

```bash
# Clone
git clone <repo-url>
cd drone-simulator

# Environment variables
cat > .env << EOF
VITE_MAPBOX_TOKEN=your_mapbox_token
VITE_CESIUM_TOKEN=your_cesium_token
OPENAI_API_KEY=your_openai_key
EOF

# Frontend
cd packages/web && npm install

# YOLO service
cd ../python-yolo && python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# ML service
cd ../ml && python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Run

```bash
# Terminal 1: Frontend (port 4000)
cd packages/web && npx vite --port 4000

# Terminal 2: YOLO + OpenAI service (port 5050)
cd packages/python-yolo && source venv/bin/activate && python main.py

# Terminal 3: ML model server (port 5051)
cd packages/ml && source venv/bin/activate && python model_server.py
```

Open http://localhost:4000

### Generate ML Training Data

```bash
cd packages/ml && source venv/bin/activate

# Run simulation on Ray (single node locally, cluster in production)
jupyter notebook 01_simulation.ipynb

# Train ML models with MLflow tracking
jupyter notebook 02_training.ipynb
```

## Controls

| Key | Action |
|-----|--------|
| W / S | Throttle / Brake |
| A / D / Arrow Keys | Roll / Turn |
| Arrow Up / Down | Climb / Descend |
| B | Mission Planning mode |
| Space | Place waypoint (in mission planning) |
| Enter | Execute mission (in mission planning) |
| R | Restart after crash |
| ~ | Calibration panel (wind, quality, collision) |
| ? | Controls reference |

## API Endpoints

### YOLO Service (port 5050)
- `POST /detect` — Run YOLOv8m-OBB on uploaded image
- `POST /analyze` — Generate GPT intel report from detection data
- `GET /health` — Health check

### ML Service (port 5051)
- `POST /wind-correct` — Get ML wind corrections for aircraft state
- `GET /wind-tunnel` — Serve pre-computed CFD flow field data
- `GET /models` — List loaded ML models
- `GET /health` — Health check

## Technology Stack

| Component | Technology |
|-----------|-----------|
| 3D Engine | Cesium + Google Photorealistic 3D Tiles |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS |
| Maps | Mapbox GL JS, react-map-gl |
| 3D Viz | Three.js (wind tunnel) |
| Object Detection | YOLOv8m-OBB (ultralytics) |
| Intel Analysis | OpenAI GPT |
| ML Training | PyTorch, scikit-learn |
| Experiment Tracking | MLflow |
| Distributed Compute | Ray |
| CFD Solver | Stam Stable Fluids + mesh2sdf + pyvista |
| API Layer | FastAPI + uvicorn |
| Model Deployment | Domino Data Lab Model Registry |
| Data Storage | Parquet (Arrow), JSON |
| App Hosting | Domino Apps |

## Scientific Approach

### Why This Architecture Is Correct

The system solves a real problem in UAV operations: **wind disturbance rejection**. When a drone flies through wind, the aerodynamic forces deviate from the trim (no-wind) condition. A correction model must predict the right control inputs to counteract these deviations in real time.

The challenge: each aircraft has fundamentally different aerodynamic properties (mass, drag, wing loading, cross-sectional area). A correction model trained on an X-47B (20,215 kg stealth UCAV) will not work for a Cessna 172 (1,111 kg general aviation aircraft). The heavier X-47B is more stable in gusts but slower to respond to corrections. The lighter Cessna is blown around easily but corrects quickly.

This is why the Ray cluster is essential — we need to simulate and train **separate models per aircraft type** across a comprehensive parameter space.

### Simulation Pipeline (Ray Cluster)

**Goal**: Generate training data that captures how each aircraft responds to wind across all possible conditions.

**Aerodynamic Decomposition**:
The relative (aerodynamic) velocity seen by the aircraft is the vector sum of its own forward motion and the environmental wind:

```
V_aero = V_aircraft + V_wind

Effective angle of attack:    α = arctan(V_vertical_gust / V_forward)
Effective sideslip angle:     β = arctan(V_crosswind / V_forward)
Dynamic pressure:             q = ½ρV²_aero
```

**Force Perturbation Model** (stability derivatives per standard flight mechanics):

```
ΔLift      = C_L_α · Δα · q · S          (vertical gust → lift change)
ΔSide      = C_Y_β · β  · q · S          (crosswind → lateral force)
ΔPitch Mom = C_m_α · Δα · q · S · c̄      (gust → pitching moment)
ΔYaw Mom   = C_n_β · β  · q · S · b      (crosswind → yawing moment)
```

Where S = wing area, b = wingspan, c̄ = mean aerodynamic chord. These coefficients differ per aircraft — derived from the aircraft profiles in `aircraft_profiles.py`.

**Parameter Grid**:
- Wind direction: 8 values (0°, 45°, 90°, 135°, 180°, 225°, 270°, 315°)
- Wind speed: 8 values (0, 5, 10, 15, 20, 30, 40, 50 m/s)
- Turbulence: 6 levels (0.0 to 1.0)
- Aircraft heading: 8 values (0° through 315°)
- Random seeds: 5 per combination
- = **15,360 simulations per aircraft** × 3 aircraft = 46,080 total

Each simulation runs for 60 seconds at 0.1s timesteps = 600 data points per simulation.
Total dataset: ~27.6 million rows.

**Why heading × wind angle matters**: A drone flying North in a 90° crosswind experiences identical forces to one flying East in a 180° wind. But the ML model receives absolute heading and absolute wind direction as inputs, so it must learn from all combinations to generalize.

**Ray Distribution**: Each simulation is a pure function with no shared state — ideal for `@ray.remote`. On a 30-node cluster, all 46,080 simulations run in parallel batches. Single-node timing: ~4 hours. 30-node cluster: ~8 minutes.

### ML Training

**Architecture**: Per-aircraft feedforward network

```
Input (9 features)                    Output (3 corrections)
─────────────────                     ──────────────────────
speed                                 heading_correction  (±15°)
heading                               throttle_correction (±50 km/h)
pitch              → [128] → [64] →  pitch_correction    (±10°)
roll                  ReLU    ReLU
vertical_velocity     Drop    Drop
wind_dir_sin                [32]
wind_dir_cos           ReLU → Tanh → Scale
wind_speed             Drop
turbulence
```

**Why Tanh output**: The Tanh activation naturally bounds corrections to [-1, 1], which is then scaled to the physical correction ranges. This prevents the model from producing dangerously large corrections.

**Why per-aircraft**: The same 30 m/s crosswind produces:
- X-47B (20,215 kg): β=8.5°, side force ~257 kN, heading correction needed: -4.3°
- Cessna 172 (1,111 kg): same β, but 3.4× more heading deviation due to lower mass and higher wind sensitivity

A single model cannot learn both — the correction magnitudes are fundamentally different.

**Training targets**: The optimal corrections are computed from the stability derivative force model — they represent the control inputs that would counteract the wind-induced perturbation and return the aircraft to its desired trajectory.

**MLflow Tracking**: Each aircraft gets its own MLflow experiment (`drone-wind-correction-x47b`, etc.) with:
- Tags: aircraft_id, mass, wingspan, drag coefficient
- Params: learning rate, batch size, epochs, architecture
- Metrics: per-epoch train/val loss, per-axis MAE
- Artifacts: PyTorch model (.pt), feature scaler (.pkl)
- Model registered in MLflow Model Registry for Domino deployment

### CFD Wind Tunnel Simulation

**Purpose**: Visualize the actual fluid dynamics around the aircraft body under various wind conditions. This uses the same physics that generates the ML training data — the CFD solver computes the flow field, and the results are both visualized and used to validate the force model.

**Solver**: 3D incompressible Navier-Stokes based on Jos Stam's "Stable Fluids" (SIGGRAPH 1999).

The solver is an iterative time-stepping system where **the output of each step is the input to the next step**. The velocity field carries the history of all previous timesteps — turbulence at time T affects all subsequent flow. This is implemented following the reference implementation from GregTJ/stable-fluids.

**Operator splitting per timestep**:
1. **Advection** (Semi-Lagrangian): For each grid cell, trace backward along the velocity field and interpolate the source value. Uses `scipy.ndimage.map_coordinates` with spline filtering. Unconditionally stable for any CFL number.
2. **Pressure Projection**: Compute divergence of velocity, solve Poisson equation via pre-factorized sparse Laplacian (`scipy.sparse.linalg.factorized`), subtract pressure gradient. Enforces incompressibility (∇·u = 0).
3. **Boundary Conditions**: No-slip on aircraft surface (velocity = 0 where SDF < 0), Dirichlet inflow, Neumann outflow.

**Mesh Integration**:
- Aircraft GLB model loaded via `trimesh`
- Mesh repaired (normals, winding, holes) for CFD use
- Signed Distance Field computed via `mesh2sdf` (Wang et al., SIGGRAPH 2022) — handles non-watertight game meshes through level-set extraction and component cleaning
- SDF defines the solid boundary in the solver grid

**Inflow Conditions** (consistent with the ML force model):

```
V_inflow = V_aircraft + V_wind_headwind    (x-component)
V_lateral = V_wind_crosswind               (z-component)
```

At wind=0, the aircraft still sees airflow from its own forward motion. Adding crosswind creates effective sideslip angle β, producing asymmetric flow around the body.

**Particle Tracking**: Lagrangian tracer particles injected at inflow faces, advected through the time-varying velocity field using 4th-order Runge-Kutta with CFL-limited sub-stepping. Particles that exit the domain or enter the obstacle are respawned at the inflow face corresponding to their origin (front face for forward motion, side face for crosswind).

**Pre-computation**: All flow fields are computed in advance on the Ray cluster. The web application never runs the solver — it serves stored results instantly. Each scenario is a Ray task.

**Physical Coordinate System**: The simulation grid, particle positions, and GLB model all share the same coordinate system in meters, centered at the aircraft origin. The aircraft is scaled to its real physical dimensions from the aircraft profile (e.g., X-47B: 11.63m fuselage length). This ensures the visualization accurately represents the spatial relationship between the flow field and the aircraft geometry.

### Data Flow: Simulation → Training → Deployment

```
1. Aircraft GLB model
   ↓ (trimesh + mesh2sdf)
2. Signed Distance Field (SDF) on 3D grid
   ↓
3. Navier-Stokes solver computes flow fields     ← Ray cluster
   ↓                                                (distributed)
4. Aerodynamic forces extracted (lift, drag, side)
   ↓
5. Force model generates training targets         ← aero_forces.py
   (state + wind → optimal correction)
   ↓
6. Flight trajectory simulation with force        ← 01_simulation.ipynb
   perturbations across parameter grid               (Ray distributed)
   ↓
7. Training data: 27.6M rows in Parquet
   ↓
8. Per-aircraft ML model training                 ← 02_training.ipynb
   with MLflow tracking                              (MLflow + PyTorch)
   ↓
9. Model deployment                               ← Domino Model Registry
   ↓
10. Real-time wind correction in flight sim       ← model_server.py
    + wind tunnel visualization                      (FastAPI)
```

## Deployment

### Local Development
All three services run locally on separate ports (4000, 5050, 5051). Ray initializes in single-node mode using all available CPU cores.

### Production (Domino Data Lab)
- **Domino Apps**: Flight simulator hosted as interactive web application
- **Ray Cluster**: 30+ node cluster for simulation at scale (`ray.init(address="auto")`)
- **MLflow**: Experiment tracking and model registry integrated with Domino
- **Model APIs**: Wind correction models deployed via Domino Model Registry using `model_api.py`
- **Pre-computed Data**: CFD flow fields generated on cluster, stored in Domino project files

## License

MIT
