import * as Cesium from 'cesium';
import { Camera } from '../camera/Camera';
import { FollowCamera } from '../camera/FollowCamera';
import { Vehicle } from '../vehicles/Vehicle';
import { Updatable } from '../core/GameLoop';
import { InputManager } from '../input/InputManager';

export type CameraType = 'follow';

export class CameraManager implements Updatable {
  private camera: Camera;
  private cesiumCamera: Cesium.Camera;

  constructor(cesiumCamera: Cesium.Camera) {
    this.cesiumCamera = cesiumCamera;
    this.camera = new FollowCamera(this.cesiumCamera);
    this.camera.activate();
  }

  public getActiveCamera(): Camera | null {
    return this.camera;
  }

  public getActiveCameraType(): CameraType {
    return 'follow';
  }

  public setTarget(vehicle: Vehicle | null): void {
    this.camera.setTarget(vehicle);
  }

  public update(deltaTime: number): void {
    this.camera.update(deltaTime);
  }

  public setupInputHandling(_inputManager: InputManager): void {
    // No camera switching - single camera mode
  }

  public destroy(): void {
    this.camera.deactivate();
  }
}
