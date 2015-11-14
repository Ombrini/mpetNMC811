#!/usr/bin/env python2
# -*- coding: utf-8 -*-

import numpy as np
import scipy.sparse as sprs
import scipy.special as spcl

from daetools.pyDAE import *
from daetools.pyDAE.data_reporters import *
from daetools.solvers.superlu import pySuperLU

import delta_phi_fits
import mpetPorts

eps = -1e-12

# Define some variable types
mole_frac_t = daeVariableType(name="mole_frac_t", units=unit(),
        lowerBound=0, upperBound=1, initialGuess=0.25,
        absTolerance=1e-6)
elec_pot_t = daeVariableType(name="elec_pot_t", units=unit(),
        lowerBound=-1e20, upperBound=1e20, initialGuess=0,
        absTolerance=1e-5)

class mod2var(daeModel):
    def __init__(self, Name, Parent=None, Description="", ndD=None,
            ndD_s=None):
        daeModel.__init__(self, Name, Parent, Description)
        if (ndD is None) or (ndD_s is None):
            raise Exception("Need input parameter dictionary")
        self.ndD = ndD
        self.ndD_s = ndD_s

        # Domain
        self.Dmn = daeDomain("discretizationDomain", self, unit(),
                "discretization domain")

        # Variables
        self.c1 =  daeVariable("c1", mole_frac_t, self,
                "Concentration in 'layer' 1 of active particle",
                [self.Dmn])
        self.c2 =  daeVariable("c2", mole_frac_t, self,
                "Concentration in 'layer' 2 of active particle",
                [self.Dmn])
        self.cbar = daeVariable("cbar", mole_frac_t, self,
                "Average concentration in active particle")
        self.c1bar = daeVariable("c1bar", mole_frac_t, self,
                "Average concentration in 'layer' 1 of active particle")
        self.c2bar = daeVariable("c2bar", mole_frac_t, self,
                "Average concentration in 'layer' 2 of active particle")
        self.dcbardt = daeVariable("dcbardt", no_t, self,
                "Rate of particle filling")

        # Ports
        self.portInLyte = mpetPorts.portFromElyte("portInLyte",
                eInletPort, self, "Inlet port from electrolyte")
        self.portInBulk = mpetPorts.portFromBulk("portInBulk",
                eInletPort, self, "Inlet port from e- conducting phase")
        self.phi_lyte = self.portInLyte.phi_lyte()
        self.c_lyte = self.portInLyte.c_lyte()
        self.phi_m = self.portInBulk.phi_m()

    def DeclareEquations(self):
        ndD = self.ndD
        N = ndD["N"] # number of grid points in particle
        T = self.ndD_s["T"] # nondimensional temperature
        r_vec, volfrac_vec = get_unit_solid_discr(
                ndD['shape'], ndD['type'], N)

        # Prepare the Ideal Solution log ratio terms
        self.ISfuncs1 = np.array(
                [LogRatio("LR1", self, unit(), self.c1(k)) for k in
                    range(N)])
        self.ISfuncs2 = np.array(
                [LogRatio("LR2", self, unit(), self.c2(k)) for k in
                    range(N)])

        # Figure out mu_O, mu of the oxidized state
        # phi in the electron conducting phase
        phi_sld = self.phi_m
        # mu of the ionic species
        if self.ndD_s["elyteModelType"] == "SM":
            mu_lyte = self.phi_lyte
            act_lyte = None
        elif self.ndD_s["elyteModelType"] == "dilute":
            act_lyte = self.c_lyte
            mu_lyte = T*np.log(act_lyte) + self.phi_lyte
        mu_O = mu_lyte - phi_sld

        # Define average filling fractions in particle
        eq1 = self.CreateEquation("c1bar")
        eq2 = self.CreateEquation("c2bar")
        eq1.Residual = self.c1bar()
        eq2.Residual = self.c2bar()
        for k in range(N):
            eq1.Residual -= self.c1(k) * volfrac_vec[k]
            eq2.Residual -= self.c2(k) * volfrac_vec[k]
        eq = self.CreateEquation("cbar")
        eq.Residual = self.cbar() - 0.5*(self.c1bar() + self.c2bar())

        # Define average rate of filling of particle
        eq = self.CreateEquation("dcbardt")
        eq.Residual = self.dcbardt()
        for k in range(N):
            eq.Residual -= 0.5*(self.c1.dt(k) + self.c2.dt(k)) * volfrac_vec[k]

        c1 = np.empty(N, dtype=object)
        c2 = np.empty(N, dtype=object)
        c1[:] = [self.c1(k) for k in range(N)]
        c2[:] = [self.c2(k) for k in range(N)]
        if ndD["type"] in ["diffn2", "CHR2"]:
            # Equations for 1D particles of 1 field varible
            self.sldDynamics1D2var(c1, c2, mu_O, act_lyte,
                    self.ISfuncs1, self.ISfuncs2)
        elif ndD["type"] in ["homog2", "homog2_sdn"]:
            # Equations for 0D particles of 1 field variables
            self.sldDynamics0D2var(c1, c2, mu_O, act_lyte,
                    self.ISfuncs1, self.ISfuncs2)

        for eq in self.Equations:
            eq.CheckUnitsConsistency = False

    def sldDynamics0D2var(self, c1, c2, mu_O, act_lyte, ISfuncs1,
            ISfuncs2):
        raise NotImplementedError("0D 2var not implemented")
        ndD = self.ndD
        N = ndD["N"]
        T = self.ndD_s["T"]
        c_surf = c
        mu_R_surf = act_R_surf = None
        if not ndD["delPhiEqFit"]:
            mu_R_surf = mu_reg_sln(c, ndD["Omga"], T)
            act_R_surf = np.exp(mu_R_surf / T)
        eta = calc_eta(c_surf, mu_O, ndD["delPhiEqFit"], mu_R_surf, T,
                ndD["dphi_eq_ref"], ndD["delPhiFunc"])
        Rxn = calc_rxn_rate(eta, c_surf, self.c_lyte, ndD["k0"],
                T, ndD["rxnType"], act_R_surf, act_lyte, ndD["lambda"],
                ndD["alpha"])

        dcdt_vec = np.empty(N, dtype=object)
        dcdt_vec[0:N] = [self.c.dt(k) for k in range(N)]
        LHS_vec = dcdt_vec
        for k in range(N):
            eq = self.CreateEquation("dcsdt")
            eq.Residual = LHS_vec[k] - Rxn[k]
        return

    def sldDynamics1D2var(self, c1, c2, mu_O, act_lyte, ISfuncs1,
            ISfuncs2):
        ndD = self.ndD
        N = ndD["N"]
        T = self.ndD_s["T"]
        r_vec, volfrac_vec = get_unit_solid_discr(
                ndD['shape'], ndD['type'], N)
        dr = r_vec[1] - r_vec[0]
        Rs = 1. # (non-dimensionalized by itself)
        # Equations for concentration evolution
        # Mass matrix, M, where M*dcdt = RHS, where c and RHS are vectors
        if ndD['shape'] == "C3":
            Mmat = sprs.eye(N, N, format="csr")
        elif ndD['shape'] in ["sphere", "cylinder"]:
            # For discretization background, see Zeng & Bazant 2013
            # Mass matrix is common for spherical shape, diffn or CHR
            edges = np.hstack((0, (r_vec[0:-1] + r_vec[1:])/2, Rs))
            if ndD['shape'] == "sphere":
                Vp = 4./3. * np.pi * Rs**3
            elif ndD['shape'] == "cylinder":
                Vp = np.pi * Rs**2  # per unit height
            vol_vec = Vp * volfrac_vec
            M1 = sprs.diags([1./8, 3./4, 1./8], [-1, 0, 1],
                    shape=(N, N), format="csr")
            M1[1, 0] = M1[-2, -1] = 1./4
            M2 = sprs.diags(vol_vec, 0, format="csr")
            if ndD['shape'] == "sphere":
                Mmat = M1*M2
            elif ndD['shape'] == "cylinder":
                Mmat = M2

        # Get solid particle chemical potential, overpotential, reaction rate
        c1_surf = mu1_R_surf = act1_R_surf = None
        c2_surf = mu2_R_surf = act2_R_surf = None
        if ndD["type"] in ["diffn2", "CHR2"]:
            c1_surf = c1[-1]
            c2_surf = c2[-1]
        if ndD["type"] in ["CHR2"]:
            mu1_R, mu2_R = calc_mu_CHR2(c1, c2, self.c1bar(),
                    self.c2bar(), ndD["Omga"], ndD["Omgb"],
                    ndD["Omgc"], ndD["B"], ndD["kappa"], ndD["EvdW"],
                    ndD["beta_s"], T, ndD["shape"], dr, r_vec, Rs,
                    ISfuncs1, ISfuncs2)
            mu1_R_surf, mu2_R_surf = mu1_R[-1], mu2_R[-1]
            act1_R_surf = np.exp(mu1_R_surf/T)
            act2_R_surf = np.exp(mu2_R_surf/T)
        eta1 = calc_eta(c1_surf, mu_O, ndD["delPhiEqFit"], mu1_R_surf, T,
                ndD["dphi_eq_ref"], ndD["delPhiFunc"])
        eta2 = calc_eta(c2_surf, mu_O, ndD["delPhiEqFit"], mu2_R_surf, T,
                ndD["dphi_eq_ref"], ndD["delPhiFunc"])
        Rxn1 = calc_rxn_rate(eta1, c1_surf, self.c_lyte, ndD["k0"],
                T, ndD["rxnType"], act1_R_surf, act_lyte, ndD["lambda"],
                ndD["alpha"])
        Rxn2 = calc_rxn_rate(eta2, c2_surf, self.c_lyte, ndD["k0"],
                T, ndD["rxnType"], act2_R_surf, act_lyte, ndD["lambda"],
                ndD["alpha"])

        # Get solid particle fluxes (if any) and RHS
        if ndD["type"] in ["diffn2", "CHR2"]:
            Flux1_bc = 0.5 * ndD["delta_L"] * Rxn1
            Flux2_bc = 0.5 * ndD["delta_L"] * Rxn2
            if ndD["type"] == "diffn2":
                Flux1_vec, Flux2_vec = calc_Flux_diffn2(c1, c2,
                        ndD["Dsld"], Flux1_bc, Flux2_bc, dr, T)
            elif ndD["type"] == "CHR2":
                Flux1_vec, Flux2_vec = calc_Flux_CHR2(c1, c2, mu1_R, mu2_R,
                        ndD["Dsld"], Flux1_bc, Flux2_bc, dr, T)
            if ndD["shape"] == "sphere":
                area_vec = 4*np.pi*edges**2
            elif ndD["shape"] == "cylinder":
                area_vec = 2*np.pi*edges  # per unit height
            RHS1 = np.diff(Flux1_vec * area_vec)
            RHS2 = np.diff(Flux2_vec * area_vec)
#            kinterlayer = 1e2
#            interLayerRxn = (kinterlayer * (1 - c1_sld) *
#                    (1 - c2_sld) * (act1_R - act2_R))
#            RxnTerm1 = -interLayerRxn
#            RxnTerm2 = interLayerRxn
            RxnTerm1 = 0
            RxnTerm2 = 0
            RHS1 += RxnTerm1
            RHS2 += RxnTerm2

        dc1dt_vec = np.empty(N, dtype=object)
        dc2dt_vec = np.empty(N, dtype=object)
        dc1dt_vec[0:N] = [self.c1.dt(k) for k in range(N)]
        dc2dt_vec[0:N] = [self.c2.dt(k) for k in range(N)]
        LHS1_vec = MX(Mmat, dc1dt_vec)
        LHS2_vec = MX(Mmat, dc2dt_vec)
        for k in range(N):
            eq1 = self.CreateEquation("dc1sdt_discr{k}".format(k=k))
            eq2 = self.CreateEquation("dc2sdt_discr{k}".format(k=k))
            eq1.Residual = LHS1_vec[k] - RHS1[k]
            eq2.Residual = LHS2_vec[k] - RHS2[k]
#            eq.Residual = (LHS_vec[k] - RHS_c[k] + noisevec[k]()) # NOISE
        return

class mod1var(daeModel):
    def __init__(self, Name, Parent=None, Description="", ndD=None,
            ndD_s=None):
        daeModel.__init__(self, Name, Parent, Description)

        if (ndD is None) or (ndD_s is None):
            raise Exception("Need input parameter dictionary")
        self.ndD = ndD
        self.ndD_s = ndD_s

        # Domain
        self.Dmn = daeDomain("discretizationDomain", self, unit(),
                "discretization domain")

        # Variables
        self.c =  daeVariable("c", mole_frac_t, self,
                "Concentration in active particle",
                [self.Dmn])
        self.cbar = daeVariable("cbar", mole_frac_t, self,
                "Average concentration in active particle")
        self.dcbardt = daeVariable("dcbardt", no_t, self,
                "Rate of particle filling")
        if (self.ndD["type"] == "ACR") and self.ndD["simSurfCond"]:
            self.phi = daeVariable("phi", elec_pot_t, self,
                    "Electric potential within the particle",
                    [self.Dmn])
        else:
            self.ndD["simSurfCond"] = False
            self.phi = False

        # Ports
        self.portInLyte = mpetPorts.portFromElyte("portInLyte",
                eInletPort, self, "Inlet port from electrolyte")
        self.portInBulk = mpetPorts.portFromBulk("portInBulk",
                eInletPort, self, "Inlet port from e- conducting phase")
        self.phi_lyte = self.portInLyte.phi_lyte()
        self.c_lyte = self.portInLyte.c_lyte()
        self.phi_m = self.portInBulk.phi_m()

    def DeclareEquations(self):
        ndD = self.ndD
        N = ndD["N"] # number of grid points in particle
        T = self.ndD_s["T"] # nondimensional temperature
        r_vec, volfrac_vec = get_unit_solid_discr(
                ndD['shape'], ndD['type'], N)

        # Figure out mu_O, mu of the oxidized state
        # phi in the electron conducting phase
        if ndD["simSurfCond"]:
            phi_sld = np.empty(N, dtype=object)
            phi_sld[:] = [self.phi(k) for k in range(N)]
        else:
            phi_sld = self.phi_m
        # mu of the ionic species
        if self.ndD_s["elyteModelType"] == "SM":
            mu_lyte = self.phi_lyte
            act_lyte = None
        elif self.ndD_s["elyteModelType"] == "dilute":
            act_lyte = self.c_lyte
            mu_lyte = T*np.log(act_lyte) + self.phi_lyte
        mu_O = mu_lyte - phi_sld

        # Define average filling fraction in particle
        eq = self.CreateEquation("cbar")
        eq.Residual = self.cbar()
        for k in range(N):
            eq.Residual -= self.c(k) * volfrac_vec[k]

        # Define average rate of filling of particle
        eq = self.CreateEquation("dcbardt")
        eq.Residual = self.dcbardt()
        for k in range(N):
            eq.Residual -= self.c.dt(k) * volfrac_vec[k]

        c = np.empty(N, dtype=object)
        c[:] = [self.c(k) for k in range(N)]
        if ndD["type"] in ["ACR", "diffn", "CHR"]:
            # Equations for 1D particles of 1 field varible
            self.sldDynamics1D1var(c, mu_O, act_lyte)
        elif ndD["type"] in ["homog", "homog_sdn"]:
            # Equations for 0D particles of 1 field variables
            self.sldDynamics0D1var(c, mu_O, act_lyte)

        # Equations for potential drop along particle, if desired
        if ndD['simSurfCond']:
            # Conservation of charge in the solid particles with
            # Ohm's Law
#            LHS = self.calc_part_surf_LHS()
            phi_tmp = np.empty(N + 2, dtype=object)
            phi_tmp[1:-1] = [self.phi(k) for k in range(N)]
            # BC's -- touching e- supply on both sides
            phi_tmp[0] = self.phi_m
            phi_tmp[-1] = self.phi_m
            dx = 1./N
            phi_edges (phi_tmp[0:-1] + phi_tmp[1:])/2.
            scond_vec = ndD["scond"] * np.exp(-1*(phi_edges - self.phi_m))
            curr_dens = -scond_vec * (np.diff(phi_tmp, 1) / dx)
            LHS = np.diff(curr_dens, 1)/dx
            k0_part = ndD["k0"]
            for k in range(N):
                eq = self.CreateEquation(
                        "charge_cons_discr{k}".format(
                            i=i,j=j,k=k,l=l))
                RHS = self.c.dt(k) / k0_part
                eq.Residual = LHS[k] - RHS

        for eq in self.Equations:
            eq.CheckUnitsConsistency = False

    def sldDynamics0D1var(self, c, mu_O, act_lyte):
        ndD = self.ndD
        N = ndD["N"]
        T = self.ndD_s["T"]
        c_surf = c
        mu_R_surf = act_R_surf = None
        if not ndD["delPhiEqFit"]:
            mu_R_surf = mu_reg_sln(c, ndD["Omga"], T)
            act_R_surf = np.exp(mu_R_surf / T)
        eta = calc_eta(c_surf, mu_O, ndD["delPhiEqFit"], mu_R_surf, T,
                ndD["dphi_eq_ref"], ndD["delPhiFunc"])
        Rxn = calc_rxn_rate(eta, c_surf, self.c_lyte, ndD["k0"],
                T, ndD["rxnType"], act_R_surf, act_lyte, ndD["lambda"],
                ndD["alpha"])

        dcdt_vec = np.empty(N, dtype=object)
        dcdt_vec[0:N] = [self.c.dt(k) for k in range(N)]
        LHS_vec = dcdt_vec
        for k in range(N):
            eq = self.CreateEquation("dcsdt")
            eq.Residual = LHS_vec[k] - Rxn[k]
        return

    def sldDynamics1D1var(self, c, mu_O, act_lyte):
        ndD = self.ndD
        N = ndD["N"]
        T = self.ndD_s["T"]
        r_vec, volfrac_vec = get_unit_solid_discr(
                ndD['shape'], ndD['type'], N)
        # Equations for concentration evolution
        # Mass matrix, M, where M*dcdt = RHS, where c and RHS are vectors
        if ndD['shape'] == "C3":
            Mmat = sprs.eye(N, N, format="csr")
        elif ndD['shape'] in ["sphere", "cylinder"]:
            # For discretization background, see Zeng & Bazant 2013
            # Mass matrix is common for spherical shape, diffn or CHR
            Rs = 1. # (non-dimensionalized by itself)
            edges = np.hstack((0, (r_vec[0:-1] + r_vec[1:])/2, Rs))
            if ndD['shape'] == "sphere":
                Vp = 4./3. * np.pi * Rs**3
            elif ndD['shape'] == "cylinder":
                Vp = np.pi * Rs**2  # per unit height
            vol_vec = Vp * volfrac_vec
            dr = r_vec[1] - r_vec[0]
            M1 = sprs.diags([1./8, 3./4, 1./8], [-1, 0, 1],
                    shape=(N, N), format="csr")
            M1[1, 0] = M1[-2, -1] = 1./4
            M2 = sprs.diags(vol_vec, 0, format="csr")
            if ndD['shape'] == "sphere":
                Mmat = M1*M2
            elif ndD['shape'] == "cylinder":
                Mmat = M2

        # Get solid particle chemical potential, overpotential, reaction rate
        c_surf = mu_R_surf = act_R_surf = None
        if ndD["type"] in ["ACR"]:
            c_surf = c
            mu_R_surf = calc_mu_ACR(c, self.cbar(), ndD["Omga"], ndD["B"],
                    ndD["kappa"], T, ndD["cwet"])
            act_R_surf = np.exp(mu_R_surf / T)
        elif ndD["type"] in ["diffn", "CHR"]:
            c_surf = c[-1]
        if ndD["type"] in ["CHR"]:
            mu_R = calc_mu_CHR(c, self.cbar(), ndD["Omga"], ndD["B"],
                    ndD["kappa"], T, ndD["beta_s"],
                    ndD['shape'], dr, r_vec, Rs)
            mu_R_surf = mu_R[-1]
            act_R_surf = np.exp(mu_R_surf / T)
        eta = calc_eta(c_surf, mu_O, ndD["delPhiEqFit"], mu_R_surf, T,
                ndD["dphi_eq_ref"], ndD["delPhiFunc"])
        Rxn = calc_rxn_rate(eta, c_surf, self.c_lyte, ndD["k0"],
                T, ndD["rxnType"], act_R_surf, act_lyte, ndD["lambda"],
                ndD["alpha"])

        # Get solid particle fluxes (if any) and RHS
        if ndD["type"] in ["ACR"]:
            RHS = Rxn
        elif ndD["type"] in ["diffn", "CHR"]:
            Flux_bc = ndD["delta_L"] * Rxn
            if ndD["type"] == "diffn":
                Flux_vec = calc_Flux_diffn(c, ndD["Dsld"], Flux_bc, dr, T)
            elif ndD["type"] == "CHR":
                Flux_vec = calc_Flux_CHR(c, mu_R, ndD["Dsld"], Flux_bc, dr, T)
            if ndD["shape"] == "sphere":
                area_vec = 4*np.pi*edges**2
            elif ndD["shape"] == "cylinder":
                area_vec = 2*np.pi*edges  # per unit height
            RHS = np.diff(Flux_vec * area_vec)

        dcdt_vec = np.empty(N, dtype=object)
        dcdt_vec[0:N] = [self.c.dt(k) for k in range(N)]
        LHS_vec = MX(Mmat, dcdt_vec)
        for k in range(N):
            eq = self.CreateEquation("dcsdt_discr{k}".format(k=k))
            eq.Residual = LHS_vec[k] - RHS[k]
#            eq.Residual = (LHS_vec[k] - RHS_c[k] + noisevec[k]()) # NOISE

        return

class LogRatio(daeScalarExternalFunction):
    """
    Class to make a piecewise function that evaluates
    log(c/(1-c)). However, near the edges (close to zero and one),
    extend the function linearly to avoid negative log errors and
    allow concentrations above one and below zero.
    """
    def __init__(self, Name, Model, units, c):
        arguments = {}
        arguments["c"] = c
        daeScalarExternalFunction.__init__(self, Name, Model, units,
                arguments)

    def Calculate(self, values):
        c = values["c"]
        cVal = c.Value
        EPS = 1e-6
        cL = EPS
        cH = 1 - EPS
        if cVal < cL:
            logRatio = (1./(cL*(1-cL)))*(cVal-cL) + np.log(cL/(1-cL))
        elif cVal > cH:
            logRatio = (1./(cH*(1-cH)))*(cVal-cH) + np.log(cH/(1-cH))
        else:
            logRatio = np.log(cVal/(1-cVal))
        logRatio = adouble(logRatio)
        if c.Derivative != 0:
            if cVal < cL:
                logRatio.Derivative = 1./(cL*(1-cL))
            elif cVal > cH:
                logRatio.Derivative = 1./(cH*(1-cH))
            else:
                logRatio.Derivative = 1./(cVal*(1-cVal))
            logRatio.Derivative *= c.Derivative
        return logRatio

class noise(daeScalarExternalFunction):
    def __init__(self, Name, Model, units, time, time_vec,
            noise_data, previous_output, position):
        arguments = {}
        self.counter = 0
        self.saved = 0
        self.previous_output = previous_output
        self.time_vec = time_vec
        self.noise_data = noise_data
        self.interp = sint.interp1d(time_vec, noise_data, axis=0)
#        self.tlo = time_vec[0]
#        self.thi = time_vec[-1]
#        self.numnoise = len(time_vec)
        arguments["time"] = time
        self.position = position
        daeScalarExternalFunction.__init__(self, Name, Model, units, arguments)

    def Calculate(self, values):
        time = values["time"]
        # A derivative for Jacobian is requested - return always 0.0
        if time.Derivative != 0:
            return adouble(0)
        # Store the previous time value to prevent excessive
        # interpolation.
        if len(self.previous_output) > 0 and self.previous_output[0] == time.Value:
            self.saved += 1
            return adouble(float(self.previous_output[1][self.position]))
        noise_vec = self.interp(time.Value)
        self.previous_output[:] = [time.Value, noise_vec] # it is a list now not a tuple
        self.counter += 1
        return adouble(noise_vec[self.position])
#        indx = (float(time.Value - self.tlo)/(self.thi-self.tlo) *
#                (self.numnoise - 1))
#        ilo = np.floor(indx)
#        ihi = np.ceil(indx)
#        # If we're exactly at a time in time_vec
#        if ilo == ihi:
#            noise_vec = self.noise_data[ilo, :]
#        else:
#            noise_vec = (self.noise_data[ilo, :] +
#                    (time.Value - self.time_vec[ilo]) /
#                    (self.time_vec[ihi] - self.time_vec[ilo]) *
#                    (self.noise_data[ihi, :] - self.noise_data[ilo, :])
#                    )
#        # previous_output is a reference to a common object and must
#        # be updated here - not deleted.  using self.previous_output = []
#        # it will delete the common object and create a new one
#        self.previous_output[:] = [time.Value, noise_vec] # it is a list now not a tuple
#        self.counter += 1
#        return adouble(float(noise_vec[self.position]))

def calc_rxn_rate(eta, c_sld, c_lyte, k0, T, rxnType,
        act_R=None, act_lyte=None, lmbda=None, alpha=None):
    if rxnType == "Marcus":
        Rate = R_Marcus(k0, lmbda, c_lyte, c_sld, eta, T)
    elif rxnType == "BV":
        Rate = R_BV(k0, alpha, c_sld, act_lyte, act_R, eta, T)
    elif rxnType == "MHC":
        k0_MHC = k0/MHC_kfunc(0., lmbda)
        Rate = R_MHC(k0_MHC, lmbda, eta, T, c_sld, c_lyte)
    elif rxnType == "BV_mod01":
        Rate = R_BV_mod01(k0, alpha, c_sld, c_lyte, eta, T)
    elif rxnType == "BV_mod02":
        Rate = R_BV_mod02(k0, alpha, c_sld, c_lyte, eta, T)
    return Rate

def calc_eta(c, mu_O, delPhiEqFit, mu_R=None, T=None, dphi_eq_ref=None,
        material=None):
    if delPhiEqFit:
        fits = delta_phi_fits.DPhiFits(T)
        phifunc = fits.materialData[material]
        delta_phi_eq = phifunc(c, dphi_eq_ref)
        mu_R = -delta_phi_eq
    eta = mu_R - mu_O
    return eta

def get_unit_solid_discr(Shape, Type, N):
    if Shape == "C3" and Type in ["ACR"]:
        r_vec = None
        # For 1D particle, the vol fracs are simply related to the
        # length discretization
        volfrac_vec = (1./N) * np.ones(N)  # scaled to 1D particle volume
    elif Type in ["homog", "homog_sdn"]:
        r_vec = None
        volfrac_vec = np.ones(1)
    elif Shape == "sphere":
        Rs = 1.
        dr = Rs/(N - 1)
        r_vec = np.linspace(0, Rs, N)
        vol_vec = 4*np.pi*(r_vec**2 * dr + (1./12)*dr**3)
        vol_vec[0] = 4*np.pi*(1./24)*dr**3
        vol_vec[-1] = (4./3)*np.pi*(Rs**3 - (Rs - dr/2.)**3)
        Vp = 4./3.*np.pi*Rs**3
        volfrac_vec = vol_vec/Vp
    elif Shape == "cylinder":
        Rs = 1.
        h = 1.
        dr = Rs / (N - 1)
        r_vec = np.linspace(0, Rs, N)
        vol_vec = np.pi * h * 2 * r_vec * dr
        vol_vec[0] = np.pi * h * dr**2 / 4.
        vol_vec[-1] = np.pi * h * (Rs * dr - dr**2 / 4.)
        Vp = np.pi * Rs**2 * h
        volfrac_vec = vol_vec / Vp
    else:
        raise NotImplementedError("Fix shape volumes!")
    return r_vec, volfrac_vec

def calc_mu_CHR(c, cbar, Omga, B, kappa, T, beta_s, particleShape, dr,
        r_vec, Rs):
    mu_R = ( mu_reg_sln(c, Omga, T) +
            B*(c - cbar) )
    curv = calc_curv_c(c, dr, r_vec, Rs, beta_s, particleShape)
    mu_R -= kappa*curv
    return mu_R

def calc_mu_CHR2(c1, c2, c1bar, c2bar, Omga, Omgb, Omgc, B, kappa,
        EvdW, beta_s, T, particleShape, dr, r_vec, Rs, ISfuncs1=None,
        ISfuncs2=None):
    N = len(c1)
    mu1_R = ( mu_reg_sln(c1, Omga, T, ISfuncs1) +
            B*(c1 - c1bar) )
    mu2_R = ( mu_reg_sln(c2, Omga, T, ISfuncs2) +
            B*(c2 - c2bar) )
    mu1_R += EvdW * (30 * c1**2 * (1-c1)**2)
    mu2_R += EvdW * (30 * c2**2 * (1-c2)**2)
    curv1 = calc_curv_c(c1, dr, r_vec, Rs, beta_s, particleShape)
    curv2 = calc_curv_c(c2, dr, r_vec, Rs, beta_s, particleShape)
    mu1_R -= kappa*curv1
    mu2_R -= kappa*curv2
    mu1_R += Omgb*c2 + Omgc*c2*(1-c2)*(1-2*c1)
    mu2_R += Omgb*c1 + Omgc*c1*(1-c1)*(1-2*c2)
    return mu1_R, mu2_R

def calc_mu_ACR(c, cbar, Omga, B, kappa, T, cwet, ISfuncs=None):
    N = len(c)
    ctmp = np.empty(N + 2, dtype=object)
    ctmp[1:-1] = c
    ctmp[0] = cwet
    ctmp[-1] = cwet
    dxs = 1./N
    curv = np.diff(ctmp, 2)/(dxs**2)
    mu_R = ( mu_reg_sln(c, Omga, T) - kappa*curv
            + B*(c - cbar) )
    return mu_R

def calc_Flux_diffn(c, Ds, Flux_bc, dr, T):
    N = len(c)
    Flux_vec = np.empty(N+1, dtype=object)
    Flux_vec[0] = 0 # Symmetry at r=0
    Flux_vec[-1] = Flux_bc
    Flux_vec[1:N] = Ds/T * np.diff(c)/dr
    return Flux_vec

def calc_Flux_CHR(c, mu, Ds, Flux_bc, dr, T):
    N = len(c)
    Flux_vec = np.empty(N+1, dtype=ojbect)
    Flux_vec[0] = 0 # Symmetry at r=0
    Flux_vec[-1] = Flux_bc
    c_edges = 2*(c[0:-1] * c[1:])/(c[0:-1] + c[1:])
    # Keep the concentration between 0 and 1
    c_edges = np.array([Max(1e-6, c_edges[i]) for i in range(N)])
    c_edges = np.array([Min(1-1e-6, c_edges[i]) for i in range(N)])
    Flux_vec[1:N] = (Ds/T * (1-c_edges) * c_edges *
            np.diff(mu)/dr)
    return Flux_vec

def calc_Flux_CHR2(c1, c2, mu1_R, mu2_R, Ds, Flux1_bc, Flux2_bc, dr, T):
    if type(c1[0]) == pyCore.adouble:
        MIN, MAX = Min, Max
    else:
        MIN, MAX = min, max
    N = len(c1)
    Flux1_vec = np.empty(N+1, dtype=object)
    Flux2_vec = np.empty(N+1, dtype=object)
    Flux1_vec[0] = 0. # symmetry at r=0
    Flux2_vec[0] = 0. # symmetry at r=0
    Flux1_vec[-1] = Flux1_bc
    Flux2_vec[-1] = Flux2_bc
    c1_edges = 2*(c1[0:-1] * c1[1:])/(c1[0:-1] + c1[1:])
    c2_edges = 2*(c2[0:-1] * c2[1:])/(c2[0:-1] + c2[1:])
    # keep the concentrations between 0 and 1
    c1_edges = np.array([MAX(1e-6, c1_edges[i]) for i in
            range(len(c1_edges))])
    c1_edges = np.array([MIN((1-1e-6), c1_edges[i]) for i in
            range(len(c1_edges))])
    c2_edges = np.array([MAX(1e-6, c2_edges[i]) for i in
            range(len(c1_edges))])
    c2_edges = np.array([MIN((1-1e-6), c2_edges[i]) for i in
            range(len(c1_edges))])
    cbar_edges = 0.5*(c1_edges + c2_edges)
    Flux1_vec[1:N] = (Ds/T * (1 - c1_edges)**(1.0) * c1_edges *
            np.diff(mu1_R)/dr)
    Flux2_vec[1:N] = (Ds/T * (1 - c2_edges)**(1.0) * c2_edges *
            np.diff(mu2_R)/dr)
    return Flux1_vec, Flux2_vec

def calc_curv_c(c, dr, r_vec, Rs, beta_s, particleShape):
    N = len(c)
    curv = np.empty(N, dtype=object)
    if particleShape == "sphere":
        curv[0] = 3 * (2*c[1] - 2*c[0]) / dr**2
        curv[1:N-1] = (np.diff(c, 2)/dr**2 +
                (c[2:] - c[0:-2])/(dr*r_vec[1:-1]))
        curv[N-1] = ((2./Rs)*beta_s +
                (2*c[-2] - 2*c[-1] + 2*dr*beta_s)/dr**2)
    elif particleShape == "cylinder":
        curv[0] = 2 * (2*c[1] - 2*c[0]) / dr**2
        curv[1:N-1] = (np.diff(c, 2)/dr**2 +
                (c[2:] - c[0:-2])/(2 * dr*r_vec[1:-1]))
        curv[N-1] = ((1./Rs)*beta_s +
                (2*c[-2] - 2*c[-1] + 2*dr*beta_s)/dr**2)
    else:
        raise NotImplementedError("calc_curv_c only for sphere and cylinder")
    return curv

def mu_reg_sln(c, Omga, T, ISfunc=None):
    enthalpyTerm = np.array([Omga*(1-2*c[i]) for i in range(len(c))])
    if (type(c[0]) == pyCore.adouble) and (ISfunc is not None):
        ISterm = T*np.array([ISfunc[i]() for i in range(len(c))])
    else:
        ISterm = T*np.array([np.log(c[i]/(1-c[i])) for i in
            range(len(c))])
    return ISterm + enthalpyTerm

def R_BV(k0, alpha, c_sld, act_lyte, act_R, eta, T):
    gamma_ts = (1./(1-c_sld))
    ecd = ( k0 * act_lyte**(1-alpha)
            * act_R**(alpha) / gamma_ts )
    Rate = ( ecd *
        (np.exp(-alpha*eta/T) - np.exp((1-alpha)*eta/T)) )
    return Rate

def R_BV_mod01(k0, alpha, c_sld, c_lyte, eta, T):
    # Fuller, Doyle, Newman 1994, Mn2O4
    ecd = ( k0 * c_lyte**(1-alpha) * (1.0 - c_sld)**(1 - alpha) *
            c_sld**alpha )
    Rate = ( ecd *
        (np.exp(-alpha*eta/T) - np.exp((1-alpha)*eta/T)) )
    return Rate

def R_BV_mod02(k0, alpha, c_sld, c_lyte, eta, T):
    # Fuller, Doyle, Newman 1994, carbon coke
    ecd = ( k0 * c_lyte**(1-alpha) * (0.5 - c_sld)**(1 - alpha) *
            c_sld**alpha )
    Rate = ( ecd *
        (np.exp(-alpha*eta/T) - np.exp((1-alpha)*eta/T)) )
    return Rate

def R_Marcus(k0, lmbda, c_lyte, c_sld, eta, T):
    if type(c_sld) == np.ndarray:
        c_sld = np.array([Max(eps, c_sld[i]) for i in
            range(len(c_sld))])
    else:
        c_sld = Max(eps, c_sld)
    alpha = 0.5*(1 + (T/lmbda) * np.log(Max(eps, c_lyte)/c_sld))
    # We'll assume c_e = 1 (at the standard state for electrons)
#        ecd = ( k0 * np.exp(-lmbda/(4.*T)) *
#        ecd = ( k0 *
    ecd = ( k0 * (1-c_sld) *
            c_lyte**((3-2*alpha)/4.) *
            c_sld**((1+2*alpha)/4.) )
    Rate = ( ecd * np.exp(-eta**2/(4.*T*lmbda)) *
        (np.exp(-alpha*eta/T) - np.exp((1-alpha)*eta/T)) )
    return Rate

def MHC_kfunc(eta, lmbda):
    a = 1. + np.sqrt(lmbda)
    if type(eta) == pyCore.adouble:
        ERF = Erf
    else:
        ERF = spcl.erf
    # evaluate with eta for oxidation, -eta for reduction
    return (np.sqrt(np.pi*lmbda) / (1 + np.exp(-eta))
            * (1. - ERF((lmbda - np.sqrt(a + eta**2))
                / (2*np.sqrt(lmbda)))))

def R_MHC(k0, lmbda, eta, T, c_sld, c_lyte):
    # See Zeng, Smith, Bai, Bazant 2014
    # Convert to "MHC overpotential"
    eta_f = eta + T*np.log(c_lyte/c_sld)
    gamma_ts = 1./(1. - c_sld)
    if type(eta) == np.ndarray:
        Rate = np.empty(len(eta), dtype=object)
        for i, etaval in enumerate(eta):
            krd = k0*MHC_kfunc(-eta_f[i], lmbda)
            kox = k0*MHC_kfunc(eta_f[i], lmbda)
            Rate[i] = (1./gamma_ts[i])*(krd*c_lyte - kox*c_sld[i])
    else:
        krd = k0*MHC_kfunc(-eta_f, lmbda)
        kox = k0*MHC_kfunc(eta_f, lmbda)
        Rate = (1./gamma_ts)*(krd*c_lyte - kox*c_sld)
    return Rate

def MX(mat, objvec):
    if type(mat) is not sprs.csr.csr_matrix:
        raise Exception("MX function designed for csr mult")
    n = objvec.shape[0]
    if (type(objvec[0]) == pyCore.adouble):
        out = np.empty(n, dtype=object)
    else:
        out = np.zeros(n, dtype=float)
    # Loop through the rows
    for i in range(n):
        low = mat.indptr[i]
        up = mat.indptr[i+1]
        if up > low:
            out[i] = np.sum(
                    mat.data[low:up] * objvec[mat.indices[low:up]] )
        else:
            out[i] = 0.0
    return out
