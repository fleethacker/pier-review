"""Synthetic ramps and bounded propulsion/rudder forces in ship axes.

Rudder: dynamic pressure times area and bounded lift coefficient (NASA):
https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/lift-equation/ .
Dimensional surrogate, not identified propulsion. Ahead propwash is explicitly
synthetic; no astern wash, wake interaction or rudder drag model.
"""
import math

from mooring.core.schemas.motion_controls import HelmOrder, MotionControlState

NEUTRAL = HelmOrder(port_throttle=0, starboard_throttle=0, rudder_deg=0, bow_thruster=0, stern_thruster=0)


def ramp(old, target, rate, elapsed):
    delta = target-old
    return old+math.copysign(min(abs(delta), rate*max(0, elapsed)), delta)


class Propulsion:
    def __init__(self, spec):
        self.spec = spec.model_copy(deep=True)
        self.start = 0.0
        self.old = NEUTRAL.model_copy()
        self.commanded = NEUTRAL.model_copy()

    def actual(self, t):
        p = self.spec
        rates = (p.engine_slew_per_s, p.engine_slew_per_s, p.rudder_slew_degps,
                 p.thruster_slew_per_s, p.thruster_slew_per_s)
        return HelmOrder(**{name: ramp(getattr(self.old,name), getattr(self.commanded,name), rate, t-self.start)
                            for name,rate in zip(HelmOrder.model_fields, rates)})

    def order(self, command, t):
        if abs(command.rudder_deg) > self.spec.rudder_max_deg:
            raise ValueError("rudder order exceeds supplied actuator limit")
        self.old, self.start = self.actual(t), t
        self.commanded = HelmOrder(**{name: getattr(command,name) for name in HelmOrder.model_fields})

    def forces(self, t, state, current_body=(0.0, 0.0)):
        p, a = self.spec, self.actual(t)
        def thrust(value):
            return value*(p.max_ahead_thrust_lbf if value >= 0 else p.max_astern_thrust_lbf)
        port, starboard = thrust(a.port_throttle), thrust(a.starboard_throttle)
        flow = state[3]-current_body[0]
        wash = p.propwash_fps_at_full_ahead*math.sqrt((max(a.port_throttle,0)+max(a.starboard_throttle,0))/2)
        axial = math.copysign(math.hypot(flow, wash), flow if flow else 1)
        lateral = state[4]+state[5]*p.rudder_x_ft-current_body[1]
        speed2 = axial*axial+lateral*lateral
        incidence = (1 if axial >= 0 else -1)*math.radians(a.rudder_deg)-math.atan2(lateral, max(abs(axial),1e-12))
        cl = max(-p.rudder_max_lift_coefficient, min(p.rudder_max_lift_coefficient,
                                                  p.rudder_lift_slope_per_rad*incidence))
        rudder = .5*p.water_density_slug_ft3*speed2*p.rudder_area_ft2*cl
        rudder = max(-p.rudder_max_force_lbf, min(p.rudder_max_force_lbf, rudder))
        bow, stern = a.bow_thruster*p.bow_thruster_max_lbf, a.stern_thruster*p.stern_thruster_max_lbf
        x, y = port+starboard, rudder+bow+stern
        n = p.shaft_y_ft*(starboard-port)+p.rudder_x_ft*rudder+p.bow_thruster_x_ft*bow+p.stern_thruster_x_ft*stern
        return (x,y,n), (port,starboard,rudder,bow,stern)

    def state(self, t, state, current_body=(0.0,0.0)):
        wrench, parts = self.forces(t,state,current_body)
        p = self.spec
        c, sn = math.cos(state[2]), math.sin(state[2])
        actuators = []
        for name,x,y,fx,fy in (
                ("port_engine", p.shaft_x_ft, p.shaft_y_ft, parts[0], 0),
                ("starboard_engine", p.shaft_x_ft, -p.shaft_y_ft, parts[1], 0),
                ("rudder", p.rudder_x_ft, 0, 0, parts[2]),
                ("bow_thruster", p.bow_thruster_x_ft, 0, 0, parts[3]),
                ("stern_thruster", p.stern_thruster_x_ft, 0, 0, parts[4])):
            actuators.append(dict(actuator_id=name, x_ft=state[0]+c*x-sn*y, y_ft=state[1]+sn*x+c*y,
                                  x_lbf=c*fx-sn*fy, y_lbf=sn*fx+c*fy, yaw_moment_ftlbf=x*fy-y*fx))
        return MotionControlState(basis=self.spec.basis, source=self.spec.source,
            commanded=self.commanded, actual=self.actual(t), port_thrust_lbf=parts[0],
            starboard_thrust_lbf=parts[1], rudder_force_lbf=parts[2], bow_thruster_force_lbf=parts[3],
            stern_thruster_force_lbf=parts[4], surge_force_lbf=wrench[0], sway_force_lbf=wrench[1],
            yaw_moment_ftlbf=wrench[2], actuators=actuators, validity={"state":"limited", "reasons":[{
                "code":"SYNTHETIC_PROPULSION", "message":"Bounded synthetic thrust/lift and actuator slew; not vessel-qualified propulsion."}]})
