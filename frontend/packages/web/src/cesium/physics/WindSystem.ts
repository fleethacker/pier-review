/**
 * WindSystem — Applies aerodynamic wind forces to the aircraft.
 *
 * Computes headwind drag, crosswind lateral force, and vertical gusts
 * based on configurable wind direction, speed, and turbulence intensity.
 *
 * Turbulence uses a Dryden-approximation: Gaussian noise filtered through
 * a first-order lag to create realistic gust patterns.
 */

export interface WindConfig {
  direction: number;   // degrees, 0=North, 90=East
  speed: number;       // m/s
  turbulence: number;  // 0.0 (calm) to 1.0 (severe)
}

export interface WindForce {
  headwind: number;    // speed change (m/s²)
  lateral: number;     // heading drift (rad/s)
  vertical: number;    // altitude change (m/s²)
}

export class WindSystem {
  private direction: number = 0;
  private speed: number = 0;
  private turbulence: number = 0;

  // Dryden turbulence state
  private gustX: number = 0;
  private gustY: number = 0;
  private gustZ: number = 0;
  private filterTau: number = 0.5;

  public setWind(direction: number, speed: number, turbulence: number): void {
    this.direction = direction;
    this.speed = Math.max(0, speed);
    this.turbulence = Math.max(0, Math.min(1, turbulence));
  }

  public setRandom(): void {
    this.direction = Math.random() * 360;
    this.speed = Math.random() * 40 + 5;
    this.turbulence = Math.random() * 0.8 + 0.1;
  }

  public getWind(): WindConfig {
    return {
      direction: this.direction,
      speed: this.speed,
      turbulence: this.turbulence,
    };
  }

  /**
   * Compute wind forces on the aircraft for this frame.
   *
   * @param headingRad - Aircraft heading in radians
   * @param speedMs - Aircraft speed in m/s
   * @param dt - Delta time in seconds
   * @returns Wind force components to apply to aircraft physics
   */
  public computeForce(headingRad: number, speedMs: number, dt: number): WindForce {
    if (this.speed < 0.1) {
      return { headwind: 0, lateral: 0, vertical: 0 };
    }

    const windDirRad = (this.direction * Math.PI) / 180;
    const relativeAngle = windDirRad - headingRad;

    // Decompose wind into headwind and crosswind components
    let headwindComponent = this.speed * Math.cos(relativeAngle);
    let crosswindComponent = this.speed * Math.sin(relativeAngle);

    // Add turbulence gusts (filtered noise)
    if (this.turbulence > 0.01) {
      const sigma = this.turbulence * Math.max(this.speed * 0.3, 2.0);
      const alpha = dt / (this.filterTau + dt);
      this.gustX += alpha * (this.gaussianRandom() * sigma - this.gustX);
      this.gustY += alpha * (this.gaussianRandom() * sigma - this.gustY);
      this.gustZ += alpha * (this.gaussianRandom() * sigma * 0.5 - this.gustZ);
      headwindComponent += this.gustX;
      crosswindComponent += this.gustY;
    }

    // Scale forces — these are accelerations applied to the aircraft
    // Headwind: slows/speeds the aircraft proportional to wind² / speed
    const headwind = headwindComponent * 0.02;

    // Crosswind: pushes heading off course
    const lateral = crosswindComponent * 0.001;

    // Vertical: turbulence causes altitude perturbations
    const vertical = this.gustZ * 0.5;

    return { headwind, lateral, vertical };
  }

  private gaussianRandom(): number {
    // Box-Muller transform
    const u1 = Math.random();
    const u2 = Math.random();
    return Math.sqrt(-2 * Math.log(u1 || 0.0001)) * Math.cos(2 * Math.PI * u2);
  }
}
