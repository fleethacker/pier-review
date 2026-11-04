import { CesiumVehicleGame } from './cesium/bootstrap/main';
import { GameBridge } from './cesium/bridge/GameBridge';
import { mountReactUI } from './react/index';
import { hasValidTokens } from './utils/tokenValidator';
import { mountTokenSetup } from './react/tokenSetup.tsx';
import { mountLocationPicker } from './react/locationPicker.tsx';
import { setBaseLocation, type BaseLocation } from './baseLocation';
import './cesium.css';

function setLoadingOverlay(visible: boolean) {
    const el = document.getElementById('loading-overlay');
    if (el) {
        if (visible) {
            el.classList.remove('hidden');
        } else {
            el.classList.add('hidden');
        }
    }
}

async function initializeGame() {
    // Hide loading overlay initially (location picker / token setup have their own UI)
    setLoadingOverlay(false);

    if (!hasValidTokens()) {
        mountTokenSetup(() => {
            window.location.reload();
        });
        return;
    }

    // Show location picker and wait for selection
    const location = await new Promise<BaseLocation>((resolve) => {
        const root = mountLocationPicker((loc) => {
            root.unmount();
            resolve(loc);
        });
    });

    setBaseLocation(location);

    // Show loading overlay during globe zoom-in
    setLoadingOverlay(true);

    const game = new CesiumVehicleGame('cesiumContainer');

    if (location.missionId === 'maverick') {
        const gameBridge = new GameBridge(game);

        // Phase 1: Cinematic (globe spin + zoom to carrier)
        // Show loading overlay with header/footer — same as normal mode
        setLoadingOverlay(true);
        await gameBridge.startMaverickCinematic();

        // Hide loading overlay, mount React UI (same timing as normal flow)
        setLoadingOverlay(false);
        gameBridge.emit('gameReady', { ready: true });
        mountReactUI(gameBridge);

        // Phase 2: Briefing + spawn (React UI is now mounted, briefing screen visible)
        await gameBridge.startMaverickMission();

        if (typeof window !== 'undefined') {
            (window as { cesiumGame?: CesiumVehicleGame }).cesiumGame = game;
            (window as { gameBridge?: GameBridge }).gameBridge = gameBridge;
        }

        return { game, gameBridge };
    }

    // Normal flow — cinematic zoom to location
    await game.startCinematicSequence();

    // Hide loading overlay - game is ready
    setLoadingOverlay(false);

    const gameBridge = new GameBridge(game);
    gameBridge.emit('gameReady', { ready: true });

    mountReactUI(gameBridge);

    if (typeof window !== 'undefined') {
        (window as { cesiumGame?: CesiumVehicleGame }).cesiumGame = game;
        (window as { gameBridge?: GameBridge }).gameBridge = gameBridge;
    }

    return { game, gameBridge };
}

initializeGame().catch(error => {
    console.error('Failed to start Cesium Vehicle Game:', error);
});
