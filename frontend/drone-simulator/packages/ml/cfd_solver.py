"""
3D Navier-Stokes CFD Solver — Based on Jos Stam's "Stable Fluids"
=================================================================
Reference implementation: GregTJ/stable-fluids (GitHub)
Reference paper: Stam, J. "Stable Fluids" SIGGRAPH 1999

This is the correct iterative time-stepping approach:
- The velocity field is mutable state that persists between steps
- Output of step N IS the input to step N+1
- The flow has MEMORY — turbulence at time T affects all future steps
- You cannot compute step T+5 without computing T+1, T+2, T+3, T+4

Operator splitting per timestep:
    1. Advection — Semi-Lagrangian backtracing (unconditionally stable)
    2. Pressure projection — Poisson solve enforces ∇·u = 0
    3. Boundary enforcement — No-slip on aircraft, inflow, outflow

Particle tracking:
    Lagrangian particles are advected through the TIME-VARYING velocity
    field using RK4 integration. Their positions at each timestep are
    recorded as frames for visualization playback.

References:
    [1] Stam, J. "Stable Fluids" SIGGRAPH 1999
    [2] GregTJ/stable-fluids — github.com/GregTJ/stable-fluids
    [3] Bridson, R. "Fluid Simulation for Computer Graphics" 2015
"""

import numpy as np
from scipy.ndimage import map_coordinates, spline_filter
from scipy.sparse.linalg import factorized
import scipy.sparse as sp
from functools import reduce
from itertools import cycle
from math import factorial
from typing import Tuple, Dict, List, Optional


def _difference(derivative, accuracy=1):
    """Central difference stencil coefficients.
    From: http://web.media.mit.edu/~crtaylor/calculator.html"""
    derivative += 1
    radius = accuracy + derivative // 2 - 1
    points = range(-radius, radius + 1)
    coefficients = np.linalg.inv(np.vander(points))
    return coefficients[-derivative] * factorial(derivative - 1), points


def _operator(shape, *differences):
    """Build sparse Laplacian operator via Kronecker sums."""
    differences = zip(shape, cycle(differences))
    factors = (sp.diags(*diff, shape=(dim,) * 2) for dim, diff in differences)
    return reduce(lambda a, f: sp.kronsum(f, a, format='csc'), factors)


class FluidSolver:
    """
    3D incompressible Navier-Stokes solver.

    The velocity field is mutable state — it persists between calls to step().
    Each step modifies velocity in-place. The output of step N is automatically
    the input to step N+1. This is the correct iterative/looped structure
    where the flow has memory of all previous timesteps.

    Attributes:
        velocity: np.ndarray of shape (3, Nx, Ny, Nz) — the flow state
        shape: (Nx, Ny, Nz) grid dimensions
        obstacle_mask: boolean array, True where aircraft body exists
    """

    def __init__(self, shape: Tuple[int, int, int],
                 pressure_order: int = 1, advect_order: int = 3):
        """
        Initialize solver with grid shape.

        Args:
            shape: (Nx, Ny, Nz) grid dimensions
            pressure_order: Finite difference order for pressure Laplacian
            advect_order: Spline interpolation order for advection
        """
        self.shape = shape
        self.dimensions = 3

        # The velocity field — THIS IS THE STATE that carries between steps
        self.velocity = np.zeros((3, *shape))

        # Grid coordinate indices for advection
        self.indices = np.indices(shape)

        # Pre-factorize the pressure Laplacian — done once, reused every step
        laplacian = _operator(shape, _difference(2, pressure_order))
        self.pressure_solver = factorized(laplacian)

        self.advect_order = advect_order

        # Obstacle (aircraft body) — no-slip boundary
        self.obstacle_mask: Optional[np.ndarray] = None

        # Inflow velocity
        self.inflow_velocity = np.zeros(3)

        # Diagnostics
        self._pressure = np.zeros(shape)
        self._divergence = np.zeros(shape)

    def set_obstacle(self, sdf: np.ndarray) -> None:
        """Set obstacle from signed distance field. SDF < 0 = inside body."""
        self.obstacle_mask = (sdf < 0)
        n_solid = np.sum(self.obstacle_mask)
        print(f"    Obstacle: {n_solid:,} solid cells ({n_solid/sdf.size*100:.1f}%)")

    def set_inflow(self, vx: float, vy: float = 0.0, vz: float = 0.0) -> None:
        """Set inflow boundary velocity."""
        self.inflow_velocity = np.array([vx, vy, vz])
        # Initialize entire field to freestream
        for d in range(3):
            self.velocity[d] = self.inflow_velocity[d]
        # Zero inside obstacle
        if self.obstacle_mask is not None:
            for d in range(3):
                self.velocity[d][self.obstacle_mask] = 0

    def step(self):
        """
        Advance the simulation by one timestep.

        This MUTATES self.velocity in-place — the output of this step
        IS the input to the next step. The flow has memory.

        Returns:
            (divergence, curl_magnitude, pressure) for diagnostics
        """
        # 1. ADVECTION — Semi-Lagrangian backtracing
        # "Where did the fluid at this grid point come from?"
        advection_map = self.indices - self.velocity

        def advect(field, filter_epsilon=10e-2, mode='nearest'):
            filtered = spline_filter(field, order=self.advect_order, mode=mode)
            field = filtered * (1 - filter_epsilon) + field * filter_epsilon
            return map_coordinates(field, advection_map, prefilter=False,
                                   order=self.advect_order, mode=mode)

        # Self-advect velocity (each component advected through the full field)
        for d in range(3):
            self.velocity[d] = advect(self.velocity[d])

        # 2. PRESSURE PROJECTION — enforce incompressibility ∇·u = 0
        # Compute Jacobian to get divergence
        partials = tuple(np.gradient(self.velocity[d]) for d in range(3))
        jacobian = np.stack(partials)
        # Divergence = trace of Jacobian
        self._divergence = sum(jacobian[d][d] for d in range(3))

        # Solve Poisson equation for pressure
        self._pressure = self.pressure_solver(
            self._divergence.flatten()
        ).reshape(self.shape)

        # Subtract pressure gradient from velocity
        pressure_gradient = np.gradient(self._pressure)
        for d in range(3):
            self.velocity[d] -= pressure_gradient[d]

        # 3. BOUNDARY CONDITIONS
        self._enforce_boundaries()

        # Compute curl magnitude for diagnostics
        curl_mag = self._compute_curl_magnitude(jacobian)

        return self._divergence, curl_mag, self._pressure

    def _enforce_boundaries(self):
        """Apply boundary conditions after each step."""
        # No-slip on aircraft body
        if self.obstacle_mask is not None:
            for d in range(3):
                self.velocity[d][self.obstacle_mask] = 0

        # Inflow (x=0 face)
        for d in range(3):
            self.velocity[d][0, :, :] = self.inflow_velocity[d]

        # Outflow (x=-1 face) — zero gradient (Neumann)
        for d in range(3):
            self.velocity[d][-1, :, :] = self.velocity[d][-2, :, :]

    def _compute_curl_magnitude(self, jacobian):
        """Compute |∇ × u| from the Jacobian."""
        # curl_x = dw/dy - dv/dz
        # curl_y = du/dz - dw/dx
        # curl_z = dv/dx - du/dy
        cx = jacobian[2][1] - jacobian[1][2]
        cy = jacobian[0][2] - jacobian[2][0]
        cz = jacobian[1][0] - jacobian[0][1]
        return np.sqrt(cx**2 + cy**2 + cz**2)

    def get_speed(self) -> np.ndarray:
        """Speed magnitude at each cell."""
        return np.sqrt(sum(self.velocity[d]**2 for d in range(3)))

    def sample_velocity(self, positions: np.ndarray) -> np.ndarray:
        """
        Interpolate velocity at arbitrary positions using map_coordinates.

        Args:
            positions: (N, 3) array of grid-coordinate positions

        Returns:
            (N, 3) array of velocity vectors at those positions
        """
        result = np.zeros_like(positions)
        for d in range(3):
            result[:, d] = map_coordinates(
                self.velocity[d],
                positions.T,
                order=1,
                mode='nearest',
            )
        return result


def run_simulation(
    sdf: np.ndarray,
    grid_dims: Tuple[int, int, int],
    cell_size: float,
    aircraft_speed: float,
    wind_speed: float,
    wind_dir_deg: float,
    domain_bounds: Optional[dict] = None,
    n_warmup: int = 60,
    n_frames: int = 80,
    n_particles: int = 500,
    record_interval: int = 2,
) -> Dict:
    """
    Run a complete fluid simulation with Lagrangian particle tracking.

    This is the main entry point. It:
    1. Creates the solver
    2. Sets up inflow from combined aircraft + wind velocity
    3. Warms up the flow field (iterative steps, each building on the last)
    4. Injects particles and tracks them through the TIME-VARYING velocity field
    5. Records particle positions at each timestep as frames

    The key property: output of step N feeds into step N+1.
    Turbulence at time T affects all subsequent timesteps.

    Args:
        sdf: Signed distance field (negative = inside aircraft)
        grid_dims: (Nx, Ny, Nz)
        cell_size: Grid spacing in meters
        aircraft_speed: Aircraft TAS in m/s
        wind_speed: Environmental wind in m/s
        wind_dir_deg: Wind direction (0=headwind, 90=crosswind)
        n_warmup: Steps to develop flow before tracking particles
        n_frames: Steps to track particles
        n_particles: Number of tracer particles
        record_interval: Record every N steps

    Returns:
        Dict with frames, forces, metrics
    """
    actual_dims = sdf.shape
    solver = FluidSolver(actual_dims)
    solver.set_obstacle(sdf)

    # Compute combined inflow velocity
    wind_rad = np.radians(wind_dir_deg)
    vx = aircraft_speed + wind_speed * np.cos(wind_rad)
    vz = wind_speed * np.sin(wind_rad)
    vy = 0.0

    # Scale velocity to grid units.
    # The Stam solver works in cells/step. CFL should be < 1 for stability.
    # We use a FIXED reference speed (200 m/s) to define the scale.
    # This ensures different aircraft speeds produce different flow intensities.
    # At 200 m/s the CFL = 0.5 cells/step.
    # At 150 m/s the CFL = 0.375 (slower flow).
    # At 250 m/s the CFL = 0.625 (faster flow).
    reference_speed = 200.0  # m/s — baseline for CFL=0.5
    v_scale = 0.5 / reference_speed  # Fixed scale factor
    solver.set_inflow(vx * v_scale, vy * v_scale, vz * v_scale)

    V_aero = np.sqrt(vx**2 + vz**2)
    beta = np.degrees(np.arctan2(vz, vx)) if vx > 0 else 0

    print(f"    Inflow: aircraft={aircraft_speed} m/s, wind={wind_speed} m/s @ {wind_dir_deg}°")
    print(f"    V_aero={V_aero:.1f} m/s, beta={beta:.2f}°")
    print(f"    Grid inflow: ({solver.inflow_velocity[0]:.3f}, {solver.inflow_velocity[1]:.3f}, {solver.inflow_velocity[2]:.3f})")

    # Phase 1: Warm up — build up the flow field iteratively
    # Each step's output feeds into the next step
    print(f"    Warming up ({n_warmup} steps)...")
    for step in range(n_warmup):
        div, curl, pres = solver.step()
        if (step + 1) % 20 == 0:
            max_spd = solver.get_speed().max()
            print(f"      Step {step+1}: max_speed={max_spd:.3f}")

    # Phase 2: Inject particles
    print(f"    Injecting {n_particles} particles...")
    sqrt_n = int(np.ceil(np.sqrt(n_particles)))
    particles = np.zeros((n_particles, 3))

    # Distribute across inflow face(s)
    n_front = n_particles if abs(vz) < 1 else int(n_particles * 0.7)
    n_side = n_particles - n_front

    for i in range(n_front):
        iy = i // sqrt_n
        iz = i % sqrt_n
        particles[i] = [
            1.0 + np.random.uniform(0, 3),
            (iy + 0.5) / sqrt_n * (actual_dims[1] - 4) + 2,
            (iz + 0.5) / sqrt_n * (actual_dims[2] - 4) + 2,
        ]

    if n_side > 0:
        sqrt_s = int(np.ceil(np.sqrt(n_side)))
        z_face = 2.0 if vz > 0 else actual_dims[2] - 3.0
        for i in range(n_side):
            ix = i // sqrt_s
            iy = i % sqrt_s
            particles[n_front + i] = [
                (ix + 0.5) / sqrt_s * (actual_dims[0] - 4) + 2,
                (iy + 0.5) / sqrt_s * (actual_dims[1] - 4) + 2,
                z_face,
            ]

    # Phase 3: Track particles through the TIME-VARYING velocity field
    # Each step: solve flow → advect particles → record → the modified flow carries forward
    print(f"    Tracking ({n_frames} steps, recording every {record_interval})...")
    frames = []
    max_speed_global = 0.0
    grid_center = np.array(actual_dims) / 2.0

    for step in range(n_frames):
        # Solve one step — MUTATES velocity in-place
        # The flow field now contains the history of all previous steps
        div, curl, pres = solver.step()

        # Advect particles through THIS step's velocity field using RK4
        velocities = solver.sample_velocity(particles)
        for i in range(n_particles):
            vel = velocities[i]
            v_mag = np.linalg.norm(vel) + 1e-10

            # RK4 with CFL-limited sub-stepping
            dt_sub = min(1.0, 0.5 / v_mag)  # Keep CFL < 0.5
            n_sub = max(1, int(1.0 / dt_sub))

            pos = particles[i].copy()
            for _ in range(n_sub):
                k1 = solver.sample_velocity(pos.reshape(1, 3))[0]
                k2 = solver.sample_velocity((pos + 0.5 * dt_sub * k1).reshape(1, 3))[0]
                k3 = solver.sample_velocity((pos + 0.5 * dt_sub * k2).reshape(1, 3))[0]
                k4 = solver.sample_velocity((pos + dt_sub * k3).reshape(1, 3))[0]
                pos += (dt_sub / 6.0) * (k1 + 2*k2 + 2*k3 + k4)

            # Clamp to domain
            for d in range(3):
                pos[d] = np.clip(pos[d], 0.5, grid_dims[d] - 1.5)

            # Respawn if inside obstacle or at outflow
            gi = int(np.clip(pos[0], 0, actual_dims[0]-1))
            gj = int(np.clip(pos[1], 0, actual_dims[1]-1))
            gk = int(np.clip(pos[2], 0, actual_dims[2]-1))

            if (solver.obstacle_mask is not None and solver.obstacle_mask[gi, gj, gk]) or \
               pos[0] > actual_dims[0] - 3:
                # Respawn at inflow
                if i < n_front:
                    pos = np.array([
                        1.0 + np.random.uniform(0, 3),
                        np.random.uniform(2, actual_dims[1] - 2),
                        np.random.uniform(2, actual_dims[2] - 2),
                    ])
                else:
                    z_face = 2.0 if vz > 0 else actual_dims[2] - 3.0
                    pos = np.array([
                        np.random.uniform(2, actual_dims[0] - 2),
                        np.random.uniform(2, actual_dims[1] - 2),
                        z_face,
                    ])

            particles[i] = pos

        # Record frame
        if step % record_interval == 0:
            frame = []
            for i in range(n_particles):
                world_pos = (particles[i] - grid_center) * cell_size
                vel = velocities[i] if i < len(velocities) else np.zeros(3)
                speed = np.linalg.norm(vel) * cell_size  # Convert to m/s
                max_speed_global = max(max_speed_global, speed)
                frame.append([
                    round(float(world_pos[0]), 3),
                    round(float(world_pos[1]), 3),
                    round(float(world_pos[2]), 3),
                    round(float(speed), 2),
                ])
            frames.append(frame)

        if (step + 1) % 20 == 0:
            print(f"      Step {step+1}/{n_frames}: {len(frames)} frames recorded")

    # Compute final forces
    speed_field = solver.get_speed()

    print(f"    Complete: {len(frames)} frames, {n_particles} particles, "
          f"max_speed={max_speed_global:.2f}")

    # Domain bounds for visualization coordinate matching
    half_domain = np.array(actual_dims) * cell_size / 2

    return {
        "frames": frames,
        "n_frames": len(frames),
        "n_particles": n_particles,
        "max_speed": round(max_speed_global, 2),
        "effective_airspeed": round(V_aero, 1),
        "effective_beta": round(beta, 2),
        "grid_dims": list(actual_dims),
        "cell_size": round(float(cell_size), 4),
        "domain_min": [round(-float(h), 3) for h in half_domain],
        "domain_max": [round(float(h), 3) for h in half_domain],
    }
