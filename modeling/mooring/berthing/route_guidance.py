"""Bounded training helmsman: requests forces, never writes ship pose/velocity.

Pure pursuit and damped heading/speed control are authored training policies,
not hydrodynamic coefficients or approved pilot procedures. Updates occur at
fixed simulation times; the object is copied into prediction. Manual helm wins.
"""
import math
from dataclasses import dataclass
from mooring.core.schemas.motion_controls import HelmOrder
from mooring.core.schemas.motion_guidance import MotionGuidanceState
from mooring.core.units import KT_TO_FPS

UPDATE_S = 0.5
SPEED_RESPONSE_S = 25.0
HEADING_GAIN = 1.5
YAW_DAMPING_S = 12.0
DECELERATION_FPS2 = 0.04

def _clip(value, low, high):
    return min(high, max(low, value))

@dataclass(frozen=True)
class RoutePoint:
    x_ft: float
    y_ft: float
    speed_fps: float
    name: str

@dataclass
class RouteGuidance:
    points: list[RoutePoint]
    route_id: str
    vessel_length_ft: float = 600.0
    waypoint_index: int = 1
    next_update_s: float = 0.0
    active: bool = True
    completed: bool = False
    target_speed_fps: float = 0.0

    def __post_init__(self):
        if len(self.points) < 2 or self.vessel_length_ft <= 0:
            raise ValueError("guidance needs two route points and positive vessel length")
        if any(not all(math.isfinite(v) for v in (p.x_ft,p.y_ft,p.speed_fps)) or p.speed_fps < 0 for p in self.points):
            raise ValueError("route points need finite coordinates and nonnegative speeds")

    def geometry(self, state):
        a,b = self.points[self.waypoint_index-1:self.waypoint_index+1]
        dx,dy = b.x_ft-a.x_ft,b.y_ft-a.y_ft
        length = math.hypot(dx,dy)
        if length < 1e-6:
            raise ValueError("successive guidance points must be distinct")
        px,py = state[0]-a.x_ft,state[1]-a.y_ft
        fraction = (px*dx+py*dy)/(length*length)
        cross = (dx*py-dy*px)/length
        remaining = max(0.0,1-fraction)*length
        remaining += sum(math.hypot(q.x_ft-p.x_ft,q.y_ft-p.y_ft)
                         for p,q in zip(self.points[self.waypoint_index:],self.points[self.waypoint_index+1:]))
        return fraction,cross,remaining

    def _aim(self, state):
        fraction,_,remaining = self.geometry(state)
        distance = max(self.vessel_length_ft,abs(state[3])*60)
        index = self.waypoint_index
        a,b = self.points[index-1:index+1]
        x = a.x_ft+_clip(fraction,0,1)*(b.x_ft-a.x_ft)
        y = a.y_ft+_clip(fraction,0,1)*(b.y_ft-a.y_ft)
        while True:
            segment = math.hypot(b.x_ft-x,b.y_ft-y)
            if segment >= distance or index == len(self.points)-1:
                f = min(1.0,distance/segment) if segment else 0
                return x+f*(b.x_ft-x),y+f*(b.y_ft-y),remaining
            distance -= segment
            x,y = b.x_ft,b.y_ft
            index += 1
            b = self.points[index]

    def order(self, t_s, state, params, propulsion_spec):
        self.next_update_s = (math.floor((t_s+1e-8)/UPDATE_S)+1)*UPDATE_S
        while self.waypoint_index < len(self.points)-1:
            fraction,_,_ = self.geometry(state)
            if fraction < 1:
                break
            self.waypoint_index += 1
        x,y,remaining = self._aim(state)
        final = self.points[-1]
        distance_final = math.hypot(state[0]-final.x_ft,state[1]-final.y_ft)
        if distance_final < 80 and math.hypot(state[3],state[4]) < 0.2:
            self.completed,self.active,self.target_speed_fps = True,False,0.0
            return HelmOrder(port_throttle=0,starboard_throttle=0,rudder_deg=0,bow_thruster=0,stern_thruster=0)
        angle = math.atan2(y-state[1],x-state[0])
        error = math.atan2(math.sin(angle-state[2]),math.cos(angle-state[2]))
        speed = self.points[self.waypoint_index-1].speed_fps
        speed = min(speed,math.sqrt(2*DECELERATION_FPS2*max(0,remaining-40)))
        speed *= max(0.15,math.cos(error))
        self.target_speed_fps = speed
        force = params.m[0]*(speed-state[3])/SPEED_RESPONSE_S
        force += params.damping_lin[0]*state[3]+params.damping_quad[0]*abs(state[3])*state[3]
        limit = propulsion_spec.max_ahead_thrust_lbf if force >= 0 else propulsion_spec.max_astern_thrust_lbf
        throttle = _clip(force/(2*limit),-1,1) if limit else 0.0
        rudder = _clip(-HEADING_GAIN*math.degrees(error)+YAW_DAMPING_S*math.degrees(state[5]),
                       -propulsion_spec.rudder_max_deg,propulsion_spec.rudder_max_deg)
        # Differential thrust assists low-speed turning; actual actuators retain
        # their own capacity and slew limits. This is not a position constraint.
        yaw_request = params.m[2]*(error/80-state[5]/15)+params.damping_lin[2]*state[5]
        yaw_capacity = 2*propulsion_spec.max_ahead_thrust_lbf*propulsion_spec.shaft_y_ft
        differential = _clip(yaw_request/yaw_capacity,-0.4,0.4) if yaw_capacity else 0.0
        differential *= max(0,1-abs(state[3])/3)
        return HelmOrder(port_throttle=_clip(throttle-differential,-1,1),
                         starboard_throttle=_clip(throttle+differential,-1,1),rudder_deg=rudder,
                         bow_thruster=0,stern_thruster=0)

    def state(self, t_s, state):
        _,cross,remaining = self.geometry(state)
        return MotionGuidanceState(active=self.active,route_id=self.route_id,waypoint_index=self.waypoint_index,
            waypoint_name=self.points[self.waypoint_index].name,target_speed_kt=self.target_speed_fps/KT_TO_FPS,
            cross_track_ft=cross,remaining_ft=remaining,completed=self.completed)
