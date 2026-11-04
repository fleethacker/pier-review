/**
 * Generate a Northrop Grumman X-47B-like flying wing drone as a GLB file.
 * Uses @gltf-transform/core to build the geometry from scratch.
 */
import { Document, NodeIO } from '@gltf-transform/core';

// X-47B approximate dimensions (scaled): wingspan ~19m, length ~11.6m
// We'll model it as a flying wing / blended wing body

function buildX47BGeometry() {
  // All vertices defined to create a flying wing shape
  // The X-47B is a cranked-kite planform with:
  // - Pointed nose
  // - Swept leading edges (~55° inboard, ~30° outboard)
  // - Blended body center section
  // - Trailing edge with sawtooth (simplified)

  const halfSpan = 9.5;   // half wingspan
  const length = 11.6;    // nose to tail
  const bodyHalfWidth = 2.5;
  const bodyHeight = 1.2; // max body thickness
  const wingThickness = 0.15;
  const wingMidThickness = 0.4;

  // Airfoil cross-section helper: returns top/bottom y offsets for a given chord position (0=leading, 1=trailing)
  function airfoilY(t, maxThick) {
    // Simple symmetric airfoil shape
    const x = t;
    return maxThick * (5 * 0.2969 * Math.sqrt(x) - 0.1260 * x - 0.3516 * x * x + 0.2843 * x * x * x - 0.1015 * x * x * x * x);
  }

  const positions = [];
  const indices = [];
  const normals = [];

  // Define cross-sections along the span (from centerline to tip)
  // Each section: { z: spanwise position, xLE: leading edge x, xTE: trailing edge x, thickness: max thickness }
  const sections = [
    { z: 0,              xLE: length,       xTE: 0,            thickness: bodyHeight },
    { z: bodyHalfWidth,  xLE: length * 0.7, xTE: 0.3,         thickness: bodyHeight * 0.9 },
    { z: 4.0,            xLE: length * 0.5, xTE: 1.5,         thickness: wingMidThickness },
    { z: 6.5,            xLE: length * 0.35,xTE: 3.0,         thickness: wingThickness * 1.5 },
    { z: halfSpan,       xLE: length * 0.25,xTE: length*0.2,  thickness: wingThickness },
  ];

  const chordSteps = 12; // points along chord per section

  // Generate vertices for each section
  const sectionVerts = []; // [sectionIndex][chordIndex] = { top: vertIndex, bottom: vertIndex }

  for (const section of sections) {
    const chord = section.xLE - section.xTE;
    const verts = [];

    for (let i = 0; i <= chordSteps; i++) {
      const t = i / chordSteps;
      const x = section.xLE - t * chord; // from LE to TE
      const y = airfoilY(t, section.thickness);

      // Top vertex
      const topIdx = positions.length / 3;
      positions.push(x, y, section.z);
      normals.push(0, 1, 0); // approximate, will be refined

      // Bottom vertex
      const botIdx = positions.length / 3;
      positions.push(x, -y, section.z);
      normals.push(0, -1, 0);

      verts.push({ top: topIdx, bottom: botIdx });
    }
    sectionVerts.push(verts);
  }

  // Also mirror for negative z (other wing half)
  const mirrorSectionVerts = [];
  for (const section of sections) {
    const chord = section.xLE - section.xTE;
    const verts = [];

    for (let i = 0; i <= chordSteps; i++) {
      const t = i / chordSteps;
      const x = section.xLE - t * chord;
      const y = airfoilY(t, section.thickness);

      const topIdx = positions.length / 3;
      positions.push(x, y, -section.z);
      normals.push(0, 1, 0);

      const botIdx = positions.length / 3;
      positions.push(x, -y, -section.z);
      normals.push(0, -1, 0);

      verts.push({ top: topIdx, bottom: botIdx });
    }
    mirrorSectionVerts.push(verts);
  }

  // Connect sections with triangles
  function connectSections(secA, secB) {
    for (let i = 0; i < chordSteps; i++) {
      // Top surface
      indices.push(secA[i].top, secB[i].top, secA[i + 1].top);
      indices.push(secA[i + 1].top, secB[i].top, secB[i + 1].top);

      // Bottom surface
      indices.push(secA[i].bottom, secA[i + 1].bottom, secB[i].bottom);
      indices.push(secA[i + 1].bottom, secB[i + 1].bottom, secB[i].bottom);
    }

    // Leading edge (connect top to bottom at i=0)
    indices.push(secA[0].top, secA[0].bottom, secB[0].top);
    indices.push(secB[0].top, secA[0].bottom, secB[0].bottom);

    // Trailing edge (connect top to bottom at i=chordSteps)
    indices.push(secA[chordSteps].top, secB[chordSteps].top, secA[chordSteps].bottom);
    indices.push(secB[chordSteps].top, secB[chordSteps].bottom, secA[chordSteps].bottom);
  }

  // Connect right wing sections
  for (let s = 0; s < sections.length - 1; s++) {
    connectSections(sectionVerts[s], sectionVerts[s + 1]);
  }

  // Connect left wing sections (mirror)
  for (let s = 0; s < sections.length - 1; s++) {
    connectSections(mirrorSectionVerts[s], mirrorSectionVerts[s + 1]);
  }

  // Connect center sections (z=0 right and z=0 left share the same geometry,
  // but we need to connect them at the centerline)
  // The center sections (index 0) of both halves are at z=0, so they overlap
  // We need to connect them properly - actually they share the same z=0 line
  // Let's just close the wingtip

  // Close wingtip (right)
  const tipR = sectionVerts[sections.length - 1];
  for (let i = 0; i < chordSteps; i++) {
    indices.push(tipR[i].top, tipR[i + 1].top, tipR[i].bottom);
    indices.push(tipR[i + 1].top, tipR[i + 1].bottom, tipR[i].bottom);
  }

  // Close wingtip (left)
  const tipL = mirrorSectionVerts[sections.length - 1];
  for (let i = 0; i < chordSteps; i++) {
    indices.push(tipL[i].top, tipL[i].bottom, tipL[i + 1].top);
    indices.push(tipL[i + 1].top, tipL[i].bottom, tipL[i + 1].bottom);
  }

  // Add intake bump on top (simplified as a raised area on the body)
  const intakeIdx = positions.length / 3;
  // A raised ridge on top of the body
  positions.push(length * 0.6, bodyHeight * 1.3, -1.0); // left
  normals.push(0, 1, 0);
  positions.push(length * 0.6, bodyHeight * 1.3, 1.0);  // right
  normals.push(0, 1, 0);
  positions.push(length * 0.45, bodyHeight * 1.1, -0.8); // left rear
  normals.push(0, 1, 0);
  positions.push(length * 0.45, bodyHeight * 1.1, 0.8);  // right rear
  normals.push(0, 1, 0);
  positions.push(length * 0.7, bodyHeight * 1.0, 0);     // front center
  normals.push(0, 1, 0);

  // Intake triangles
  indices.push(intakeIdx + 4, intakeIdx + 1, intakeIdx);
  indices.push(intakeIdx + 4, intakeIdx, intakeIdx + 2);
  indices.push(intakeIdx + 4, intakeIdx + 3, intakeIdx + 1);
  indices.push(intakeIdx, intakeIdx + 1, intakeIdx + 3);
  indices.push(intakeIdx, intakeIdx + 3, intakeIdx + 2);

  // Add exhaust nozzle area (recessed area at the back)
  const exIdx = positions.length / 3;
  positions.push(0.5, 0.2, -1.2);   normals.push(0, 0, -1);
  positions.push(0.5, 0.2, 1.2);    normals.push(0, 0, 1);
  positions.push(0.5, -0.2, -1.2);  normals.push(0, 0, -1);
  positions.push(0.5, -0.2, 1.2);   normals.push(0, 0, 1);
  positions.push(-0.2, 0, 0);       normals.push(-1, 0, 0);

  indices.push(exIdx + 4, exIdx, exIdx + 1);
  indices.push(exIdx + 4, exIdx + 2, exIdx);
  indices.push(exIdx + 4, exIdx + 1, exIdx + 3);
  indices.push(exIdx + 4, exIdx + 3, exIdx + 2);

  // Recompute normals properly
  const computedNormals = new Float32Array(positions.length);
  for (let i = 0; i < indices.length; i += 3) {
    const ia = indices[i], ib = indices[i + 1], ic = indices[i + 2];
    const ax = positions[ia * 3], ay = positions[ia * 3 + 1], az = positions[ia * 3 + 2];
    const bx = positions[ib * 3], by = positions[ib * 3 + 1], bz = positions[ib * 3 + 2];
    const cx = positions[ic * 3], cy = positions[ic * 3 + 1], cz = positions[ic * 3 + 2];

    const e1x = bx - ax, e1y = by - ay, e1z = bz - az;
    const e2x = cx - ax, e2y = cy - ay, e2z = cz - az;

    const nx = e1y * e2z - e1z * e2y;
    const ny = e1z * e2x - e1x * e2z;
    const nz = e1x * e2y - e1y * e2x;

    computedNormals[ia * 3] += nx; computedNormals[ia * 3 + 1] += ny; computedNormals[ia * 3 + 2] += nz;
    computedNormals[ib * 3] += nx; computedNormals[ib * 3 + 1] += ny; computedNormals[ib * 3 + 2] += nz;
    computedNormals[ic * 3] += nx; computedNormals[ic * 3 + 1] += ny; computedNormals[ic * 3 + 2] += nz;
  }

  // Normalize
  for (let i = 0; i < computedNormals.length; i += 3) {
    const len = Math.sqrt(computedNormals[i] ** 2 + computedNormals[i + 1] ** 2 + computedNormals[i + 2] ** 2);
    if (len > 0) {
      computedNormals[i] /= len;
      computedNormals[i + 1] /= len;
      computedNormals[i + 2] /= len;
    }
  }

  return {
    positions: new Float32Array(positions),
    normals: computedNormals,
    indices: new Uint16Array(indices),
  };
}

async function main() {
  const doc = new Document();
  const buffer = doc.createBuffer();

  const geo = buildX47BGeometry();

  // Create accessors
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

  // Dark grey stealth material
  const material = doc.createMaterial('StealthCoating')
    .setBaseColorFactor([0.15, 0.16, 0.18, 1.0])  // Dark charcoal grey
    .setMetallicFactor(0.7)
    .setRoughnessFactor(0.4)
    .setDoubleSided(true);

  // Create primitive and mesh
  const primitive = doc.createPrimitive()
    .setAttribute('POSITION', positionAccessor)
    .setAttribute('NORMAL', normalAccessor)
    .setIndices(indexAccessor)
    .setMaterial(material);

  const mesh = doc.createMesh('X47B').addPrimitive(primitive);

  // Create node with rotation to align with Cesium's coordinate system
  // The drone should face forward (positive X in Cesium = east)
  const node = doc.createNode('X47B_Root')
    .setMesh(mesh)
    .setRotation([0, 0.7071068, 0, 0.7071068]); // 90° Y rotation so nose points forward

  const scene = doc.createScene().addChild(node);
  doc.getRoot().setDefaultScene(scene);

  // Write GLB
  const io = new NodeIO();
  await io.write('./packages/web/public/x47b.glb', doc);
  console.log('✅ X-47B drone model written to packages/web/public/x47b.glb');

  const vertCount = geo.positions.length / 3;
  const triCount = geo.indices.length / 3;
  console.log(`   Vertices: ${vertCount}, Triangles: ${triCount}`);
}

main().catch(console.error);
