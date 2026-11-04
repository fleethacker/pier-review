import { useState, useRef, useEffect, useCallback } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

interface FlowData {
  streamlines: number[][][];  // Steady-state reference lines
  frames: number[][][];       // Lagrangian particle frames: [n_frames][n_particles][7: x,y,z,vx,vy,vz,speed]
  forces: { drag: number[]; lift: number[] };
  forces_per_frame: { drag: number[]; lift: number[] }[];
  max_speed: number;
  max_vorticity: number;
  n_streamlines: number;
  n_frames: number;
  n_particles: number;
  total_points: number;
}

export function WindTunnelPage({ onClose }: { onClose: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [aircraftSpeed, setAircraftSpeed] = useState(200);
  const [windSpeed, setWindSpeed] = useState(0);
  const [windDir, setWindDir] = useState(0);
  const [pitch, setPitch] = useState(0);
  const [yaw, setYaw] = useState(0);
  const [roll, setRoll] = useState(0);
  const [aircraft, setAircraft] = useState('x47b');
  const [status, setStatus] = useState('INITIALIZING...');
  const [flowData, setFlowData] = useState<FlowData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [currentFrame, setCurrentFrame] = useState(0);
  const [currentForces, setCurrentForces] = useState<{ drag: number[]; lift: number[] } | null>(null);

  const sceneRef = useRef<THREE.Scene | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const droneRef = useRef<THREE.Group | null>(null);
  const streamlinesGroupRef = useRef<THREE.Group | null>(null);
  const forceArrowsRef = useRef<THREE.Group | null>(null);
  const particlesRef = useRef<THREE.Points | null>(null);
  const flowDataRef = useRef<FlowData | null>(null);
  const frameCounterRef = useRef(0);
  const animRef = useRef<number>(0);
  const pitchRef = useRef(0);
  const yawRef = useRef(0);
  const rollRef = useRef(0);
  const windDirRef = useRef(0);
  pitchRef.current = pitch;
  yawRef.current = yaw;
  rollRef.current = roll;
  windDirRef.current = windDir;

  // Fetch real CFD data from the solver
  const fetchFlowField = useCallback(async () => {
    setIsLoading(true);
    setStatus('LOADING FLOW FIELD DATA...');
    try {
      const res = await fetch(
        `/api/wind-tunnel?aircraft_id=${aircraft}&aircraft_speed=${aircraftSpeed}&wind_speed=${windSpeed}&wind_dir=${windDir}&pitch=${pitch}&yaw=${yaw}`
      );
      const data = await res.json();
      if (data.error) {
        setStatus(`ERROR: ${data.error}`);
        setIsLoading(false);
        return;
      }
      setFlowData(data);
      const hasFrames = data.frames && data.frames.length > 0;
      if (hasFrames) {
        setStatus(`${data.n_frames} FRAMES // ${data.n_particles} PARTICLES // MAX ${data.max_speed} m/s // β=${(data as any).effective_beta || 0}°`);
      } else {
        setStatus(`${data.n_streamlines} STREAMLINES // ${data.total_points} POINTS // MAX ${data.max_speed} m/s`);
      }
      renderStreamlines(data);
    } catch (e) {
      setStatus('SOLVER ERROR — IS MODEL SERVER RUNNING ON :5051?');
    }
    setIsLoading(false);
  }, [aircraft, windSpeed, windDir, pitch, yaw]);

  // Render streamlines as tube/line geometry from CFD data
  const renderStreamlines = useCallback((data: FlowData) => {
    const scene = sceneRef.current;
    if (!scene) return;

    // Remove old particles
    if (particlesRef.current) {
      scene.remove(particlesRef.current);
      particlesRef.current.geometry.dispose();
      (particlesRef.current.material as THREE.Material).dispose();
      particlesRef.current = null;
    }

    flowDataRef.current = data;

    // Allocate enough points to show trail history.
    // For each particle, we show its position from the current frame
    // PLUS the previous TRAIL_LENGTH frames. This creates visible
    // flow trails from pure data — no animation tricks.
    const hasFrames = data.frames && data.frames.length > 0;
    const TRAIL_LENGTH = 8; // Show 8 frames of history per particle
    const baseParticles = hasFrames
      ? data.n_particles || data.frames[0].length
      : (data.streamlines || []).length * 4;
    const nPoints = baseParticles * TRAIL_LENGTH;

    if (nPoints === 0) return;

    const geo = new THREE.BufferGeometry();
    const positions = new Float32Array(nPoints * 3);
    const colors = new Float32Array(nPoints * 3);
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    (geo as any)._trailLength = TRAIL_LENGTH;
    (geo as any)._baseParticles = baseParticles;

    const mat = new THREE.PointsMaterial({
      size: 0.06,
      vertexColors: true,
      transparent: true,
      opacity: 0.85,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });

    const pts = new THREE.Points(geo, mat);
    scene.add(pts);
    particlesRef.current = pts;

    if (!hasFrames) {
      // Streamline-based: stagger particles along paths
      const streamlines = data.streamlines || [];
      const pPerSl = 4;
      const offsets = new Float32Array(nParticles);
      for (let i = 0; i < nParticles; i++) {
        offsets[i] = (i % pPerSl) / pPerSl;
      }
      (geo as any)._offsets = offsets;
      (geo as any)._streamlines = streamlines;
      (geo as any)._pPerSl = pPerSl;
    } else {
      (geo as any)._pPerSl = 1;
    }

    setCurrentForces(data.forces);
    frameCounterRef.current = 0;
  }, []);

  // Three.js setup (runs once)
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#0a1628');
    scene.fog = new THREE.FogExp2('#0a1628', 0.008);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(50, container.clientWidth / container.clientHeight, 0.1, 200);
    camera.position.set(2, 6, 18);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.3;
    container.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.target.set(0, 0, 0);
    controls.minDistance = 5;
    controls.maxDistance = 50;

    // Lighting
    scene.add(new THREE.AmbientLight('#1a3a5c', 0.5));
    const main = new THREE.DirectionalLight('#00e5ff', 2.0);
    main.position.set(10, 8, 5);
    scene.add(main);
    scene.add(new THREE.DirectionalLight('#ffc107', 0.3).translateX(-5).translateY(3));
    const rim = new THREE.PointLight('#00e5ff', 1.5, 40);
    rim.position.set(-12, 3, 0);
    scene.add(rim);

    // Grid floor
    const grid = new THREE.GridHelper(60, 60, '#1a3a5c', '#0d1f3c');
    grid.position.y = -5;
    scene.add(grid);

    // Tunnel wireframe
    const tunnelGeo = new THREE.BoxGeometry(50, 12, 12);
    const tunnelMat = new THREE.MeshBasicMaterial({
      color: '#1a3a5c', wireframe: true, transparent: true, opacity: 0.06
    });
    scene.add(new THREE.Mesh(tunnelGeo, tunnelMat));

    // Drone model
    const droneGroup = new THREE.Group();
    scene.add(droneGroup);
    droneRef.current = droneGroup;

    new GLTFLoader().load('/x47b.glb', (gltf) => {
      const model = gltf.scene;

      // Scale to fit
      const box = new THREE.Box3().setFromObject(model);
      const size = box.getSize(new THREE.Vector3());
      const s = 8 / Math.max(size.x, size.y, size.z);
      model.scale.setScalar(s);

      // Center
      box.setFromObject(model);
      model.position.sub(box.getCenter(new THREE.Vector3()));

      // Material
      model.traverse((c) => {
        if ((c as THREE.Mesh).isMesh) {
          (c as THREE.Mesh).material = new THREE.MeshPhongMaterial({
            color: '#0d1f3c',
            emissive: '#00e5ff',
            emissiveIntensity: 0.15,
            shininess: 120,
            transparent: true,
            opacity: 0.8,
            side: THREE.DoubleSide,
          });
        }
      });

      // Find where nose is AFTER scaling/centering
      box.setFromObject(model);
      const center = box.getCenter(new THREE.Vector3());
      const maxX = box.max.x;
      const minX = box.min.x;

      // Nose is at +X. We want nose to point LEFT (-X on screen).
      // Create a wrapper that rotates the whole thing 180° around Y.
      const wrapper = new THREE.Group();
      wrapper.add(model);
      // Rotate nose to point LEFT on screen (-X from camera's perspective)
      // Camera at (2, 6, 15) looking at origin — left is -X
      wrapper.rotation.y = -Math.PI / 2;

      droneGroup.add(wrapper);
    });

    // Streamlines group
    const slGroup = new THREE.Group();
    scene.add(slGroup);
    streamlinesGroupRef.current = slGroup;

    // Force arrows group
    const faGroup = new THREE.Group();
    scene.add(faGroup);
    forceArrowsRef.current = faGroup;

    // Animation loop
    const animate = () => {
      animRef.current = requestAnimationFrame(animate);
      controls.update();

      // Apply pitch/yaw/roll to the GROUP (not the model)
      // The MODEL has rotation.y = PI (faces left) which is FIXED
      // The GROUP adds attitude adjustments on top
      if (droneRef.current) {
        droneRef.current.rotation.x = THREE.MathUtils.lerp(droneRef.current.rotation.x, pitchRef.current * Math.PI / 180, 0.1);
        droneRef.current.rotation.y = THREE.MathUtils.lerp(droneRef.current.rotation.y, yawRef.current * Math.PI / 180, 0.1);
        droneRef.current.rotation.z = THREE.MathUtils.lerp(droneRef.current.rotation.z, rollRef.current * Math.PI / 180, 0.1);
      }

      // Play back pre-computed frames — particles move each frame
      if (particlesRef.current && flowDataRef.current) {
        const data = flowDataRef.current;
        const frames = data.frames;
        const geo = particlesRef.current.geometry;
        const offsets = (geo as any)._offsets as Float32Array;
        const streamlines = (geo as any)._streamlines as number[][][];

        if (frames && frames.length > 0) {
          // Direct frame playback with trail history.
          // For each particle, show its position from the current frame
          // AND the previous TRAIL_LENGTH frames. The older positions
          // fade in opacity, creating visible flow trails from actual data.
          frameCounterRef.current = (frameCounterRef.current + 1) % frames.length;
          const currentFrame = frameCounterRef.current;

          const posAttr = geo.getAttribute('position') as THREE.BufferAttribute;
          const colAttr = geo.getAttribute('color') as THREE.BufferAttribute;
          const maxSpd = data.max_speed || 1;
          const trailLen = (geo as any)._trailLength || 1;
          const baseParts = (geo as any)._baseParticles || frames[0].length;

          let ptIdx = 0;
          for (let t = 0; t < trailLen; t++) {
            // Get frame from history (current, current-1, current-2, ...)
            const fi = (currentFrame - t + frames.length) % frames.length;
            const frame = frames[fi];
            const fadeAlpha = 1.0 - (t / trailLen) * 0.7; // Fade older points

            for (let i = 0; i < Math.min(frame.length, baseParts); i++) {
              if (ptIdx >= posAttr.count) break;
              const [x, y, z, speed] = frame[i];
              posAttr.array[ptIdx * 3] = x;
              posAttr.array[ptIdx * 3 + 1] = y;
              posAttr.array[ptIdx * 3 + 2] = z;

              const spd = Math.min(1, speed / maxSpd);
              let r, g, b;
              if (spd < 0.3) {
                r = 0; g = 0.15 + spd * 2; b = 1;
              } else if (spd < 0.65) {
                r = 0; g = 0.9; b = 1;
              } else {
                const s = (spd - 0.65) / 0.35;
                r = 1; g = 0.5 * (1 - s); b = 0;
              }
              colAttr.array[ptIdx * 3] = r * fadeAlpha;
              colAttr.array[ptIdx * 3 + 1] = g * fadeAlpha;
              colAttr.array[ptIdx * 3 + 2] = b * fadeAlpha;
              ptIdx++;
            }
          }

          geo.setDrawRange(0, ptIdx);
          posAttr.needsUpdate = true;
          colAttr.needsUpdate = true;
          setCurrentFrame(currentFrame);
        } else if (streamlines && streamlines.length > 0 && offsets) {
          // Fallback: animate along streamline paths
          const posAttr = geo.getAttribute('position') as THREE.BufferAttribute;
          const colAttr = geo.getAttribute('color') as THREE.BufferAttribute;
          const maxSpd = data.max_speed || 1;
          const pPerSl = (geo as any)._pPerSl || 4;

          for (let i = 0; i < offsets.length; i++) {
            const slIdx = Math.floor(i / pPerSl) % streamlines.length;
            const sl = streamlines[slIdx];
            if (!sl || sl.length < 2) continue;

            offsets[i] = (offsets[i] + 0.005) % 1.0;
            const idx = Math.floor(offsets[i] * (sl.length - 1));
            const [x, y, z, speed] = sl[idx];
            posAttr.array[i * 3] = x;
            posAttr.array[i * 3 + 1] = y;
            posAttr.array[i * 3 + 2] = z;

            const t = Math.min(1, speed / maxSpd);
            if (t < 0.3) {
              colAttr.array[i * 3] = 0; colAttr.array[i * 3 + 1] = 0.15 + t * 2; colAttr.array[i * 3 + 2] = 1;
            } else if (t < 0.65) {
              colAttr.array[i * 3] = 0; colAttr.array[i * 3 + 1] = 0.9; colAttr.array[i * 3 + 2] = 1;
            } else {
              const s = (t - 0.65) / 0.35;
              colAttr.array[i * 3] = 1; colAttr.array[i * 3 + 1] = 0.5 * (1 - s); colAttr.array[i * 3 + 2] = 0;
            }
          }
          posAttr.needsUpdate = true;
          colAttr.needsUpdate = true;
        }
      }

      renderer.render(scene, camera);
    };
    animate();

    const handleResize = () => {
      if (!container) return;
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      cancelAnimationFrame(animRef.current);
      renderer.dispose();
      if (container.contains(renderer.domElement)) container.removeChild(renderer.domElement);
    };
  }, []);

  // Fetch flow field when params change (debounced 1.5s to let user finish adjusting)
  useEffect(() => {
    const timer = setTimeout(() => {
      fetchFlowField();
    }, 1500);
    return () => clearTimeout(timer);
  }, [aircraft, aircraftSpeed, windSpeed, windDir, pitch, yaw, roll]);

  // Arrow keys for attitude adjustment
  useEffect(() => {
    const keys: Record<string, boolean> = {};
    const down = (e: KeyboardEvent) => { keys[e.key] = true; };
    const up = (e: KeyboardEvent) => { keys[e.key] = false; };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    const iv = setInterval(() => {
      const s = 1;
      if (keys['ArrowUp']) setPitch(p => Math.max(-20, p - s));
      if (keys['ArrowDown']) setPitch(p => Math.min(20, p + s));
      if (keys['ArrowLeft']) setYaw(y => Math.max(-30, y - s));
      if (keys['ArrowRight']) setYaw(y => Math.min(30, y + s));
      if (keys['q'] || keys['Q']) setRoll(r => Math.max(-45, r - s));
      if (keys['e'] || keys['E']) setRoll(r => Math.min(45, r + s));
    }, 50);
    return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up); clearInterval(iv); };
  }, []);

  const profiles: Record<string, { name: string; drag: number; lift: number }> = {
    x47b: { name: 'X-47B UCAV', drag: 0.022, lift: 0.45 },
    cessna172: { name: 'CESSNA 172', drag: 0.034, lift: 0.50 },
    mq9_reaper: { name: 'MQ-9 REAPER', drag: 0.028, lift: 0.55 },
  };
  const prof = profiles[aircraft] || profiles.x47b;

  return (
    <div className="fixed inset-0 z-[200] bg-[#0a1628] flex flex-col">
      {/* Header */}
      <div className="h-10 bg-[#0a1628] border-b border-mil-border flex items-center justify-between px-4 flex-shrink-0">
        <div className="flex items-center gap-4">
          <button onClick={onClose} className="mil-label text-mil-amber hover:text-white transition-colors">DRONE OPS</button>
          <span className="text-[10px] text-mil-cyan font-mono tracking-wider">CFD WIND TUNNEL — NAVIER-STOKES SOLVER</span>
        </div>
        <div className="flex items-center gap-3">
          {isLoading && <div className="w-3 h-3 border-2 border-mil-cyan/30 border-t-mil-cyan rounded-full animate-spin" />}
          <span className="text-[8px] text-mil-dim font-mono">{status}</span>
          <button onClick={onClose}
            className="text-[9px] text-mil-dim font-mono hover:text-white transition-colors px-3 py-1 border border-mil-border rounded-sm">
            BACK TO OPS
          </button>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Left: Metrics */}
        <div className="w-48 border-r border-mil-border p-4 space-y-3 flex-shrink-0 overflow-y-auto">
          <div className="mil-label text-mil-amber">CFD RESULTS</div>
          {[
            { l: 'AIRCRAFT', v: prof.name, c: '#00e5ff' },
            { l: 'DRAG FORCE', v: currentForces ? `${Math.sqrt(currentForces.drag.reduce((s,v)=>s+v*v,0)).toFixed(1)} N` : '--', c: '#ff1744' },
            { l: 'LIFT FORCE', v: currentForces ? `${Math.abs(currentForces.lift[1] || 0).toFixed(2)} N` : '--', c: '#00e676' },
            { l: 'AIRCRAFT TAS', v: `${aircraftSpeed} m/s`, c: '#00e5ff' },
            { l: 'EFF. AIRSPEED', v: flowData ? `${(flowData as any).effective_airspeed?.toFixed(1) || '--'} m/s` : '--', c: '#00e5ff' },
            { l: 'EFF. ALPHA', v: flowData ? `${(flowData as any).effective_alpha?.toFixed(2) || '0'}°` : '--', c: '#ffc107' },
            { l: 'EFF. BETA', v: flowData ? `${(flowData as any).effective_beta?.toFixed(2) || '0'}°` : '--', c: '#ffc107' },
            { l: 'MAX SPEED', v: flowData ? `${flowData.max_speed} m/s` : '--', c: '#00e5ff' },
            { l: 'MAX VORTICITY', v: flowData ? `${flowData.max_vorticity}` : '--', c: '#ffc107' },
            { l: 'ENV. WIND', v: `${windSpeed} m/s @ ${windDir}°`, c: windSpeed > 0 ? '#ff9100' : '#4a6a8a' },
            { l: 'STREAMLINES', v: flowData ? `${flowData.n_streamlines}` : '--', c: '#4a6a8a' },
            { l: 'DATA POINTS', v: flowData ? `${flowData.total_points.toLocaleString()}` : '--', c: '#4a6a8a' },
          ].map(({ l, v, c }) => (
            <div key={l}>
              <div className="text-[8px] text-white/40 font-mono">{l}</div>
              <div className="text-sm font-mono font-bold" style={{ color: c }}>{v}</div>
            </div>
          ))}
          <div className="border-t border-mil-border pt-2">
            <div className="text-[8px] text-white/40 font-mono mb-1">VELOCITY COLOR</div>
            {[['#0044ff', 'SLOW (stagnation)'], ['#00e5ff', 'CRUISE (freestream)'], ['#ff6600', 'FAST (acceleration)']].map(([c, l]) => (
              <div key={l} className="flex items-center gap-1.5 mb-0.5">
                <div className="w-3 h-3 rounded-full" style={{ background: c }} />
                <span className="text-[8px] text-white/50 font-mono">{l}</span>
              </div>
            ))}
          </div>
          <div className="border-t border-mil-border pt-2">
            <div className="text-[8px] text-white/40 font-mono mb-1">FORCE ARROWS</div>
            <div className="flex items-center gap-1.5 mb-0.5">
              <div className="w-3 h-1" style={{ background: '#ff1744' }} />
              <span className="text-[8px] text-white/50 font-mono">DRAG</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-1" style={{ background: '#00e676' }} />
              <span className="text-[8px] text-white/50 font-mono">LIFT</span>
            </div>
          </div>
        </div>

        {/* Center: 3D */}
        <div ref={containerRef} className="flex-1 relative cursor-grab active:cursor-grabbing" />

        {/* Right: Controls */}
        <div className="w-56 border-l border-mil-border p-4 space-y-3 flex-shrink-0 overflow-y-auto">
          <div className="mil-label text-mil-amber">FLIGHT CONDITIONS</div>

          {[
            { l: 'AIRCRAFT TAS', v: `${aircraftSpeed} m/s`, val: aircraftSpeed, set: setAircraftSpeed, min: 50, max: 300 },
            { l: 'ENV. WIND', v: `${windSpeed} m/s`, val: windSpeed, set: setWindSpeed, min: 0, max: 50 },
          ].map(({ l, v, val, set, min, max }) => (
            <div key={l} className="space-y-1">
              <div className="flex justify-between">
                <span className="text-[8px] text-white/40 font-mono">{l}</span>
                <span className="text-[9px] text-mil-cyan font-mono">{v}</span>
              </div>
              <input type="range" min={min} max={max} value={val}
                onChange={(e) => set(Number(e.target.value))}
                className="w-full h-1 bg-mil-border rounded-sm appearance-none cursor-pointer accent-mil-cyan" />
            </div>
          ))}

          <div className="border-t border-mil-border pt-2">
            <div className="mil-label mb-2">WIND ANGLE</div>
            <div className="space-y-0.5 mb-2">
              <div className="flex justify-between">
                <span className="text-[8px] text-white/40 font-mono">DIRECTION (0=head, 90=cross)</span>
                <span className="text-[9px] text-mil-cyan font-mono">{windDir}°</span>
              </div>
              <input type="range" min={-90} max={90} value={windDir}
                onChange={(e) => setWindDir(Number(e.target.value))}
                className="w-full h-1 bg-mil-border rounded-sm appearance-none cursor-pointer accent-mil-cyan" />
            </div>
          </div>

          <div className="border-t border-mil-border pt-2">
            <div className="mil-label mb-2">AIRCRAFT ATTITUDE</div>
            <div className="text-[7px] text-white/30 font-mono mb-2">
              Changes how aircraft attacks the airflow
            </div>
            {[
              { l: 'PITCH (nose up/down)', v: pitch, s: setPitch, mn: -20, mx: 20 },
              { l: 'YAW (nose left/right)', v: yaw, s: setYaw, mn: -30, mx: 30 },
              { l: 'ROLL (bank)', v: roll, s: setRoll, mn: -45, mx: 45 },
            ].map(({ l, v, s, mn, mx }) => (
              <div key={l} className="space-y-0.5 mb-1.5">
                <div className="flex justify-between">
                  <span className="text-[8px] text-white/40 font-mono">{l}</span>
                  <span className="text-[9px] text-mil-cyan font-mono">{v}°</span>
                </div>
                <input type="range" min={mn} max={mx} value={v}
                  onChange={(e) => s(Number(e.target.value))}
                  className="w-full h-1 bg-mil-border rounded-sm appearance-none cursor-pointer accent-mil-cyan" />
              </div>
            ))}
          </div>

          <div className="border-t border-mil-border pt-2">
            <button onClick={() => { setAircraftSpeed(200); setWindSpeed(0); setWindDir(0); setPitch(0); setYaw(0); setRoll(0); }}
              className="w-full py-1.5 text-[8px] font-mono tracking-wider text-mil-dim border border-mil-border rounded-sm hover:text-white transition-all">
              RESET ALL
            </button>
          </div>

          <div className="border-t border-mil-border pt-2">
            <div className="mil-label mb-2">AIRCRAFT</div>
            <div className="space-y-1">
              {[
                { id: 'x47b', name: 'X-47B UCAV' },
                { id: 'cessna172', name: 'CESSNA 172' },
                { id: 'mq9_reaper', name: 'MQ-9 REAPER' },
              ].map((ac) => (
                <button
                  key={ac.id}
                  onClick={() => setAircraft(ac.id)}
                  className={`w-full px-3 py-2 text-left text-[10px] font-mono font-bold tracking-wider rounded-sm border transition-all ${
                    aircraft === ac.id
                      ? 'bg-[#00e5ff]/10 text-[#00e5ff] border-[#00e5ff]/50'
                      : 'bg-[#0a1628] text-[#4a6a8a] border-[#1a3a5c] hover:bg-[#00e5ff]/5 hover:text-[#8ba4c4] hover:border-[#00e5ff]/30'
                  }`}
                >
                  {ac.name}
                </button>
              ))}
            </div>
          </div>

          <div className="border-t border-mil-border pt-2">
            <div className="text-[7px] text-white/20 font-mono leading-relaxed">
              SOLVER: 3D Navier-Stokes (Stam's Stable Fluids)
              <br />GRID: 80×40×40 Eulerian
              <br />ADVECTION: Semi-Lagrangian
              <br />PRESSURE: Poisson solve (Jacobi, 50 iter)
              <br />PARTICLES: Lagrangian tracking (Heun RK2)
              <br />BOUNDARY: No-slip (SDF from X-47B GLB mesh)
              <br />VORTICITY: Confinement enabled
              <br />INFLOW: V_aero = V_aircraft + V_wind
              <br />α = arctan(w_gust / V_TAS)
              <br />β = arctan(V_cross / V_TAS)
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="h-8 bg-[#0a1628] border-t border-mil-border flex items-center justify-center gap-6 flex-shrink-0">
        {[
          `DRAG ${currentForces ? Math.sqrt(currentForces.drag.reduce((s,v)=>s+v*v,0)).toFixed(1) : '--'} N`,
          `LIFT ${currentForces ? Math.abs(currentForces.lift[1] || 0).toFixed(2) : '--'} N`,
          `TAS ${aircraftSpeed} m/s`,
          `WIND ${windSpeed} m/s @ ${windDir}°`,
          `PITCH ${pitch}°`,
          `${flowData?.n_streamlines || 0} STREAMLINES`,
          `${flowData?.total_points?.toLocaleString() || 0} POINTS`,
        ].map(t => <span key={t} className="text-[9px] text-mil-dim font-mono">{t}</span>)}
      </div>
    </div>
  );
}
