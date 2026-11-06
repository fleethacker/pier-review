"""Coupled, explicitly synthetic planar tug bodies and unilateral connections.

Each tug has pose, body velocity and three slew-limited propulsion states. A
bounded velocity/heading controller requests force; it never sets velocity.
Push contact and a straight towline use capped spring/dashpot forces with equal
and opposite reactions at their application points. Spring potential includes
the constant-force region beyond the cap. No hull hydrodynamic identification,
ambient tug wind/current, tug-tug collision or off-assignment hull collision law.

Rigid-body equations and power balance: Fossen's marine craft model,
https://www.fossen.biz/html/marineCraftModel.html . Spring energy is the integral
of the stated synthetic force law; dashpot dissipation is evaluated explicitly.
"""
import math
from dataclasses import dataclass

from mooring.core.schemas.motion_controls import TugDynamicsConfig, TugMotionOrder, MotionTugDynamicsState
from mooring.mechanics.dynamics import BodyParams, _deriv, kinetic_energy


def rotate(angle, x, y):
    c,s = math.cos(angle),math.sin(angle)
    return c*x-s*y,s*x+c*y


def point_state(state, point):
    x,y,yaw,u,v,r = state
    px,py = point
    dx,dy = rotate(yaw,px,py)
    vx,vy = rotate(yaw,u-r*py,v+r*px)
    return (x+dx,y+dy),(vx,vy)


def capped_vector(x,y,limit):
    norm = math.hypot(x,y)
    scale = min(1.0,limit/norm) if norm else 1.0
    return x*scale,y*scale


def rectangles_overlap(a, a_length, a_beam, b, b_length, b_beam):
    """Separating-axis check of explicit synthetic rectangles; touching alone is not overlap."""
    for angle in (a[2],a[2]+math.pi/2,b[2],b[2]+math.pi/2):
        ux,uy = math.cos(angle),math.sin(angle)
        distance = abs((a[0]-b[0])*ux+(a[1]-b[1])*uy)
        extent_a = abs(math.cos(a[2]-angle))*a_length/2+abs(math.sin(a[2]-angle))*a_beam/2
        extent_b = abs(math.cos(b[2]-angle))*b_length/2+abs(math.sin(b[2]-angle))*b_beam/2
        if distance >= extent_a+extent_b-1e-9:
            return False
    return True


def spring(extension, rate, stiffness, damping, capacity):
    """Unilateral capped spring/dashpot; returned dissipation is nonnegative."""
    if extension <= 0:
        return 0.0,0.0,0.0
    elastic = min(capacity,stiffness*extension)
    force = max(0.0,min(capacity,elastic+damping*rate))
    cap_extension = capacity/stiffness
    energy = (.5*stiffness*extension**2 if extension <= cap_extension
              else capacity*(extension-.5*cap_extension))
    return force,energy,max(0.0,(force-elastic)*rate)


@dataclass(frozen=True)
class Connection:
    ship_wrench: tuple[float,float,float]
    tug_wrench: tuple[float,float,float]
    force_world: tuple[float,float]
    point_world: tuple[float,float]
    tug_point_world: tuple[float,float]
    compression: float
    extension: float
    tension: float
    energy: float
    dissipation: float
    status: str
    invalid: bool


class TugFleet:
    def __init__(self, configs, anchors, beam_ft, berth_bearing, ship_length_ft):
        self.ids = sorted(c.tug_id for c in configs)
        self.offsets = {tid:9*i for i,tid in enumerate(self.ids)}
        self.configs = {c.tug_id:c.model_copy(deep=True) for c in configs}
        self.berth_bearing = berth_bearing
        self.ship_length_ft,self.ship_beam_ft = ship_length_ft,beam_ft
        self.points, self.side, self.params, self.orders = {},{},{},{}
        for tid in self.ids:
            c = self.configs[tid]
            if tid not in anchors or c.push_point_id != anchors[tid][1].push_point_id:
                raise ValueError("dynamic tug must use its assigned water-side push point")
            tug,pp,_ = anchors[tid]
            if c.contact_capacity_lbf > min(pp.max_force_lbf,tug.bollard_pull_ahead_lbf):
                raise ValueError("synthetic contact capacity exceeds supplied tug/push-point rating")
            if c.tow_capacity_lbf > min(pp.max_force_lbf,tug.bollard_pull_astern_lbf):
                raise ValueError("synthetic tow capacity exceeds supplied tug/push-point rating")
            if max(abs(c.contact_point_x_ft),abs(c.tow_point_x_ft)) > c.length_ft/2:
                raise ValueError("tug connection point is outside its synthetic hull")
            self.side[tid] = 1 if pp.side == "port" else -1
            self.points[tid] = (pp.x_ft,self.side[tid]*beam_ft/2)
            self.params[tid] = BodyParams(c.mass_slug,c.izz_slug_ft2,
                damping_lin=(c.damping_surge_lbf_per_fps,c.damping_sway_lbf_per_fps,c.damping_yaw_ftlbf_per_radps))
            self.orders[tid] = TugMotionOrder(mode="free",target_velocity_x_fps=0,target_velocity_y_fps=0,
                target_heading_true_deg=(berth_bearing-c.initial_state.yaw_deg)%360,
                tow_length_ft=c.initial_tow_length_ft)

    def initial_state(self):
        out = []
        for tid in self.ids:
            p = self.configs[tid].initial_state
            out.extend((p.x_ft,p.y_ft,math.radians(p.yaw_deg),p.surge_fps,p.sway_fps,math.radians(p.yaw_degps),0,0,0))
        return tuple(out)

    def max_step(self):
        # Numerical bound, not an engineering qualification. Resolve the fastest
        # synthetic contact oscillator and actuator time constant with margin.
        return min(min(.1,c.actuator_response_s/5,c.velocity_response_s/5,c.heading_response_s/5,
            .2*math.sqrt(c.mass_slug/max(c.contact_stiffness_lbf_per_ft,c.tow_stiffness_lbf_per_ft)),
            .2*c.mass_slug/c.damping_surge_lbf_per_fps if c.damping_surge_lbf_per_fps else math.inf,
            .2*c.mass_slug/c.damping_sway_lbf_per_fps if c.damping_sway_lbf_per_fps else math.inf,
            .2*c.izz_slug_ft2/c.damping_yaw_ftlbf_per_radps if c.damping_yaw_ftlbf_per_radps else math.inf)
            for c in self.configs.values())

    def validate_order(self, msg):
        if msg.tug_id not in self.configs:
            raise ValueError("tug has no independent dynamics configuration")
        if math.hypot(msg.target_velocity_x_fps,msg.target_velocity_y_fps) > self.configs[msg.tug_id].max_target_speed_fps:
            raise ValueError("tug target velocity exceeds supplied synthetic controller bound")

    def order(self, msg):
        self.validate_order(msg)
        self.orders[msg.tug_id] = TugMotionOrder(**{n:getattr(msg,n) for n in TugMotionOrder.model_fields})

    def connection(self, tid, ship, auxiliary):
        c,order = self.configs[tid],self.orders[tid]
        offset = self.offsets[tid]
        tug = auxiliary[offset:offset+6]
        anchor = self.points[tid]
        anchor_world,anchor_velocity = point_state(ship,anchor)
        point_x = c.contact_point_x_ft if order.mode == "push" else c.tow_point_x_ft
        tug_point,tug_velocity = point_state(tug,(point_x,0))
        fx=fy=energy=dissipation=compression=extension=tension=0.0
        status,invalid = "free",False
        applied_point = anchor
        if order.mode == "push":
            nx,ny = rotate(ship[2],0,self.side[tid])
            tx,ty = rotate(ship[2],1,0)
            dx,dy = tug_point[0]-anchor_world[0],tug_point[1]-anchor_world[1]
            along,gap = dx*tx+dy*ty,dx*nx+dy*ny
            status = "no_contact"
            if abs(along) <= c.contact_half_width_ft and gap < 0:
                applied_point = (anchor[0]+along,anchor[1])
                anchor_world,anchor_velocity = point_state(ship,applied_point)
                closing = -((tug_velocity[0]-anchor_velocity[0])*nx+(tug_velocity[1]-anchor_velocity[1])*ny)
                compression = -gap
                force,energy,dissipation = spring(compression,closing,c.contact_stiffness_lbf_per_ft,
                    c.contact_damping_lbf_per_fps,c.contact_capacity_lbf)
                fx,fy = -nx*force,-ny*force
                status = "push_contact"
                invalid = compression > c.max_contact_compression_ft
        elif order.mode == "tow":
            dx,dy = tug_point[0]-anchor_world[0],tug_point[1]-anchor_world[1]
            distance = math.hypot(dx,dy)
            extension = max(0,distance-order.tow_length_ft)
            status = "tow_slack"
            if extension > 0:
                ex,ey = dx/distance,dy/distance
                rate = (tug_velocity[0]-anchor_velocity[0])*ex+(tug_velocity[1]-anchor_velocity[1])*ey
                tension,energy,dissipation = spring(extension,rate,c.tow_stiffness_lbf_per_ft,
                    c.tow_damping_lbf_per_fps,c.tow_capacity_lbf)
                fx,fy = ex*tension,ey*tension
                status = "tow_taut"
                invalid = extension > c.max_tow_extension_ft
        if status != "push_contact" and rectangles_overlap(ship,self.ship_length_ft,self.ship_beam_ft,tug,c.length_ft,c.beam_ft):
            invalid = True
        sx,sy = rotate(-ship[2],fx,fy)
        rx,ry = rotate(-tug[2],-fx,-fy)
        return Connection((sx,sy,applied_point[0]*sy-applied_point[1]*sx),
            (rx,ry,point_x*ry),(fx,fy),anchor_world,tug_point,compression,extension,tension,
            energy,dissipation,status,invalid)

    def connections(self, ship, auxiliary):
        return {tid:self.connection(tid,ship,auxiliary) for tid in self.ids}

    def contact_gap(self, ship, auxiliary):
        nearest = math.inf
        for tid in self.ids:
            c,order = self.configs[tid],self.orders[tid]
            if order.mode == "free":
                continue
            i = self.offsets[tid]
            anchor,_ = point_state(ship,self.points[tid])
            point,_ = point_state(auxiliary[i:i+6],(c.contact_point_x_ft if order.mode=="push" else c.tow_point_x_ft,0))
            dx,dy = point[0]-anchor[0],point[1]-anchor[1]
            if order.mode == "tow":
                nearest = min(nearest,abs(math.hypot(dx,dy)-order.tow_length_ft))
            else:
                local_x,local_y = rotate(-ship[2],dx,dy)
                if abs(local_x) <= c.contact_half_width_ft:
                    nearest = min(nearest,abs(local_y))
        return nearest

    def maximum_point_speed(self, ship, auxiliary):
        speed = math.hypot(ship[3],ship[4])
        for tid in self.ids:
            i,c = self.offsets[tid],self.configs[tid]
            tug_speed = math.hypot(auxiliary[i+3],auxiliary[i+4])+abs(auxiliary[i+5])*c.length_ft/2
            ship_point_speed = math.hypot(ship[3],ship[4])+abs(ship[5])*math.hypot(*self.points[tid])
            speed = max(speed,tug_speed+ship_point_speed)
        return speed

    def ship_wrench(self, ship, auxiliary):
        connections = self.connections(ship,auxiliary)
        return tuple(sum(v.ship_wrench[i] for v in connections.values()) for i in range(3))

    def actuator_derivative(self, tid, state):
        c,order = self.configs[tid],self.orders[tid]
        ux,uy = rotate(-state[2],order.target_velocity_x_fps,order.target_velocity_y_fps)
        dx = c.mass_slug*(ux-state[3])/c.velocity_response_s+c.damping_surge_lbf_per_fps*ux
        dy = c.mass_slug*(uy-state[4])/c.velocity_response_s+c.damping_sway_lbf_per_fps*uy
        dx,dy = capped_vector(dx,dy,c.max_propulsion_lbf)
        dx,dy = dx-state[6],dy-state[7]
        norm = math.hypot(dx,dy)
        factor = min(1/c.actuator_response_s,c.propulsion_slew_lbfps/norm) if norm else 0
        target_yaw = math.radians(self.berth_bearing-order.target_heading_true_deg)
        error = (target_yaw-state[2]+math.pi)%(2*math.pi)-math.pi
        rate_limit = math.radians(c.max_target_yaw_degps)
        target_rate = max(-rate_limit,min(rate_limit,error/c.heading_response_s))
        desired_moment = c.izz_slug_ft2*(target_rate-state[5])/c.heading_response_s+c.damping_yaw_ftlbf_per_radps*target_rate
        desired_moment = max(-c.max_yaw_moment_ftlbf,min(c.max_yaw_moment_ftlbf,desired_moment))
        moment_rate = max(-c.yaw_slew_ftlbfps,min(c.yaw_slew_ftlbfps,(desired_moment-state[8])/c.actuator_response_s))
        return dx*factor,dy*factor,moment_rate

    def derivative(self, ship, auxiliary):
        out = []
        for tid,connection in self.connections(ship,auxiliary).items():
            i = self.offsets[tid]
            state = auxiliary[i:i+9]
            wrench = tuple(a+b for a,b in zip(state[6:9],connection.tug_wrench))
            out.extend((*_deriv(self.params[tid],state[:6],wrench),*self.actuator_derivative(tid,state)))
        return tuple(out)

    def saturate_actuators(self, auxiliary):
        out = list(auxiliary)
        for tid in self.ids:
            i,c = self.offsets[tid],self.configs[tid]
            out[i+6],out[i+7] = capped_vector(out[i+6],out[i+7],c.max_propulsion_lbf)
            out[i+8] = max(-c.max_yaw_moment_ftlbf,min(c.max_yaw_moment_ftlbf,out[i+8]))
        return tuple(out)

    def energy(self, ship, auxiliary):
        return sum(kinetic_energy(self.params[tid],auxiliary[self.offsets[tid]:self.offsets[tid]+6])
                   +connection.energy for tid,connection in self.connections(ship,auxiliary).items())

    def powers(self, ship, auxiliary):
        power = dissipation = 0.0
        for tid,connection in self.connections(ship,auxiliary).items():
            i = self.offsets[tid]
            velocity = auxiliary[i+3:i+6]
            power += sum(f*v for f,v in zip(auxiliary[i+6:i+9],velocity))
            dissipation += connection.dissipation+sum(d*v*v for d,v in zip(self.params[tid].damping_lin,velocity))
        return power,dissipation

    def controls_state(self, ship, auxiliary):
        out = []
        for tid,connection in self.connections(ship,auxiliary).items():
            i,c = self.offsets[tid],self.configs[tid]
            out.append(MotionTugDynamicsState(tug_id=tid,basis=c.basis,source=c.source,commanded=self.orders[tid],
                propulsion_surge_lbf=auxiliary[i+6],propulsion_sway_lbf=auxiliary[i+7],propulsion_yaw_moment_ftlbf=auxiliary[i+8],
                transferred_x_lbf=connection.force_world[0],transferred_y_lbf=connection.force_world[1],
                transferred_yaw_moment_ftlbf=connection.ship_wrench[2],contact_compression_ft=connection.compression,
                ship_point_x_ft=connection.point_world[0],ship_point_y_ft=connection.point_world[1],
                tug_point_x_ft=connection.tug_point_world[0],tug_point_y_ft=connection.tug_point_world[1],
                tow_extension_ft=connection.extension,tow_tension_lbf=connection.tension,
                connection_state=connection.status,validity=self.validity(connection)))
        return out

    @staticmethod
    def validity(connection):
        return {"state":"invalid" if connection.invalid else "limited", "reasons":[{
            "code":"TUG_CONNECTION_MODEL_LIMIT" if connection.invalid else "SYNTHETIC_TUG_DYNAMICS",
            "message":("Synthetic connection deformation boundary exceeded or tug hull overlaps outside supported push contact; no hull-impact/rupture law."
                       if connection.invalid else "Synthetic tug mass, drag, bounded propulsion and compliant push/tow connection; no ambient tug forcing, tug-tug or off-assignment collision model.")}]}

    def rich_states(self, ship, auxiliary):
        out = []
        for tid,connection in self.connections(ship,auxiliary).items():
            i,c = self.offsets[tid],self.configs[tid]
            s = auxiliary[i:i+6]
            act = auxiliary[i+6:i+9]
            derivative = _deriv(self.params[tid],s,tuple(a+b for a,b in zip(act,connection.tug_wrench)))
            vx,vy = rotate(s[2],s[3],s[4])
            ax,ay = rotate(s[2],derivative[3]-s[4]*s[5],derivative[4]+s[3]*s[5])
            order = self.orders[tid]
            capacity = c.contact_capacity_lbf if order.mode == "push" else c.tow_capacity_lbf
            out.append(dict(tug_id=tid,availability="available",validity=self.validity(connection),
                provenance={"kind":"estimated","source":c.source,"references":[],"notes":[
                    "Integrated synthetic planar tug body and propulsion states. Transferred force is connection reaction, not requested velocity or engine thrust."]},
                position={"x_ft":s[0],"y_ft":s[1],"z_mllw_ft":None},
                heading_true_deg=(self.berth_bearing-math.degrees(s[2]))%360,
                velocity={"x_fps":vx,"y_fps":vy,"z_fps":None},
                acceleration={"x_fps2":ax,"y_fps2":ay,"z_fps2":None},
                commanded_force=None,actual_force={"x_lbf":connection.force_world[0],"y_lbf":connection.force_world[1],"z_lbf":None},
                push_point_id=c.push_point_id,
                contact_position={"x_ft":connection.point_world[0],"y_ft":connection.point_world[1],"z_mllw_ft":None},
                mode={"free":"standby","push":"push","tow":"pull"}[order.mode],
                contact_state=("line_made_up" if order.mode=="tow" else "contact" if connection.status=="push_contact" else "no_contact"),
                capacity_utilization_pct=100*math.hypot(*connection.force_world)/capacity))
        return out


def synthetic_tug_dynamics_config(tug, ship, point, ship_initial, berth_bearing, *, bow_gap_ft=2.0) -> TugDynamicsConfig:
    """Explicit authored demo coefficients, never actual tug engineering data.

    A fictional 90×32 ft tug with one-million-pound mass, uniform rectangle yaw
    inertia, 8 s translational/5 s yaw damping, and omnidirectional propulsion.
    Seed tug/hull ratings only cap transfer. Contact reaches cap at 4 ft; towline
    at 10 ft extension. These are demonstration assumptions, not a tug model fit.
    Initial tug is stationary and disconnected. ``bow_gap_ft`` is clearance from
    the tug's bow connection point to the assigned hull point, NOT center-to-hull
    distance. Default 2 ft retains the close-work fixture; presets may explicitly
    supply more clearance. Initial tow length retains 8 ft slack, at least 10 ft.
    """
    mass,length,beam = 1_000_000/32.174,90.0,32.0
    if not math.isfinite(bow_gap_ft) or bow_gap_ft < 0:
        raise ValueError("synthetic bow clearance must be finite and nonnegative")
    inertia = mass*(length*length+beam*beam)/12
    push = min(point.max_force_lbf,tug.bollard_pull_ahead_lbf)
    tow = min(point.max_force_lbf,tug.bollard_pull_astern_lbf)
    side = 1 if point.side == "port" else -1
    yaw = math.radians(berth_bearing-ship_initial.heading_true_deg)
    dx,dy = rotate(yaw,point.x_ft,side*(ship.beam_ft/2+length/2+bow_gap_ft))
    return TugDynamicsConfig.model_validate(dict(basis="synthetic",source="synthetic-tug-demo-v1: authored box body, force controller and compliant connections; not real tug coefficients",
        tug_id=tug.tug_id,push_point_id=point.push_point_id,mass_slug=mass,izz_slug_ft2=inertia,
        length_ft=length,beam_ft=beam,contact_point_x_ft=length/2,tow_point_x_ft=length/2,
        damping_surge_lbf_per_fps=mass/8,damping_sway_lbf_per_fps=mass/8,damping_yaw_ftlbf_per_radps=inertia/5,
        max_propulsion_lbf=tug.bollard_pull_ahead_lbf,max_yaw_moment_ftlbf=tug.bollard_pull_ahead_lbf*length*.2,
        propulsion_slew_lbfps=tug.bollard_pull_ahead_lbf/3,yaw_slew_ftlbfps=tug.bollard_pull_ahead_lbf*length*.2/3,
        actuator_response_s=1,velocity_response_s=2,heading_response_s=3,max_target_speed_fps=8,max_target_yaw_degps=10,
        contact_stiffness_lbf_per_ft=push/4,contact_damping_lbf_per_fps=1.4*math.sqrt(push/4*mass),
        contact_capacity_lbf=push,contact_half_width_ft=beam/2,max_contact_compression_ft=8,
        tow_stiffness_lbf_per_ft=tow/10,tow_damping_lbf_per_fps=.8*math.sqrt(tow/10*mass),tow_capacity_lbf=tow,
        max_tow_extension_ft=20,initial_tow_length_ft=max(10,bow_gap_ft+8),
        initial_state=dict(x_ft=ship_initial.x_ft+dx,y_ft=ship_initial.y_ft+dy,yaw_deg=math.degrees(yaw)-side*90,
                           surge_fps=0,sway_fps=0,yaw_degps=0)))
