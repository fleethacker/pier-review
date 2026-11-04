/**
 * Generate a simplified Nimitz-class aircraft carrier as a GLB file.
 * Uses @gltf-transform/core to build the geometry from scratch.
 */
import { Document, NodeIO } from '@gltf-transform/core';

// Nimitz-class approximate dimensions
const HULL_LENGTH = 330;
const HULL_WIDTH = 40;
const HULL_HEIGHT = 12;
const DECK_WIDTH = 75;
const DECK_THICKNESS = 1.5;
const DECK_HEIGHT = 18; // flight deck height above waterline
const ISLAND_LENGTH = 40;
const ISLAND_WIDTH = 15;
const ISLAND_HEIGHT = 20;

function buildCarrierGeometry() {
  const positions = [];
  const normals = [];
  const indices = [];

  let vertexOffset = 0;

  function addBox(cx, cy, cz, sx, sy, sz) {
    const hx = sx / 2, hy = sy / 2, hz = sz / 2;
    const x0 = cx - hx, x1 = cx + hx;
    const y0 = cy - hy, y1 = cy + hy;
    const z0 = cz - hz, z1 = cz + hz;

    // 6 faces, 4 verts each, 2 triangles each
    const faces = [
      // +Y (top)
      { verts: [[x0,y1,z0],[x1,y1,z0],[x1,y1,z1],[x0,y1,z1]], n: [0,1,0] },
      // -Y (bottom)
      { verts: [[x0,y0,z1],[x1,y0,z1],[x1,y0,z0],[x0,y0,z0]], n: [0,-1,0] },
      // +X (front)
      { verts: [[x1,y0,z0],[x1,y0,z1],[x1,y1,z1],[x1,y1,z0]], n: [1,0,0] },
      // -X (back)
      { verts: [[x0,y0,z1],[x0,y0,z0],[x0,y1,z0],[x0,y1,z1]], n: [-1,0,0] },
      // +Z (right)
      { verts: [[x1,y0,z1],[x0,y0,z1],[x0,y1,z1],[x1,y1,z1]], n: [0,0,1] },
      // -Z (left)
      { verts: [[x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0]], n: [0,0,-1] },
    ];

    for (const face of faces) {
      const base = vertexOffset;
      for (const v of face.verts) {
        positions.push(v[0], v[1], v[2]);
        normals.push(face.n[0], face.n[1], face.n[2]);
        vertexOffset++;
      }
      indices.push(base, base+1, base+2);
      indices.push(base, base+2, base+3);
    }
  }

  // Hull — tapered towards bow
  // Main hull body (stern 2/3)
  addBox(
    -HULL_LENGTH * 0.1, DECK_HEIGHT / 2 - HULL_HEIGHT / 2, 0,
    HULL_LENGTH * 0.7, HULL_HEIGHT, HULL_WIDTH
  );

  // Bow taper (front 1/3) — narrower
  addBox(
    HULL_LENGTH * 0.35, DECK_HEIGHT / 2 - HULL_HEIGHT / 2, 0,
    HULL_LENGTH * 0.3, HULL_HEIGHT, HULL_WIDTH * 0.6
  );

  // Flight deck — the big flat surface
  // Main deck (full width)
  addBox(
    0, DECK_HEIGHT, 0,
    HULL_LENGTH, DECK_THICKNESS, DECK_WIDTH
  );

  // Angled deck extension (port side, angled ~9°)
  // Simplified as a box offset to port
  addBox(
    -HULL_LENGTH * 0.05, DECK_HEIGHT, -DECK_WIDTH * 0.3,
    HULL_LENGTH * 0.5, DECK_THICKNESS, DECK_WIDTH * 0.35
  );

  // Island superstructure (starboard side, aft of midship)
  addBox(
    -HULL_LENGTH * 0.05, DECK_HEIGHT + ISLAND_HEIGHT / 2 + DECK_THICKNESS / 2, DECK_WIDTH * 0.3,
    ISLAND_LENGTH, ISLAND_HEIGHT, ISLAND_WIDTH
  );

  // Bridge/tower on top of island
  addBox(
    -HULL_LENGTH * 0.05, DECK_HEIGHT + ISLAND_HEIGHT + 5 + DECK_THICKNESS / 2, DECK_WIDTH * 0.3,
    ISLAND_LENGTH * 0.5, 10, ISLAND_WIDTH * 0.7
  );

  // Mast/antenna on top
  addBox(
    -HULL_LENGTH * 0.05, DECK_HEIGHT + ISLAND_HEIGHT + 15 + DECK_THICKNESS / 2, DECK_WIDTH * 0.3,
    3, 15, 3
  );

  // Catapult tracks on deck (thin raised lines)
  // Cat 1 — bow, centerline
  addBox(HULL_LENGTH * 0.2, DECK_HEIGHT + DECK_THICKNESS, 0, HULL_LENGTH * 0.3, 0.3, 1);
  // Cat 2 — bow, offset port
  addBox(HULL_LENGTH * 0.2, DECK_HEIGHT + DECK_THICKNESS, -8, HULL_LENGTH * 0.3, 0.3, 1);

  // Stern ramp / fantail
  addBox(
    -HULL_LENGTH * 0.48, DECK_HEIGHT - 2, 0,
    HULL_LENGTH * 0.05, 4, HULL_WIDTH * 0.8
  );

  // Elevator platforms (port side)
  addBox(-HULL_LENGTH * 0.15, DECK_HEIGHT, -DECK_WIDTH * 0.48, 20, DECK_THICKNESS, 15);
  addBox(HULL_LENGTH * 0.1, DECK_HEIGHT, -DECK_WIDTH * 0.48, 20, DECK_THICKNESS, 15);

  return {
    positions: new Float32Array(positions),
    normals: new Float32Array(normals),
    indices: new Uint32Array(indices),
  };
}

async function main() {
  const doc = new Document();
  const buffer = doc.createBuffer();

  const geo = buildCarrierGeometry();

  const positionAccessor = doc.createAccessor()
    .setType('VEC3')
    .setArray(geo.positions)
    .setBuffer(buffer);

  const normalAccessor = doc.createAccessor()
    .setType('VEC3')
    .setArray(geo.normals)
    .setBuffer(buffer);

  const indexAccessor = doc.createAccessor()
    .setType('SCALAR')
    .setArray(geo.indices)
    .setBuffer(buffer);

  // Navy haze grey
  const hullMaterial = doc.createMaterial('NavyGrey')
    .setBaseColorFactor([0.55, 0.56, 0.58, 1.0])
    .setMetallicFactor(0.6)
    .setRoughnessFactor(0.5)
    .setDoubleSided(true);

  const primitive = doc.createPrimitive()
    .setAttribute('POSITION', positionAccessor)
    .setAttribute('NORMAL', normalAccessor)
    .setIndices(indexAccessor)
    .setMaterial(hullMaterial);

  const mesh = doc.createMesh('Carrier').addPrimitive(primitive);

  // Rotate so the carrier's long axis aligns with Cesium's forward (X) direction
  const node = doc.createNode('Carrier_Root')
    .setMesh(mesh)
    .setRotation([0, 0.7071068, 0, 0.7071068]); // 90° Y rotation

  const scene = doc.createScene().addChild(node);
  doc.getRoot().setDefaultScene(scene);

  const io = new NodeIO();
  await io.write('./packages/web/public/carrier.glb', doc);
  console.log('✅ Aircraft carrier model written to packages/web/public/carrier.glb');

  const vertCount = geo.positions.length / 3;
  const triCount = geo.indices.length / 3;
  console.log(`   Vertices: ${vertCount}, Triangles: ${triCount}`);
}

main().catch(console.error);
