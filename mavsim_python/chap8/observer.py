"""
observer
    - Beard & McLain, PUP, 2012
    - Last Update:
        3/2/2019 - RWB
"""

import sys
import numpy as np
from scipy import stats
sys.path.append('..')
import parameters.control_parameters as CTRL
import parameters.simulation_parameters as SIM
import parameters.sensor_parameters as SENSOR
from tools.wrap import wrap
from message_types.msg_state import MsgState
from message_types.msg_sensors import MsgSensors
import parameters.aerosonde_parameters as MAV
from math import tan
from math import cos
from math import sin

class Observer:
    def __init__(self, ts_control, initial_state = MsgState(), initial_measurements = MsgSensors()):
        # initialized estimated state message
        self.estimated_state = initial_state
        # use alpha filters to low pass filter gyros and accels
        # alpha = Ts/(Ts + tau) where tau is the LPF time constant
        self.lpf_gyro_x = AlphaFilter(alpha=0.5, y0=initial_measurements.gyro_x)
        self.lpf_gyro_y = AlphaFilter(alpha=0.5, y0=initial_measurements.gyro_y)
        self.lpf_gyro_z = AlphaFilter(alpha=0.5, y0=initial_measurements.gyro_z)
        self.lpf_accel_x = AlphaFilter(alpha=0.5, y0=initial_measurements.accel_x)
        self.lpf_accel_y = AlphaFilter(alpha=0.5, y0=initial_measurements.accel_y)
        self.lpf_accel_z = AlphaFilter(alpha=0.5, y0=initial_measurements.accel_z)
        # use alpha filters to low pass filter absolute and differential pressure
        self.lpf_abs = AlphaFilter(alpha=0.9, y0=initial_measurements.abs_pressure)
        self.lpf_diff = AlphaFilter(alpha=0.5, y0=initial_measurements.diff_pressure)
        # ekf for phi and theta
        self.attitude_ekf = EkfAttitude()
        # ekf for pn, pe, Vg, chi, wn, we, psi
        self.position_ekf = EkfPosition()


    def update(self, measurement):

        # estimates for p, q, r are low pass filter of gyro minus bias estimate
        self.estimated_state.p = self.lpf_gyro_x.update(measurement.gyro_x - self.estimated_state.bx)
        self.estimated_state.q = self.lpf_gyro_y.update(measurement.gyro_y - self.estimated_state.by)
        self.estimated_state.r = self.lpf_gyro_z.update(measurement.gyro_x - self.estimated_state.bz)

        # invert sensor model to get altitude and airspeed
        self.estimated_state.altitude = self.lpf_abs.update(measurement.static_pressure)/(MAV.rho*MAV.gravity)
        self.estimated_state.Va = np.sqrt((2./MAV.rho)*self.lpf_diff.update(measurement.diff_pressure))

        # estimate phi and theta with simple ekf
        self.attitude_ekf.update(self.estimated_state, measurement)

        # estimate pn, pe, Vg, chi, wn, we, psi
        self.position_ekf.update(self.estimated_state, measurement)

        # not estimating these
        self.estimated_state.alpha = self.estimated_state.theta
        self.estimated_state.beta = 0.0
        self.estimated_state.bx = 0.0
        self.estimated_state.by = 0.0
        self.estimated_state.bz = 0.0
        return self.estimated_state


class AlphaFilter:
    # alpha filter implements a simple low pass filter
    # y[k] = alpha * y[k-1] + (1-alpha) * u[k]
    def __init__(self, alpha=0.5, y0=0.0):
        self.alpha = alpha  # filter parameter
        self.y = y0  # initial condition

    def update(self, u):
        self.y = self.alpha*self.y+(1-self.alpha)*u
        return self.y


class EkfAttitude:
    # implement continous-discrete EKF to estimate roll and pitch angles
    def __init__(self):
        self.Q = (1e-6)*np.eye(2)
        self.Q_gyro = np.eye(3) * SENSOR.gyro_sigma ** 2
        self.R_accel = np.eye(3) * SENSOR.accel_sigma ** 2
        self.N = 10  # number of prediction step per sample
        self.xhat = np.array([[0.0,0.0]]).T # initial state: phi, theta
        self.P = np.eye(2)*.1
        self.Ts = SIM.ts_control/self.N
        self.gate_threshold = SIM.ts_control/self.N

    def update(self, state, measurement):
        self.propagate_model(state)
        self.measurement_update(state, measurement)
        state.phi = self.xhat.item(0)
        state.theta = self.xhat.item(1)

    def f(self, x, state):
        # system dynamics for propagation model: xdot = f(x, u)
        p = state.p
        q = state.q
        r = state.r
        phi = x.item(0)
        theta = x.item(1)
        one = p+q*sin(phi)*tan(theta)+r*cos(phi)*tan(theta)
        two = q*cos(phi)-r*sin(phi)
        f_ = np.vstack((one,two))
        return f_

    def h(self, x, state):
        # measurement model y
        p = state.p
        q = state.q
        r = state.r
        phi = x.item(0)
        theta = x.item(1)
        Va = state.Va
        one = q * Va * sin(theta) + MAV.gravity * sin((theta))
        two = r * Va * cos(theta) - p * Va * sin(theta) - MAV.gravity * cos(theta) * sin(phi)
        three = -q * Va * cos(theta) - MAV.gravity * cos(theta) * cos(phi)
        h_ = np.vstack((one,two,three))
        return h_

    def propagate_model(self, state):
        for i in range(0, self.N):
            phi = self.xhat.item(0)
            theta = self.xhat.item(1)
            # propagate model
            self.xhat = self.xhat + self.Ts * self.f(self.xhat, state)
            # compute Jacobian
            A = jacobian(self.f, self.xhat, state)
            # compute G matrix for gyro noise
            G = np.array([
                [1.0, np.sin(phi) * np.tan(theta), np.cos(phi) * np.tan(theta)],
                [0.0, np.cos(phi), -np.sin(phi)]
            ])
            A_d = np.eye(2) + A * self.Ts + (A @ A) * (self.Ts ** 2) / 2.0
            G_d = G * self.Ts
            # update P with discrete time model
            self.P = A_d @ self.P @ A_d.T + G_d @ self.Q_gyro @ G_d.T + \
                     self.Q * self.Ts ** 2

    def measurement_update(self, state, measurement):
        # measurement updates
        threshold = 2.0
        h = self.h(self.xhat, state)
        C = jacobian(self.h, self.xhat, state)
        y = np.array([[measurement.accel_x, measurement.accel_y,
                       measurement.accel_z]]).T

        L = self.P @ C.T @ np.linalg.inv(self.R_accel + C @ self.P @ C.T)
        self.P = (np.eye(2) - L @ C) @ self.P @ (np.eye(2) - L @ C).T + \
                 L @ self.R_accel @ L.T
        self.xhat += L @ (y - h)


class EkfPosition:
    # implement continous-discrete EKF to estimate pn, pe, Vg, chi, wn, we, psi
    def __init__(self):
        self.Q = np.diag((
            .01,  # pn
            .01,  # pe
            .01,  # Vg
            .01,  # Chi
            .01,  # wn
            .01,  # we
            .01  # psi
        ))
        self.R_gps = np.diag([SENSOR.gps_n_sigma ** 2, SENSOR.gps_e_sigma ** 2,
                              SENSOR.gps_Vg_sigma ** 2, SENSOR.gps_course_sigma ** 2])
        self.R_pseudo = np.diag([0.01, 0.01])
        self.N = 25  # number of prediction step per sample
        self.Ts = (SIM.ts_control / self.N)
        self.xhat = np.array([[0.,0.,25.,0.,0.,0.,0.]]).T
        self.P = np.eye(7)*.5
        self.gps_n_old = 9999
        self.gps_e_old = 9999
        self.gps_Vg_old = 9999
        self.gps_course_old = 9999
        #self.pseudo_threshold = 1000#stats.chi2.isf()
        #self.gps_threshold = 100000 # don't gate GPS

    def update(self, state, measurement):
        self.propagate_model(state)
        self.measurement_update(state, measurement)
        state.north = self.xhat.item(0)
        state.east = self.xhat.item(1)
        state.Vg = self.xhat.item(2)
        state.chi = self.xhat.item(3)
        state.wn = self.xhat.item(4)
        state.we = self.xhat.item(5)
        state.psi = self.xhat.item(6)

    def f(self, x, state):
        # system dynamics for propagation model: xdot = f(x, u)
        pn = x.item(0)
        pe = x.item(1)
        Vg = x.item(2)
        chi = x.item(3)
        wn = x.item(4)
        we = x.item(5)
        psi = x.item(6)

        r = state.r
        q = state.q
        theta = state.theta
        phi = state.phi
        pndot = Vg * cos(chi)
        pedot = Vg * sin(chi)
        Va = state.Va
        chidot = MAV.gravity/Vg*tan(phi)*cos(chi-psi)
        psidot = q * sin(phi) / cos(theta) + r * cos(phi) / cos(theta)
        Vgdot = ((Va*cos(psi) + wn) * (-Va*psidot*sin(psi)) + (Va*sin(psi) + we)*(Va*psidot*cos(psi)))*1/Vg
        f_ = np.vstack((pndot, pedot, Vgdot, chidot, 0., 0., psidot))
        return f_

    def h_gps(self, x, state):
        # measurement model for gps measurements
        pn = x.item(0)
        pe = x.item(1)
        Vg = x.item(2)
        chi = x.item(3)
        h_ = np.vstack((pn,pe,Vg,chi))
        return h_

    def h_pseudo(self, x, state):
        # measurement model for wind triangale pseudo measurement
        Vg = x.item(2)
        chi = x.item(3)
        wn = x.item(4)
        we = x.item(5)
        psi = x.item(6)
        Va = state.Va
        h_ = np.array([[Va * np.cos(psi) + wn - Vg * np.cos(chi)],
                       [Va * np.sin(psi) + we - Vg * np.sin(chi)]])
        return h_

    def propagate_model(self, state):
        # model propagation
        for i in range(0, self.N):
            # propagate model
            self.xhat = self.xhat + self.Ts*self.f(self.xhat, state)
            # compute Jacobian
            A = jacobian(self.f, self.xhat, state)
            # testing again
            # compute G matrix for gyro noise
            phi = state.psi
            theta = state.theta
            G = np.array([
                [1.0, sin(phi) * tan(theta), cos(phi) * tan(theta), 0],
                [0.0, cos(phi), -sin(phi), 0]
            ])
            # convert to discrete time models
            A_d = np.eye(7) + A * self.Ts + (A @ A) * (self.Ts ** 2) / 2.0
            # update P with discrete time model
            G_d = G * self.Ts
            self.P += self.Ts * A_d@self.P@A_d.T + self.Q*self.Ts**2

    def wrap(self, chi_c, chi):
        while chi_c - chi > np.pi:
            chi_c = chi_c - 2.0 * np.pi
        while chi_c - chi < -np.pi:
            chi_c = chi_c + 2.0 * np.pi
        return chi_c
    def measurement_update(self, state, measurement):
        # always update based on wind triangle pseudu measurement
        h = self.h_pseudo(self.xhat, state)
        C = jacobian(self.h_pseudo, self.xhat, state)
        y = np.array([[0, 0]]).T

        L = self.P @ C.T @ np.linalg.inv(self.R_pseudo + C @ self.P @ C.T)
        self.P = (np.eye(7) - L @ C) @ self.P @ (np.eye(7) - L @ C).T + \
                 L @ self.R_pseudo @ L.T
        self.xhat += L @ (y - h)

        # only update GPS when one of the signals changes
        if (measurement.gps_n != self.gps_n_old) \
                or (measurement.gps_e != self.gps_e_old) \
                or (measurement.gps_Vg != self.gps_Vg_old) \
                or (measurement.gps_course != self.gps_course_old):
            h = self.h_gps(self.xhat, state)
            C = jacobian(self.h_gps, self.xhat, state)
            y = np.array([[measurement.gps_n, measurement.gps_e,
                           measurement.gps_Vg, measurement.gps_course]]).T

            L = self.P @ C.T @ np.linalg.inv(self.R_gps + C @ self.P @ C.T)

            y[3, 0] = self.wrap(y[3, 0], h[3, 0])

            self.P = (np.eye(7) - L @ C) @ self.P @ (np.eye(7) - L @ C).T + \
                     L @ self.R_gps @ L.T
            self.xhat += L @ (y - h)

            # update stored GPS signals
            self.gps_n_old = measurement.gps_n
            self.gps_e_old = measurement.gps_e
            self.gps_Vg_old = measurement.gps_Vg
            self.gps_course_old = measurement.gps_course


def jacobian(fun, x, state):
    # compute jacobian of fun with respect to x
    f = fun(x, state)
    m = f.shape[0]
    n = x.shape[0]
    eps = 0.01  # deviation
    J = np.zeros((m, n))
    for i in range(0, n):
        x_eps = np.copy(x)
        x_eps[i][0] += eps
        f_eps = fun(x_eps, state)
        df = (f_eps - f) / eps
        J[:, i] = df[:, 0]
    return J
