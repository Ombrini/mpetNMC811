r"""
This module provides functions defining properties of the ion-conducting
phase -- the electrolyte Manage functions for the parameters involved in
Stefan-Maxwell based concentrated electrolyte transport theory for
binary electrolytes.

Each electrolyte set must output functions for the following as a
function of c (electrolyte concentration, M)
 - Dchem [m^2/s] = the prefactor for grad(c) in species conservation
 - sigma [S/m] = the conductivity
 - (1 + dln(f_\pm)/dln(c)) = the "thermodynamic factor"
 - t_+^0 = the transference number of the cations
"""

import numpy as np

cref = 1.  # M
Tref = 298.  # K
N_A = 6.022e23
k = 1.381e-23
e = 1.602e-19


def LiClO4_PC():
    """ Set of parameters from Fuller, Doyle, Newman 1994, with
    conductivity directly from dualfoil5.2.f
    """
    def tp0(c):
        return 0.2

    def D(c):
        return 2.58e-10  # m^2/s

    def therm_fac(c):
        return 1.

    def sigma(cin):
        c = cin * 1000  # mol/m^3
        p_max = 0.542
        p_u = 0.6616
        a = 0.855
        b = -0.08
        rho = 1.2041e3
        out = 0.0001 + c**a * (
            p_max*(1./(rho*p_u))**a
            * np.exp(b*(c/rho - p_u)**2
                     - (a/p_u)*(c/rho - p_u)))  # S/m
        return out
    Dref = D(cref)

    def D_ndim(c):
        return D(c) / Dref

    def sigma_ndim(c):
        return sigma(c) * (
            k*Tref/(e**2*Dref*N_A*(1000*cref)))
    return D_ndim, sigma_ndim, therm_fac, tp0, Dref


def valoen_reimers():
    """ Set of parameters from Valoen and Reimers 2005 """
    def tp0(c):
        return 0.38

    def D(c):
        return (
            10**(-4) * 10**(-4.43 - 54/(Tref - (229 + 5*c)) - 0.22*c))  # m^2/s

    def therm_fac(c):
        tmp = 0.601 - 0.24*c**(0.5) + 0.982*(1 - 0.0052*(Tref - 294))*c**(1.5)
        return tmp/(1-tp0(c))

    def sigma(c):
        (k00, k01, k02,
         k10, k11, k12,
         k20, k21) = (
             -10.5, 0.0740, -6.96e-5,
             0.668, -0.0178, 2.80e-5,
             0.494, -8.86e-4)
        out = c * (k00 + k01*Tref + k02*Tref**2
                   + k10*c + k11*c*Tref + k12*c*Tref**2
                   + k20*c**2 + k21*c**2*Tref)**2  # mS/cm
        out *= 0.1  # S/m
        return out
    Dref = D(cref)

    def D_ndim(c):
        return D(c) / Dref

    def sigma_ndim(c):
        return sigma(c) * (
            k*Tref/(e**2*Dref*N_A*(1000*cref)))
    return D_ndim, sigma_ndim, therm_fac, tp0, Dref


def valoen_bernardi():
    """ Set of parameters from Bernardi and Go 2011, indirectly from
    Valoen and Reimers 2005. The only change from Valoen and Reimers
    is the conductivity.
    """
    D_ndim, Ign, therm_fac, tp0, Dref = valoen_reimers()

    def sigma(c):
        (k00, k01, k02,
         k10, k11, k12,
         k20, k21) = (
            -8.2488, 0.053248, -0.000029871,
            0.26235, -0.0093063, 0.000008069,
            0.22002, -0.0001765)
        out = c * (k00 + k01*Tref + k02*Tref**2
                   + k10*c + k11*c*Tref + k12*c*Tref**2
                   + k20*c**2 + k21*c**2*Tref)**2  # mS/cm
        out *= 0.1  # S/m
        return out

    def sigma_ndim(c):
        return sigma(c) * (
            k*Tref/(e**2*Dref*N_A*(1000*cref)))
    return D_ndim, sigma_ndim, therm_fac, tp0, Dref


def Solid_elyte_func():
    """
    Solid Electrolyte version, several sources for different params
    """
    # LCO: kappa_ndim is not actually returned, so unclear
    # what it should be used for
    # related functions and values commented out for now

    tp0 = 0.9  # tp0 is constant but a callable must be returned
    D = 1.19e-11  # m^2/s
    # kappa = 1.2e-3  # S/m

    # def kappa_valoen_reimers(c):
    #     k00, k01, k02, k10, k11, k12, k20, k21 = (-10.5, 0.0740, -6.96e-5, 0.668,
    #                                               -0.0178, 2.80e-5, 0.494, -8.86e-4)
    #     out = c * (k00 + k01*Tref + k02*Tref**2
    #                + k10*c + k11*c*Tref + k12*c*Tref**2
    #                + k20*c**2 + k21*c**2*Tref)**2  # mS/cm
    #     out *= 0.1  # S/m
    #     return out

    Ign1, sigma_ndim, thermFac, Ign3, Dref = valoen_reimers()
    D_ndim = D / Dref
    # kappa_ndim = lambda c: kappa / kappa_valoen_reimers(c)

    # D_ndim and tp0 are constants, but a callable must be returned
    return lambda c: D_ndim, sigma_ndim, thermFac, lambda c: tp0, Dref


def test1():
    """Set of dilute solution parameters with zp=|zm|=nup=num=1,
    Dp = 2.2e-10 m^2/s
    Dm = 2.94e-10 m^2/s
    """
    Dp = 2.2e-10
    Dm = 2.94e-10

    def D(c):
        return (2*Dp*Dm/(Dp+Dm))  # m^2/s

    def therm_fac(c):
        return 1.

    def tp0(c):
        return Dp/(Dp+Dm)

    def sigma(c):
        return Dm*(1000*c)*N_A*e**2/(k*Tref*(1-tp0(c)))  # S/m
    Dref = D(cref)

    def D_ndim(c):
        return D(c) / Dref

    def sigma_ndim(c):
        return sigma(c) * (
            k*Tref/(e**2*Dref*N_A*(1000*cref)))
    return D_ndim, sigma_ndim, therm_fac, tp0, Dref


def LIONSIMBA():
    """ Set of parameters from LIONSIMBA validation. Torchio et al, 2016.
    """
    T = 298  # isothermal model

    def tp0(c):
        return 0.364

    def sigma(c):
        c_dim = c*1000  # dimensionalized c
        r1 = -10.5
        r2 = 0.668e-3
        r3 = 0.494e-6
        r4 = 0.074
        r5 = -1.78e-5
        r6 = -8.86e-10
        r7 = -6.96e-5
        r8 = 2.8e-8
        sig_out = 1e-4 * c_dim * (r1 + r2*c_dim + r3*c_dim**2
                                  + T*(r4 + r5*c_dim + r6*c_dim**2)
                                  + T**2 * (r7 + r8*c_dim))**2
        return sig_out  # m^2/s

    def D(c):
        c_dim = c*1000
        T = 298
        r1 = 4.43
        r2 = 54
        r3 = 229
        r4 = 5e-3
        r5 = 0.22e-3
        D_out = 1e-4 * 10**(-r1-r2/(T-r3-r4*c_dim)-r5*c_dim)
        return D_out

    def therm_fac(c):
        return 1.

    Dref = D(cref)

    def D_ndim(c):
        return D(c) / Dref

    def sigma_ndim(c):
        return sigma(c) * (
            k*Tref/(e**2*Dref*N_A*(1000*cref)))
    return D_ndim, sigma_ndim, therm_fac, tp0, Dref


def LIONSIMBA_isothermal():
    """ Set of parameters from LIONSIMBA validation. Torchio et al, 2016.
    """
    # isothermal at 298 K

    def tp0(c):
        return 0.364

    def sigma(c):
        ce = c*1000  # dimensionalized c
        return 4.1253e-2 + 5.007e-4*ce - 4.7212e-7*ce**2 \
            + 1.5094e-10*ce**3 - 1.6018*1e-14*ce**4  # S/m

    def D(c):
        return 7.5e-10  # m^2/s

    def therm_fac(c):
        return 1.

    Dref = D(cref)

    def D_ndim(c):
        return D(c) / Dref

    def sigma_ndim(c):
        return sigma(c) * (
            k*Tref/(e**2*Dref*N_A*(1000*cref)))
    return D_ndim, sigma_ndim, therm_fac, tp0, Dref
