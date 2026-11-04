"""
Mesh Utilities — Aircraft Geometry Extraction & SDF Computation
================================================================
Converts GLB aircraft models into Signed Distance Fields (SDF) for
the Navier-Stokes CFD solver.

Pipeline:
  1. Load GLB via trimesh
  2. Repair mesh (fix normals, winding)
  3. Normalize to [-1, 1] cube
  4. Compute SDF using mesh2sdf (Wang et al., SIGGRAPH 2022)
     - Handles non-watertight meshes via level-set repair
     - Uses fast sweeping method for unsigned distance
     - Extracts and cleans level set for sign determination
  5. Rescale SDF to physical coordinates for the CFD grid

The mesh2sdf library is specifically designed for game/CAD meshes
that are often non-watertight — exactly the case for GLB aircraft
models which typically have open edges at panel joins, engine
intakes, and landing gear bays.

References:
  [1] Wang et al. "Dual Octree Graph Networks" SIGGRAPH 2022
  [2] mesh2sdf: https://github.com/wang-ps/mesh2sdf
"""

import numpy as np
import trimesh
import mesh2sdf
from typing import Tuple
from scipy.ndimage import zoom


def load_aircraft_mesh(glb_path: str, aircraft_profile: dict = None) -> trimesh.Trimesh:
    """
    Load an aircraft GLB model, repair it, and scale to real physical dimensions.

    The target_length is derived from the aircraft profile — specifically
    the 'length' field which gives the real fuselage length in meters.
    This ensures the simulation grid matches real-world dimensions.

    If no profile is provided, the mesh is returned at its raw scale.

    Args:
        glb_path: Path to the .glb file
        aircraft_profile: Dict from aircraft_profiles.py with 'length' key

    Returns:
        Repaired, physically-scaled trimesh.Trimesh object
    """
    scene_or_mesh = trimesh.load(glb_path)

    if isinstance(scene_or_mesh, trimesh.Scene):
        mesh = scene_or_mesh.to_geometry()
    else:
        mesh = scene_or_mesh

    # Repair mesh for CFD use
    trimesh.repair.fix_winding(mesh)
    trimesh.repair.fix_normals(mesh)
    mesh.fill_holes()

    # Center at origin
    mesh.vertices -= mesh.centroid

    # Scale to real physical dimensions from aircraft profile
    if aircraft_profile and 'length' in aircraft_profile:
        real_length = aircraft_profile['length']  # meters
        max_extent = max(mesh.extents)
        scale = real_length / max_extent
        mesh.vertices *= scale
        print(f"  Scaled to real dimensions: {real_length}m (from profile)")
    else:
        print(f"  No profile — using raw mesh dimensions")

    print(f"  Loaded mesh: {len(mesh.vertices):,} vertices, {len(mesh.faces):,} faces")
    print(f"  Extents (m): X={mesh.extents[0]:.2f} Y={mesh.extents[1]:.2f} Z={mesh.extents[2]:.2f}")
    print(f"  Watertight: {mesh.is_watertight}")

    return mesh


def compute_sdf_grid(
    mesh: trimesh.Trimesh,
    grid_dims: Tuple[int, int, int] = (128, 64, 64),
    padding: float = 1.5,
) -> Tuple[np.ndarray, None, float]:
    """
    Compute a Signed Distance Field on a regular 3D grid using mesh2sdf.

    mesh2sdf handles non-watertight meshes through a 4-step process:
    1. Compute unsigned distance via fast sweeping method
    2. Extract level set via marching cubes at small distance d
    3. Select largest connected component (removes artifacts)
    4. Recompute signed distance from the cleaned surface

    This is critical because aircraft GLB models are almost never
    watertight — they have open edges at panel joints, engine intakes,
    and landing gear bays. Traditional inside/outside tests (ray casting,
    normal dot product) fail on these meshes.

    Args:
        mesh: The aircraft mesh (centered, scaled)
        grid_dims: (Nx, Ny, Nz) — resolution of the SDF grid.
                   Higher = better feature resolution.
                   128³ captures wing planform.
                   256³ captures control surfaces.
        padding: Multiple of mesh extent for domain padding

    Returns:
        sdf: np.ndarray of shape grid_dims — signed distance values
             Negative = inside aircraft body
             Positive = fluid domain
        None: (placeholder for grid_coords, not needed with mesh2sdf)
        cell_size: float — spacing between grid cells in meters
    """
    # mesh2sdf requires vertices normalized to [-1, 1] cube
    verts = mesh.vertices.copy().astype(np.float32)
    center = verts.mean(axis=0)
    verts -= center
    max_ext = np.abs(verts).max()
    verts /= max_ext

    # Compute SDF on a cubic grid
    # mesh2sdf always produces a cubic grid of size N³
    cube_size = max(grid_dims)
    level = 2.0 / cube_size  # Level set distance for mesh repair

    print(f"  Computing SDF on {cube_size}³ grid with mesh2sdf (fix=True)...")
    print(f"  Level set distance: {level:.4f}")

    sdf_cube = mesh2sdf.compute(
        verts,
        mesh.faces.astype(np.int32),
        cube_size,
        fix=True,    # Enable non-watertight mesh repair
        level=level,
    )

    # Use cubic grid as-is — do NOT resample to non-cubic dimensions.
    # Resampling squishes the SDF and loses resolution on thin axes.
    sdf = sdf_cube
    # Override grid_dims to match actual cubic shape
    grid_dims = (cube_size, cube_size, cube_size)

    # Compute physical cell size
    # The SDF is in normalized [-1, 1] space
    # Scale factor: 1 unit in SDF space = max_ext meters in physical space
    # Domain extends to padding * max_ext on each side
    physical_extent = max_ext * padding * 2  # Total domain width in meters
    cell_size = physical_extent / max(grid_dims)

    # Scale SDF values from normalized to physical space
    sdf *= max_ext  # Now in meters

    n_inside = np.sum(sdf < 0)
    n_surface = np.sum(np.abs(sdf) < cell_size * 1.5)

    # Domain bounds in meters (centered at origin)
    half_extent = physical_extent / 2
    domain_bounds = {
        "min": [-half_extent, -half_extent, -half_extent],
        "max": [half_extent, half_extent, half_extent],
        "extent": physical_extent,
        "cell_size": cell_size,
        "grid_dims": list(grid_dims),
        "max_ext_meters": float(max_ext),  # Half-size of mesh in meters
    }

    print(f"  SDF computed: {n_inside:,} cells inside mesh "
          f"({n_inside / sdf.size * 100:.1f}%)")
    print(f"  Surface cells: {n_surface:,} ({n_surface / sdf.size * 100:.1f}%)")
    print(f"  Cell size: {cell_size:.4f}m")
    print(f"  Physical domain: [{-half_extent:.1f}, {half_extent:.1f}]m = {physical_extent:.1f}m")

    return sdf, domain_bounds, cell_size
