"""
mav_dynamics
    - this file implements the dynamic equations of motion for MAV
    - use unit quaternion for the attitude state
    
part of mavsimPy
    - Beard & McLain, PUP, 2012
    - Update history:  
        12/17/2018 - RWB
        1/14/2019 - RWB
"""
import sys
sys.path.append('..')
import numpy as np
import matplotlib.pyplot as plt
# load message types
"""
from message_types.msg_state import MsgState
import parameters.aerosonde_parameters as MAV
"""
#from tools.rotations import Quaternion2Euler, Quaternion2Rotation
x=[]
y=[]
z=[]
x_vel=[]
y_vel =[]
z_vel=[]
x_roll=[]
y_pitch=[]
z_yaw=[]
mass = .5
radius = .13
initial = np.array([
    [0.],
    [0.],
    [-100.],
    [0.],
    [0.],
    [0.],
    [0.],
    [0.],
    [0.],
    [0.],
    [0.],
    [5.],
    [0]
    ])
class MavDynamics:
    def __init__(self, Ts):
        self.ts_simulation = Ts
        # set initial states based on parameter file
        # _state is the 13x1 internal state of the aircraft that is being propagated:
        # _state = [pn, pe, pd, u, v, w, e0, e1, e2, e3, p, q, r]
        self._state = initial

    ###################################
    # public functions
    def update(self, forces_moments):
        '''
            Integrate the differential equations defining dynamics. 
            Inputs are the forces and moments on the aircraft.
            Ts is the time step between function calls.
        '''

        # Integrate ODE using Runge-Kutta RK4 algorithm
        time_step = self.ts_simulation
        k1 = self._derivatives(self._state, forces_moments)
        k2 = self._derivatives(self._state + time_step/2.*k1, forces_moments)
        k3 = self._derivatives(self._state + time_step/2.*k2, forces_moments)
        k4 = self._derivatives(self._state + time_step*k3, forces_moments)
        self._state += time_step/6 * (k1 + 2*k2 + 2*k3 + k4)

        # normalize the quaternion
        e0 = self._state.item(6)
        e1 = self._state.item(7)

        e2 = self._state.item(8)
        e3 = self._state.item(9)
        normE = np.sqrt(e0**2+e1**2+e2**2+e3**2)
        self._state[6][0] = self._state.item(6)/normE
        self._state[7][0] = self._state.item(7)/normE
        self._state[8][0] = self._state.item(8)/normE
        self._state[9][0] = self._state.item(9)/normE
        x.append(self._state[0])
        y.append(self._state[1])
        z.append(self._state[2])
        x_vel.append(self._state.item(3))
        y_vel.append(self._state.item(4))
        z_vel.append(self._state.item(5))
        x_roll.append(self._state.item(10))
        y_pitch.append(self._state.item(11))
        z_yaw.append(self._state.item(12))
        # update the message class for the true state
        #self._update_true_state()
        
    ###################################
    # private functions
    def _derivatives(self, state, forces_moments):
        """
        for the dynamics xdot = f(x, u), returns f(x, u)
        """
        # extract the states
        # north = state.item(0)
        # east = state.item(1)
        # down = state.item(2)
        u = state.item(3)
        v = state.item(4)
        w = state.item(5)
        e0 = state.item(6)
        e1 = state.item(7)
        e2 = state.item(8)
        e3 = state.item(9)
        p = state.item(10)
        q = state.item(11)
        r = state.item(12)

        #   extract forces/moments
        fx = forces_moments.item(0)
        fy = forces_moments.item(1)
        fz = forces_moments.item(2)
        l = forces_moments.item(3)
        m = forces_moments.item(4)
        n = forces_moments.item(5)
        
        # position kinematics
        pos_dot = np.array([
            [e1**2+e0**2 - e2**2 - e3**2, 2*(e1*e2-e3*e0), 2*(e1*e3+e2*e0)],
            [2*(e1*e2+e3*e0), e2**2+e0**2-e1**2-e3**2, 2*(e2*e3-e1*e0)],
            [2*(e1*e3-e2*e0), 2*(e2*e3+e1*e0), e3**2+e0**2-e1**2-e2**2]
        ])@np.array([[u],[v],[w]])
        """
        pos_dot = np.array([
            [e1,e2, e3],
            [e3,e2,e1],
            [e1,e2,e3]
            ])
        pos2 = np.array([[u],[v],[w]])
        """
        north_dot = pos_dot[0][0]
        east_dot =pos_dot[1][0]
        down_dot = pos_dot[2][0]
        
        # position dynamics
        
        vel = np.array([[r*v - q*w],
                          [p*w - r*u],
                          [q*u - p*v]]) + (1/mass)*np.array([[fx], [fy], [fz]])
        
        
        u_dot = vel[0][0]
        v_dot = vel[1][0]
        w_dot = vel[2][0]
        
        #Initializing the inertia matrix and required constants
        jx =  (2./5.)*mass*radius**2
        jy = jx
        jz = jx
        jxy = 0.
        jyx = 0.
        jxz = 0.
        jzx = 0.
        jyz = 0.
        jzy = 0.
        r0 = jx*jz-jxz**2
        r1 = (jxz*(jx-jy+jz))/r0
        r2 = (jz*(jz-jy)+jxz**2)/r0
        r3 = jz/r0
        r4 = jxz/r0
        r5 = (jz-jx)/jy
        r6 = jxz/jy
        r7 = ((jx-jy)*jx+jxz**2)/r0
        r8 = jx/r0
        # rotational kinematics
        
        e_vel = .5*np.array([
            [0.,-p,-q,-r],
            [p,0.,r,-q],
            [q,-r, 0., p],
            [r,q,-p,0.]
        ])@np.array([
            [e0],
            [e1],
            [e2],
            [e3]
        ])
        e0_dot = e_vel[0][0]
        e1_dot = e_vel[1][0]
        e2_dot = e_vel[2][0]
        e3_dot = e_vel[3][0]

        # rotatonal dynamics
        """"
        w_dot = np.array([
                [r1*p*q-r2*q*r],
                [r5*p*r-r6*(p**2-r**2)],
                [r7*p*q-r1*q*r]
            ])
        
        w_2 = np.array([
                    [r3*l+r4*n],
                    [m/jy],
                    [r4*l+r8*n]
                ])
        """
        p_dot = r1*p*q-r2*q*r+r3*l+r4*n
        q_dot = r5*p*r-r6*(p**2-r**2)+m/jy
        r_dot = r7*p*q-r1*q*r+r4*l+r8*n

        # collect the derivative of the states
        x_dot = np.array([[north_dot, east_dot, down_dot, u_dot, v_dot, w_dot,e0_dot, e1_dot, e2_dot, e3_dot, p_dot, q_dot, r_dot]])
        return x_dot.transpose()
    """
    def _update_true_state(self):
        # update the true state message:
        phi, theta, psi = Quaternion2Euler(self._state[6:10])
        self.true_state.north = self._state.item(0)
        self.true_state.east = self._state.item(1)
        self.true_state.altitude = -self._state.item(2)
        self.true_state.phi = phi
        self.true_state.theta = theta
        self.true_state.psi = psi
        self.true_state.p = self._state.item(10)
        self.true_state.q = self._state.item(11)
        self.true_state.r = self._state.item(12)
        """
test = MavDynamics(.1)
forces_moments = np.array([
    [0],
    [-mass*9.81],
    [0],
    [0],
    [0],
    [0]
    ])
for n in range(100):
    test.update(forces_moments)
time = np.linspace(0,100,100)

plt.figure()
plt.grid()
plt.title("X_position")
plt.plot(time,x)
plt.xlim(0,100)
plt.ylim(0,100)

plt.figure()
plt.grid()
plt.plot(time,y)
plt.title("Y_pos")

plt.figure()
plt.title("Altitude")
plt.grid()
plt.plot(time,z)

plt.figure()
plt.title("X_velocity")
plt.grid()
plt.plot(time,x_vel)

plt.figure()
plt.title("Y_velocity")
plt.plot(time,y_vel)
plt.grid()

plt.figure()
plt.title("Roll vel")
plt.plot(time,x_roll)
plt.grid()

plt.figure()
plt.title("Pitch vel")
plt.plot(time,y_pitch)
plt.grid()

plt.figure()
plt.title("Yaw vel")
plt.grid()
plt.plot(time,z_yaw)
