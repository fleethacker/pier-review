"""S1: rm0-v1 scene and rich frames from actual BerthingModel state.

Interface contract shared by the session protocol (sim_sessions.py / ws.py) and this module.
Pure functions: they read model state and never advance, mutate or reschedule the simulation.

Rules (docs/MOTION_FRAME_DESIGN.md, docs/MASTER_PLAN.md S1):
- Every value comes from the simulator's current state or the immutable scenario inputs.
  Anything not modeled is null with availability "unavailable"/"not_simulated", never zero.
- Provenance kind is "estimated" (real integrator, synthetic unqualified body, seed catalog data);
  never "qualified". Component and frame validity are "limited" (or "invalid" when the model is).
- Surge, sway, yaw are "simulated". Heave, roll, pitch are "not_simulated" (S3 adds heave).
- Tug kinematics are not modeled: tug position/velocity/acceleration stay null; forces, push point,
  contact position, mode and utilization come from the active ramp and push-point assignment.
- Waves: all four components unavailable (not a zero-wave claim), in environment and forces.
- Berth axes for positions and forces; ship-local axes for scene hull outline and ship fittings.
  Yaw moments are about the instantaneous ship reference point, +counterclockwise.
"""

from mooring.core.schemas import SimFrame, SimScene

SCHEMA_VERSION = "rm0-v1"


def scene_id_for(model) -> tuple[str, str]:
    """Deterministic (scene_id, revision) from the scene content hash; same inputs give the same id."""
    raise NotImplementedError


def build_scene(model) -> SimScene:
    """Static scene for this model: berth outline/deck/fittings/fenders/depth, ship hull outline/fittings."""
    raise NotImplementedError


def rich_frame(model, *, session_id: str, run_id: str, sequence: int, scene: SimScene,
               state=None, t: float | None = None, alerts: list[str] | None = None) -> SimFrame:
    """Legacy frame (model.frame) plus every rm0-v1 field, at `state`/`t` (defaults: current)."""
    raise NotImplementedError
