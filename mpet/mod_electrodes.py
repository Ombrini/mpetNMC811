"""These models define individual particles of active material.

This includes the equations for both 1-parameter models and 2-parameters models defining
 - mass conservation (concentration evolution)
 - reaction rate at the surface of the particles
In each model class it has options for different types of particles:
 - homogeneous
 - Fick-like diffusion
 - Cahn-Hilliard (with reaction boundary condition)
 - Allen-Cahn (with reaction throughout the particle)
These models can be instantiated from the mod_cell module to simulate various types of active
materials within a battery electrode.
"""
import daetools.pyDAE as dae
import numpy as np
import scipy.sparse as sprs
import scipy.interpolate as sintrp

import mpet.geometry as geo
import mpet.ports as ports
import mpet.props_am as props_am
import mpet.utils as utils
from mpet.daeVariableTypes import mole_frac_t


class Mod2D(dae.daeModel):
    def __init__(self, config, trode, vInd, pInd,
                 Name, Parent=None, Description=""):
        super().__init__(Name, Parent, Description)

        self.config = config
        self.trode = trode
        self.ind = (vInd, pInd)

        # Domain
        self.Dmn = dae.daeDomain("discretizationDomainX", self, dae.unit(),
                                 "discretization domain in x direction")
        self.Dmny = dae.daeDomain("discretizationDomainY", self, dae.unit(),
                                  "discretization domain in y direction")
        
        self.Dmnx_u = dae.daeDomain("discretizationDomainX_u", self, dae.unit(),
                                 "discretization domain in x direction")
        self.Dmny_u = dae.daeDomain("discretizationDomainY_u", self, dae.unit(),
                                    "discretization domain in y direction")

        # Variables
        self.c = dae.daeVariable(
            "c", mole_frac_t, self,
            "Concentration in x direction of active particle", [self.Dmn])

        Nx = self.get_trode_param("N")
        self.cy = {}
        for k in range(Nx):
            self.cy[k] = dae.daeVariable("cy{k}".format(k=k),
                                         mole_frac_t, self,
                                         "Conc in ver direction of element in row {k}".format(k=k),
                                         [self.Dmny])
        # # check unit of measures
        if self.get_trode_param("mechanics"):
            self.uy = {}
            for k in range(Nx-2):
                self.uy[k] = dae.daeVariable("uy{k}".format(k=k), mole_frac_t,
                                            self,
                                            "Displacement in y direction of element in row {k}".format(k=k),
                                            [self.Dmny_u])
            self.ux = {}
            for k in range(Nx-2):
                self.ux[k] = dae.daeVariable("ux{k}".format(k=k), mole_frac_t,
                                            self,
                                            "Displacement in x direction of element in row {k}".format(k=k),
                                            [self.Dmny_u])

        self.cbar = dae.daeVariable(
            "cbar", mole_frac_t, self,
            "Average concentration in active particle")

        self.dcbardt = dae.daeVariable("dcbardt", dae.no_t, self, "Rate of particle filling")
        self.Rxn = dae.daeVariable("Rxn", dae.no_t, self, "Rate of reaction", [self.Dmn])
        self.q_rxn_bar = dae.daeVariable(
            "q_rxn_bar", dae.no_t, self, "Rate of heat generation in particle")
        # Get reaction rate function
        rxnType = config[trode, "rxnType"]
        self.calc_rxn_rate = utils.import_function(config[trode, "rxnType_filename"],
                                                   rxnType,
                                                   f"mpet.electrode.reactions.{rxnType}")

        # Ports
        self.portInLyte = ports.portFromElyte(
            "portInLyte", dae.eInletPort, self, "Inlet port from electrolyte")
        self.portInBulk = ports.portFromBulk(
            "portInBulk", dae.eInletPort, self,
            "Inlet port from e- conducting phase")
        self.phi_lyte = self.portInLyte.phi_lyte
        self.T_lyte = self.portInLyte.T_lyte
        self.c_lyte = self.portInLyte.c_lyte
        self.phi_m = self.portInBulk.phi_m

    def get_trode_param(self, item):
        """
        Shorthand to retrieve electrode-specific value
        """
        value = self.config[self.trode, item]
        # check if it is a particle-specific parameter
        if item in self.config.params_per_particle:
            value = value[self.ind]
        return value

    def DeclareEquations(self):
        dae.daeModel.DeclareEquations(self)
        Nx = self.get_trode_param("N")
        Ny = self.get_trode_param("N_ver")

        # Prepare noise
        self.noise = None
        if self.get_trode_param("noise"):
            numnoise = self.get_trode_param("numnoise")
            noise_prefac = self.get_trode_param("noise_prefac")
            tvec = np.linspace(0., 1.05*self.config["tend"], numnoise)
            noise_data = noise_prefac*np.random.randn(numnoise, Ny)
            self.noise = sintrp.interp1d(tvec, noise_data, axis=0,
                                         bounds_error=False, fill_value=0.)

        mu_O, act_lyte = calc_mu_O(self.c_lyte(), self.phi_lyte(), self.phi_m(), self.T_lyte(),
                                   self.config["elyteModelType"])

        for k in range(Nx):
            eq = self.CreateEquation("avgscy_isc{k}".format(k=k))
            eq.Residual = self.c(k)
            for j in range(Ny):
                eq.Residual -= self.cy[k](j)/Ny

        eq = self.CreateEquation("cbar")
        eq.Residual = self.cbar()
        for k in range(Nx):
            eq.Residual -= self.c(k)/Nx

        # Define average rate of filling of particle
        eq = self.CreateEquation("dcbardt")
        eq.Residual = self.dcbardt()
        for k in range(Nx):
            for h in range(Ny):
                eq.Residual -= (self.cy[k].dt(h)/Ny)/Nx
            # eq.Residual -= self.c.dt(k)/Nx

        c_mat = np.empty((Nx, Ny), dtype=object)
        for k in range(Nx):
            c_mat[k,:] = [self.cy[k](j) for j in range(Ny)]

        if self.get_trode_param("mechanics"):
            u_y_mat = np.empty((Nx-2, Ny-1), dtype=object)
            for k in range(Nx-2):
                u_y_mat[k,:] = [self.uy[k](j) for j in range(Ny-1)]

            u_x_mat = np.empty((Nx-2, Ny-1), dtype=object)
            for k in range(Nx-2):
                u_x_mat[k,:] = [self.ux[k](j) for j in range(Ny-1)]

        # eta, c_surf = self.sld_dynamics_2D1var(c_mat, mu_O, act_lyte, self.noise)
        if self.get_trode_param("mechanics"):
            eta, c_surf = self.sld_dynamics_2Dmechanical(c_mat, u_x_mat, u_y_mat, mu_O, act_lyte, self.noise)
        else:
            eta, c_surf = self.sld_dynamics_2D1var(c_mat, mu_O, act_lyte, self.noise)

        eq = self.CreateEquation("q_rxn_bar")
        if self.config["entropy_heat_gen"]:
            eq.Residual = self.q_rxn_bar() - self.dcbardt() * \
                (eta - self.T_lyte()*(np.log(c_surf[int(Nx/2)]/(1
                 - c_surf[int(Nx/2)]))-1/self.c_lyte()))
        else:
            eq.Residual = self.q_rxn_bar() - self.dcbardt() * eta[int(Nx/2)]

        for eq in self.Equations:
            eq.CheckUnitsConsistency = False

    def sld_dynamics_2D1var(self, c_mat, muO, act_lyte, noise):
        Ny = np.size(c_mat, 1)
        Nx = np.size(c_mat, 0)
        Dfunc_name = self.get_trode_param("Dfunc")
        Dfunc = utils.import_function(self.get_trode_param("Dfunc_filename"),
                                      Dfunc_name,
                                      f"mpet.electrode.diffusion.{Dfunc_name}")
        dr, edges = geo.get_dr_edges(self.get_trode_param('shape'), Ny)
        area_vec = 1.
        Mmaty = get_Mmat(self.get_trode_param('shape'), Ny)
        # (c, cbar, T, config, trode, ind)
        muR_mat, actR_mat = calc_muR(c_mat, self.cbar(), self.T_lyte(),
                                     self.config, self.trode, self.ind)

        if self.get_trode_param("surface_diffusion"):
            surf_diff_vec = calc_surf_diff(c_mat[:,-1], muR_mat[:,-1],
                                           self.get_trode_param("D_surf"),
                                           self.get_trode_param("E_D_surf"),
                                           self.T_lyte())

        eta = calc_eta(muR_mat[:,-1], muO)
        for k in range(Nx):
            c_vec = c_mat[k,:]
            muR_vec = muR_mat[k,:]
            actR_vec = actR_mat[k,:]
            # muR_vec, actR_vec = calc_muR(c_vec, self.cbar(),
            #                              self.config, self.trode, self.ind)
            c_surf = c_vec[-1]
            # muR_surf = muR_vec[-1]
            actR_surf = actR_vec[-1]
            # eta = calc_eta(muR_surf, muO)

            eta_eff = eta[k] + self.Rxn(k)*self.get_trode_param("Rfilm")

            # flux from top and bottom, 0.5 is for compensate the normalization in 'delta_L'
            Rxn = self.calc_rxn_rate(
                eta_eff, c_surf, self.c_lyte(), self.get_trode_param("k0"),
                self.get_trode_param("E_A"), self.T_lyte(), actR_surf, act_lyte,
                self.get_trode_param("lambda"), self.get_trode_param("alpha"))

            eq = self.CreateEquation("Rxn_{k}".format(k=k))
            eq.Residual = self.Rxn(k) - Rxn

            if self.get_trode_param("surface_diffusion"):
                Flux_bc = -self.Rxn(k)*self.get_trode_param("delta_L") - surf_diff_vec[k]
            else:
                Flux_bc = -self.Rxn(k)*self.get_trode_param("delta_L")

            Flux_vec = calc_flux_CHR_2D(c_vec, muR_vec, self.get_trode_param("D"), Dfunc,
                                     self.get_trode_param("E_D"), Flux_bc, dr,
                                     self.T_lyte(), noise)
            if self.get_trode_param("shape") == "plate":
                area_vec = np.ones(np.shape(edges))
            elif self.get_trode_param("shape") == "cylinder":
                area_vec = 2*np.pi*edges  # per unit height

            RHS_vec = -np.diff(Flux_vec * area_vec)
            dcdt_vec_y = np.empty(Ny, dtype=object)
            dcdt_vec_y[0:Ny] = [self.cy[k].dt(j) for j in range(Ny)]
            LHS_vec_y = MX(Mmaty, dcdt_vec_y)
            for j in range(Ny):
                eq = self.CreateEquation("dcydt_{k}_{j}".format(k=k, j=j))
                eq.Residual = LHS_vec_y[j] - RHS_vec[j]

        return eta, c_mat[:,-1]

    def sld_dynamics_2Dmechanical(self, c_mat, u_x_mat, u_y_mat, muO, act_lyte, noise):
        Ny = np.size(c_mat, 1)
        Nx = np.size(c_mat, 0)
        T = self.config["T"]
        Dfunc_name = self.get_trode_param("Dfunc")
        Dfunc = utils.import_function(self.get_trode_param("Dfunc_filename"),
                                      Dfunc_name,
                                      f"mpet.electrode.diffusion.{Dfunc_name}")
        dr, edges = geo.get_dr_edges(self.get_trode_param('shape'), Ny)
        # C3 shape has constant area along the depth
        area_vec = 1.
        Mmaty = get_Mmat(self.get_trode_param('shape'), Ny)
        # print(c_mat)
        muR_mat, actR_mat = calc_muR(c_mat, self.cbar(), self.T_lyte(),
                                     self.config, self.trode, self.ind)
        muR_el, div_stress_mat, str_mat = calc_muR_el(c_mat, u_x_mat, u_y_mat,
                             self.config, self.trode, self.ind)
        muR_mat -= muR_el
        actR_mat = np.exp(muR_mat)

        for i in range(Nx-2):
            for j in range(Ny-1):
                eq1 = self.CreateEquation("divsigma1_{i}_{j}_equal0".format(i=i, j=j))
                eq1.Residual = div_stress_mat[i,j,0]
                eq2 = self.CreateEquation("divsigma2_{i}_{j}_equal0".format(i=i, j=j))
                eq2.Residual = div_stress_mat[i,j,1]

        eta = calc_eta(muR_mat[:,-1], muO)
        if self.get_trode_param("surface_diffusion"):
            surf_diff_vec = calc_surf_diff(c_mat[:,-1], muR_mat[:,-1],
                                           self.get_trode_param("D_surf"),
                                           self.get_trode_param("E_D_surf"),
                                           self.T_lyte())
        str_mat_tmp = np.zeros((Nx, Ny, 6), dtype=object)
        str_mat_tmp[1:-1,1:,:] = str_mat[:,:,:]
        str_mat_tmp[0,1:,:] = str_mat[0,:,:]
        str_mat_tmp[-1,1:,:] = str_mat[-1,:,:]
        str_mat_tmp[:,0,:] = str_mat_tmp[:,1,:]
        for k in range(Nx):
            c_vec = c_mat[k,:]
            str_vec = str_mat_tmp[k,:,:]
            muR_vec = muR_mat[k,:]
            actR_vec = actR_mat[k,:]
            # muR_vec, actR_vec = calc_muR(c_vec, self.cbar(),
            #                              self.config, self.trode, self.ind)
            c_surf = c_vec[-1]
            # muR_surf = muR_vec[-1]
            actR_surf = actR_vec[-1]
            # eta = calc_eta(muR_surf, muO)

            eta_eff = eta[k] + self.Rxn(k)*self.get_trode_param("Rfilm")

            # flux from top and bottom, 0.5 is for compensate the normalization in 'delta_L'
            Rxn = self.calc_rxn_rate(
                eta_eff, c_surf, self.c_lyte(), self.get_trode_param("k0"),
                self.get_trode_param("E_A"), self.T_lyte(), actR_surf, act_lyte,
                self.get_trode_param("lambda"), self.get_trode_param("alpha"))

            eq = self.CreateEquation("Rxn_{k}".format(k=k))
            eq.Residual = self.Rxn(k) - Rxn

            if self.get_trode_param("surface_diffusion"):
                Flux_bc = -self.Rxn(k)*self.get_trode_param("delta_L") - surf_diff_vec[k]
            else:
                Flux_bc = -self.Rxn(k)*self.get_trode_param("delta_L")

            Flux_vec = calc_flux_CHR_2D(c_vec, str_vec, muR_vec, self.get_trode_param("D"), Dfunc,
                                     self.get_trode_param("E_D"), Flux_bc, dr,
                                     self.T_lyte(), noise)
            if self.get_trode_param("shape") == "plate":
                area_vec = np.ones(np.shape(edges))
            elif self.get_trode_param("shape") == "cylinder":
                print('only plate, sorry :)')

            RHS_vec = -np.diff(Flux_vec * area_vec)
            dcdt_vec_y = np.empty(Ny, dtype=object)
            dcdt_vec_y[0:Ny] = [self.cy[k].dt(j) for j in range(Ny)]
            LHS_vec_y = MX(Mmaty, dcdt_vec_y)
            for j in range(Ny):
                eq = self.CreateEquation("dcydt_{k}_{j}".format(k=k, j=j))
                eq.Residual = LHS_vec_y[j] - RHS_vec[j]

        return eta, c_mat[:,-1]


class Mod2var(dae.daeModel):
    def __init__(self, config, trode, vInd, pInd,
                 Name, Parent=None, Description=""):
        super().__init__(Name, Parent, Description)

        self.config = config
        self.trode = trode
        self.ind = (vInd, pInd)

        # Domain
        self.Dmn = dae.daeDomain("discretizationDomain", self, dae.unit(),
                                 "discretization domain")

        # Variables
        self.c1 = dae.daeVariable(
            "c1", mole_frac_t, self,
            "Concentration in 'layer' 1 of active particle", [self.Dmn])
        self.c2 = dae.daeVariable(
            "c2", mole_frac_t, self,
            "Concentration in 'layer' 2 of active particle", [self.Dmn])
        self.cbar = dae.daeVariable(
            "cbar", mole_frac_t, self,
            "Average concentration in active particle")
        self.c1bar = dae.daeVariable(
            "c1bar", mole_frac_t, self,
            "Average concentration in 'layer' 1 of active particle")
        self.c2bar = dae.daeVariable(
            "c2bar", mole_frac_t, self,
            "Average concentration in 'layer' 2 of active particle")
        self.dcbardt = dae.daeVariable("dcbardt", dae.no_t, self, "Rate of particle filling")
        self.dcbar1dt = dae.daeVariable("dcbar1dt", dae.no_t, self, "Rate of particle 1 filling")
        self.dcbar2dt = dae.daeVariable("dcbar2dt", dae.no_t, self, "Rate of particle 2 filling")
        self.q_rxn_bar = dae.daeVariable(
            "q_rxn_bar", dae.no_t, self, "Rate of heat generation in particle")
        if self.get_trode_param("type") not in ["ACR2"]:
            self.Rxn1 = dae.daeVariable("Rxn1", dae.no_t, self, "Rate of reaction 1")
            self.Rxn2 = dae.daeVariable("Rxn2", dae.no_t, self, "Rate of reaction 2")
        else:
            self.Rxn1 = dae.daeVariable("Rxn1", dae.no_t, self, "Rate of reaction 1", [self.Dmn])
            self.Rxn2 = dae.daeVariable("Rxn2", dae.no_t, self, "Rate of reaction 2", [self.Dmn])

        # Get reaction rate function
        rxnType = config[trode, "rxnType"]
        self.calc_rxn_rate = utils.import_function(config[trode, "rxnType_filename"],
                                                   rxnType,
                                                   f"mpet.electrode.reactions.{rxnType}")

        # Ports
        self.portInLyte = ports.portFromElyte(
            "portInLyte", dae.eInletPort, self, "Inlet port from electrolyte")
        self.portInBulk = ports.portFromBulk(
            "portInBulk", dae.eInletPort, self,
            "Inlet port from e- conducting phase")
        self.phi_lyte = self.portInLyte.phi_lyte
        self.T_lyte = self.portInLyte.T_lyte
        self.c_lyte = self.portInLyte.c_lyte
        self.phi_m = self.portInBulk.phi_m

    def get_trode_param(self, item):
        """
        Shorthand to retrieve electrode-specific value
        """
        value = self.config[self.trode, item]
        # check if it is a particle-specific parameter
        if item in self.config.params_per_particle:
            value = value[self.ind]
        return value

    def DeclareEquations(self):
        dae.daeModel.DeclareEquations(self)
        N = self.get_trode_param("N")  # number of grid points in particle
        r_vec, volfrac_vec = geo.get_unit_solid_discr(self.get_trode_param('shape'), N)

        # Prepare noise
        self.noise1 = self.noise2 = None
        if self.get_trode_param("noise"):
            numnoise = self.get_trode_param("numnoise")
            noise_prefac = self.get_trode_param("noise_prefac")
            tvec = np.linspace(0., 1.05*self.config["tend"], numnoise)
            noise_data1 = noise_prefac*np.random.randn(numnoise, N)
            noise_data2 = noise_prefac*np.random.randn(numnoise, N)
            self.noise1 = sintrp.interp1d(tvec, noise_data1, axis=0,
                                          bounds_error=False, fill_value=0.)
            self.noise2 = sintrp.interp1d(tvec, noise_data2, axis=0,
                                          bounds_error=False, fill_value=0.)
        noises = (self.noise1, self.noise2)

        # Figure out mu_O, mu of the oxidized state
        mu_O, act_lyte = calc_mu_O(
            self.c_lyte(), self.phi_lyte(), self.phi_m(), self.T_lyte(),
            self.config["elyteModelType"])

        # Define average filling fractions in particle
        eq1 = self.CreateEquation("c1bar")
        eq2 = self.CreateEquation("c2bar")
        eq1.Residual = self.c1bar()
        eq2.Residual = self.c2bar()
        for k in range(N):
            eq1.Residual -= self.c1(k) * volfrac_vec[k]
            eq2.Residual -= self.c2(k) * volfrac_vec[k]
        eq = self.CreateEquation("cbar")
        eq.Residual = self.cbar() - .5*(self.c1bar() + self.c2bar())

        # Define average rate of filling of particle
        eq = self.CreateEquation("dcbardt")
        eq.Residual = self.dcbardt()
        for k in range(N):
            eq.Residual -= .5*(self.c1.dt(k) + self.c2.dt(k)) * volfrac_vec[k]

        # Define average rate of filling of particle for cbar1
        eq = self.CreateEquation("dcbar1dt")
        eq.Residual = self.dcbar1dt()
        for k in range(N):
            eq.Residual -= self.c1.dt(k) * volfrac_vec[k]

        # Define average rate of filling of particle for cbar1
        eq = self.CreateEquation("dcbar2dt")
        eq.Residual = self.dcbar2dt()
        for k in range(N):
            eq.Residual -= self.c2.dt(k) * volfrac_vec[k]

        c1 = np.empty(N, dtype=object)
        c2 = np.empty(N, dtype=object)
        c1[:] = [self.c1(k) for k in range(N)]
        c2[:] = [self.c2(k) for k in range(N)]
        if self.get_trode_param("type") in ["diffn2", "CHR2"]:
            # Equations for 1D particles of 1 field varible
            eta1, eta2, c_surf1, c_surf2 = self.sld_dynamics_1D2var(c1, c2, mu_O, act_lyte,
                                                                    noises)
        elif self.get_trode_param("type") in ["homog2", "homog2_sdn"]:
            # Equations for 0D particles of 1 field variables
            eta1, eta2, c_surf1, c_surf2 = self.sld_dynamics_0D2var(c1, c2, mu_O, act_lyte,
                                                                    noises)

        # Define average rate of heat generation
        eq = self.CreateEquation("q_rxn_bar")
        if self.config["entropy_heat_gen"]:
            eq.Residual = self.q_rxn_bar() - 0.5 * self.dcbar1dt() * \
                (eta1 - self.T_lyte()*(np.log(c_surf1/(1-c_surf1))-1/self.c_lyte())) \
                - 0.5 * self.dcbar2dt() * (eta2 - self.T_lyte()
                                           * (np.log(c_surf2/(1-c_surf2))-1/self.c_lyte()))
        else:
            eq.Residual = self.q_rxn_bar() - 0.5 * self.dcbar1dt() * eta1 \
                - 0.5 * self.dcbar2dt() * eta2

        for eq in self.Equations:
            eq.CheckUnitsConsistency = False

    def sld_dynamics_0D2var(self, c1, c2, muO, act_lyte, noises):
        c1_surf = c1
        c2_surf = c2
        (mu1R_surf, mu2R_surf), (act1R_surf, act2R_surf) = calc_muR(
            (c1_surf, c2_surf), (self.c1bar(), self.c2bar()), self.T_lyte(), self.config,
            self.trode, self.ind)
        eta1 = calc_eta(mu1R_surf, muO)
        eta2 = calc_eta(mu2R_surf, muO)
        eta1_eff = eta1 + self.Rxn1()*self.get_trode_param("Rfilm")
        eta2_eff = eta2 + self.Rxn2()*self.get_trode_param("Rfilm")
        noise1, noise2 = noises
        if self.get_trode_param("noise"):
            eta1_eff += noise1(dae.Time().Value)
            eta2_eff += noise2(dae.Time().Value)
        Rxn1 = self.calc_rxn_rate(
            eta1_eff, c1_surf, self.c_lyte(), self.get_trode_param("k0"),
            self.get_trode_param("E_A"), self.T_lyte(), act1R_surf, act_lyte,
            self.get_trode_param("lambda"), self.get_trode_param("alpha"))
        Rxn2 = self.calc_rxn_rate(
            eta2_eff, c2_surf, self.c_lyte(), self.get_trode_param("k0"),
            self.get_trode_param("E_A"), self.T_lyte(), act2R_surf, act_lyte,
            self.get_trode_param("lambda"), self.get_trode_param("alpha"))
        eq1 = self.CreateEquation("Rxn1")
        eq2 = self.CreateEquation("Rxn2")
        eq1.Residual = self.Rxn1() - Rxn1[0]
        eq2.Residual = self.Rxn2() - Rxn2[0]

        eq1 = self.CreateEquation("dc1sdt")
        eq2 = self.CreateEquation("dc2sdt")
        eq1.Residual = self.c1.dt(0) - self.get_trode_param("delta_L")*Rxn1[0]
        eq2.Residual = self.c2.dt(0) - self.get_trode_param("delta_L")*Rxn2[0]
        return eta1[-1], eta2[-1], c1_surf[-1], c2_surf[-1]

    def sld_dynamics_1D2var(self, c1, c2, muO, act_lyte, noises):
        N = self.get_trode_param("N")
        # Equations for concentration evolution
        # Mass matrix, M, where M*dcdt = RHS, where c and RHS are vectors
        Mmat = get_Mmat(self.get_trode_param('shape'), N)
        dr, edges = geo.get_dr_edges(self.get_trode_param('shape'), N)

        # Get solid particle chemical potential, overpotential, reaction rate
        if self.get_trode_param("type") in ["diffn2", "CHR2"]:
            (mu1R, mu2R), (act1R, act2R) = calc_muR((c1, c2), (self.c1bar(), self.c2bar()),
                                                    self.T_lyte(), self.config, self.trode,
                                                    self.ind)
            c1_surf = c1[-1]
            c2_surf = c2[-1]
            mu1R_surf, act1R_surf = mu1R[-1], act1R[-1]
            mu2R_surf, act2R_surf = mu2R[-1], act2R[-1]
        eta1 = calc_eta(mu1R_surf, muO)
        eta2 = calc_eta(mu2R_surf, muO)
        if self.get_trode_param("type") in ["ACR2"]:
            eta1_eff = np.array([eta1[i]
                                 + self.Rxn1(i)*self.get_trode_param("Rfilm") for i in range(N)])
            eta2_eff = np.array([eta2[i]
                                 + self.Rxn2(i)*self.get_trode_param("Rfilm") for i in range(N)])
        else:
            eta1_eff = eta1 + self.Rxn1()*self.get_trode_param("Rfilm")
            eta2_eff = eta2 + self.Rxn2()*self.get_trode_param("Rfilm")
        Rxn1 = self.calc_rxn_rate(
            eta1_eff, c1_surf, self.c_lyte(), self.get_trode_param("k0"),
            self.get_trode_param("E_A"), self.T_lyte(), act1R_surf, act_lyte,
            self.get_trode_param("lambda"), self.get_trode_param("alpha"))
        Rxn2 = self.calc_rxn_rate(
            eta2_eff, c2_surf, self.c_lyte(), self.get_trode_param("k0"),
            self.get_trode_param("E_A"), self.T_lyte(), act2R_surf, act_lyte,
            self.get_trode_param("lambda"), self.get_trode_param("alpha"))
        if self.get_trode_param("type") in ["ACR2"]:
            for i in range(N):
                eq1 = self.CreateEquation("Rxn1_{i}".format(i=i))
                eq2 = self.CreateEquation("Rxn2_{i}".format(i=i))
                eq1.Residual = self.Rxn1(i) - Rxn1[i]
                eq2.Residual = self.Rxn2(i) - Rxn2[i]
        else:
            eq1 = self.CreateEquation("Rxn1")
            eq2 = self.CreateEquation("Rxn2")
            eq1.Residual = self.Rxn1() - Rxn1
            eq2.Residual = self.Rxn2() - Rxn2

        # Get solid particle fluxes (if any) and RHS
        if self.get_trode_param("type") in ["diffn2", "CHR2"]:
            # Positive reaction (reduction, intercalation) is negative
            # flux of Li at the surface.
            Flux1_bc = -0.5 * self.Rxn1()
            Flux2_bc = -0.5 * self.Rxn2()
            Dfunc_name = self.get_trode_param("Dfunc")
            Dfunc = utils.import_function(self.get_trode_param("Dfunc_filename"),
                                          Dfunc_name,
                                          f"mpet.electrode.diffusion.{Dfunc_name}")
            if self.get_trode_param("type") == "CHR2":
                noise1, noise2 = noises
                Flux1_vec, Flux2_vec = calc_flux_CHR2(
                    c1, c2, mu1R, mu2R, self.get_trode_param("D"), Dfunc,
                    self.get_trode_param("E_D"), Flux1_bc, Flux2_bc, dr, self.T_lyte(),
                    noise1, noise2)
            if self.get_trode_param("shape") == "sphere":
                area_vec = 4*np.pi*edges**2
            elif self.get_trode_param("shape") == "cylinder":
                area_vec = 2*np.pi*edges  # per unit height
            RHS1 = -np.diff(Flux1_vec * area_vec)
            RHS2 = -np.diff(Flux2_vec * area_vec)
#            kinterlayer = 1e-3
#            interLayerRxn = (kinterlayer * (1 - c1) * (1 - c2) * (act1R - act2R))
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

        if self.get_trode_param("type") in ["ACR"]:
            return eta1[-1], eta2[-1], c1_surf[-1], c2_surf[-1]
        else:
            return eta1, eta2, c1_surf, c2_surf


class Mod1var(dae.daeModel):
    def __init__(self, config, trode, vInd, pInd,
                 Name, Parent=None, Description=""):
        super().__init__(Name, Parent, Description)

        self.config = config
        self.trode = trode
        self.ind = (vInd, pInd)

        # Domain
        self.Dmn = dae.daeDomain("discretizationDomain", self, dae.unit(),
                                 "discretization domain")

        # Variables
        self.c = dae.daeVariable("c", mole_frac_t, self,
                                 "Concentration in active particle",
                                 [self.Dmn])
        self.cbar = dae.daeVariable(
            "cbar", mole_frac_t, self,
            "Average concentration in active particle")
        self.dcbardt = dae.daeVariable("dcbardt", dae.no_t, self, "Rate of particle filling")
        self.q_rxn_bar = dae.daeVariable(
            "q_rxn_bar", dae.no_t, self, "Rate of heat generation in particle")
        if config[trode, "type"] not in ["ACR"]:
            self.Rxn = dae.daeVariable("Rxn", dae.no_t, self, "Rate of reaction")
        else:
            self.Rxn = dae.daeVariable("Rxn", dae.no_t, self, "Rate of reaction", [self.Dmn])

        # Get reaction rate function
        rxnType = config[trode, "rxnType"]
        self.calc_rxn_rate = utils.import_function(config[trode, "rxnType_filename"],
                                                   rxnType,
                                                   f"mpet.electrode.reactions.{rxnType}")

        # Ports
        self.portInLyte = ports.portFromElyte(
            "portInLyte", dae.eInletPort, self,
            "Inlet port from electrolyte")
        self.portInBulk = ports.portFromBulk(
            "portInBulk", dae.eInletPort, self,
            "Inlet port from e- conducting phase")
        self.phi_lyte = self.portInLyte.phi_lyte
        self.T_lyte = self.portInLyte.T_lyte
        self.c_lyte = self.portInLyte.c_lyte
        self.phi_m = self.portInBulk.phi_m

    def get_trode_param(self, item):
        """
        Shorthand to retrieve electrode-specific value
        """
        value = self.config[self.trode, item]
        # check if it is a particle-specific parameter
        if item in self.config.params_per_particle:
            value = value[self.ind]
        return value

    def DeclareEquations(self):
        dae.daeModel.DeclareEquations(self)
        N = self.get_trode_param("N")  # number of grid points in particle
        r_vec, volfrac_vec = geo.get_unit_solid_discr(self.get_trode_param('shape'), N)

        # Prepare noise
        self.noise = None
        if self.get_trode_param("noise"):
            numnoise = self.get_trode_param("numnoise")
            noise_prefac = self.get_trode_param("noise_prefac")
            tvec = np.linspace(0., 1.05*self.config["tend"], numnoise)
            noise_data = noise_prefac*np.random.randn(numnoise, N)
            self.noise = sintrp.interp1d(tvec, noise_data, axis=0,
                                         bounds_error=False, fill_value=0.)

        # Figure out mu_O, mu of the oxidized state
        mu_O, act_lyte = calc_mu_O(self.c_lyte(), self.phi_lyte(), self.phi_m(), self.T_lyte(),
                                   self.config["elyteModelType"])

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
        c_surf = np.empty(N, dtype=object)
        c[:] = [self.c(k) for k in range(N)]
        if self.get_trode_param("type") in ["ACR", "diffn", "CHR"]:
            # Equations for 1D particles of 1 field varible
            eta, c_surf = self.sld_dynamics_1D1var(c, mu_O, act_lyte, self.noise)
        elif self.get_trode_param("type") in ["homog", "homog_sdn"]:
            # Equations for 0D particles of 1 field variables
            eta, c_surf = self.sld_dynamics_0D1var(c, mu_O, act_lyte, self.noise)

        # Define average rate of heat generation
        eq = self.CreateEquation("q_rxn_bar")
        if self.config["entropy_heat_gen"]:
            eq.Residual = self.q_rxn_bar() - self.dcbardt() * \
                (eta - self.T_lyte()*(np.log(c_surf/(1-c_surf))-1/self.c_lyte()))
        else:
            eq.Residual = self.q_rxn_bar() - self.dcbardt() * eta

        for eq in self.Equations:
            eq.CheckUnitsConsistency = False

    def sld_dynamics_0D1var(self, c, muO, act_lyte, noise):
        c_surf = c
        muR_surf, actR_surf = calc_muR(c_surf, self.cbar(), self.T_lyte(),self.config,
                                       self.trode, self.ind)
        eta = calc_eta(muR_surf, muO)
        eta_eff = eta + self.Rxn()*self.get_trode_param("Rfilm")
        if self.get_trode_param("noise"):
            eta_eff += noise[0]()
        Rxn = self.calc_rxn_rate(
            eta_eff, c_surf, self.c_lyte(), self.get_trode_param("k0"),
            self.get_trode_param("E_A"), self.T_lyte(), actR_surf, act_lyte,
            self.get_trode_param("lambda"), self.get_trode_param("alpha"))
        eq = self.CreateEquation("Rxn")
        eq.Residual = self.Rxn() - Rxn[0]

        eq = self.CreateEquation("dcsdt")
        eq.Residual = self.c.dt(0) - self.get_trode_param("delta_L")*self.Rxn()
        return eta[-1], c_surf[-1]

    def sld_dynamics_1D1var(self, c, muO, act_lyte, noise):
        N = self.get_trode_param("N")
        # Equations for concentration evolution
        # Mass matrix, M, where M*dcdt = RHS, where c and RHS are vectors
        Mmat = get_Mmat(self.get_trode_param('shape'), N)
        dr, edges = geo.get_dr_edges(self.get_trode_param('shape'), N)
        # Get solid particle chemical potential, overpotential, reaction rate
        if self.get_trode_param("type") in ["ACR"]:
            # c_surf = c
            if noise is None:
                c_surf = c
            else:
                c_surf = c + noise(dae.Time().Value)
            muR_surf, actR_surf = calc_muR(
                c_surf, self.cbar(), self.T_lyte(), self.config, self.trode, self.ind)

        elif self.get_trode_param("type") in ["diffn", "CHR"]:
            muR, actR = calc_muR(c, self.cbar(), self.T_lyte(),
                                 self.config, self.trode, self.ind)
            c_surf = c[-1]
            muR_surf = muR[-1]
            if actR is None:
                actR_surf = None
            else:
                actR_surf = actR[-1]
        eta = calc_eta(muR_surf, muO)
        if self.get_trode_param("type") in ["ACR"]:
            eta_eff = np.array([eta[i] + self.Rxn(i)*self.get_trode_param("Rfilm")
                                for i in range(N)])
        else:
            eta_eff = eta + self.Rxn()*self.get_trode_param("Rfilm")
        Rxn = self.calc_rxn_rate(
            eta_eff, c_surf, self.c_lyte(), self.get_trode_param("k0"),
            self.get_trode_param("E_A"), self.T_lyte(), actR_surf, act_lyte,
            self.get_trode_param("lambda"), self.get_trode_param("alpha"))
        if self.get_trode_param("type") in ["ACR"]:
            for i in range(N):
                eq = self.CreateEquation("Rxn_{i}".format(i=i))
                eq.Residual = self.Rxn(i) - Rxn[i]
        else:
            eq = self.CreateEquation("Rxn")
            eq.Residual = self.Rxn() - Rxn

        # Get solid particle fluxes (if any) and RHS
        if self.get_trode_param("type") in ["ACR"]:
            RHS = np.array([self.get_trode_param("delta_L")*self.Rxn(i) for i in range(N)])
        elif self.get_trode_param("type") in ["diffn", "CHR"]:
            # Positive reaction (reduction, intercalation) is negative
            # flux of Li at the surface.
            Flux_bc = -self.Rxn()
            Dfunc_name = self.get_trode_param("Dfunc")
            Dfunc = utils.import_function(self.get_trode_param("Dfunc_filename"),
                                          Dfunc_name,
                                          f"mpet.electrode.diffusion.{Dfunc_name}")
            if self.get_trode_param("type") == "diffn":
                Flux_vec = calc_flux_diffn(c, self.get_trode_param("D"), Dfunc,
                                           self.get_trode_param("E_D"), Flux_bc, dr,
                                           self.T_lyte(), noise)
            elif self.get_trode_param("type") == "CHR":
                Flux_vec = calc_flux_CHR(c, muR, self.get_trode_param("D"), Dfunc,
                                         self.get_trode_param("E_D"), Flux_bc, dr,
                                         self.T_lyte(), noise)
            if self.get_trode_param("shape") == "sphere":
                area_vec = 4*np.pi*edges**2
            elif self.get_trode_param("shape") == "cylinder":
                area_vec = 2*np.pi*edges  # per unit height
            elif self.get_trode_param("shape") == "plate":
                area_vec = np.ones(np.shape(edges))
            RHS = -np.diff(Flux_vec * area_vec)

        dcdt_vec = np.empty(N, dtype=object)
        dcdt_vec[0:N] = [self.c.dt(k) for k in range(N)]
        LHS_vec = MX(Mmat, dcdt_vec)
        if self.get_trode_param("surface_diffusion"):
            surf_diff_vec = calc_surf_diff(c_surf, muR_surf,
                                           self.get_trode_param("D_surf"),
                                           self.get_trode_param("E_D_surf"),
                                           self.T_lyte())
            for k in range(N):
                eq = self.CreateEquation("dcsdt_discr{k}".format(k=k))
                eq.Residual = LHS_vec[k] - RHS[k] - surf_diff_vec[k]
        else:
            for k in range(N):
                eq = self.CreateEquation("dcsdt_discr{k}".format(k=k))
                eq.Residual = LHS_vec[k] - RHS[k]

        if self.get_trode_param("type") in ["ACR"]:
            return eta[-1], c_surf[-1]
        else:
            return eta, c_surf


def calc_surf_diff(c_surf, muR_surf, D_surf, E_D_surf, T):
    # the surface diffusion keeps the volume centered method of the ACR
    N = np.size(c_surf)
    dxs = 1./N
    D_eff = (D_surf/(T) * np.exp(-E_D_surf/(T)
             + E_D_surf/1))
    c_edges = utils.mean_linear(c_surf)
    surf_flux = np.empty(N+1, dtype=object)
    surf_flux[1:-1] = -D_eff*c_edges*(1-c_edges)*np.diff(muR_surf)/(dxs)
    surf_flux[0] = 0.
    surf_flux[-1] = 0.
    surf_diff = -np.diff(surf_flux)/dxs
    return surf_diff


def calc_eta(muR, muO):
    return muR - muO


def get_Mmat(shape, N):
    r_vec, volfrac_vec = geo.get_unit_solid_discr(shape, N)
    if shape == "C3":
        Mmat = sprs.eye(N, N, format="csr")
    elif shape in ["sphere", "cylinder", 'plate']:
        Rs = 1.
        # For discretization background, see Zeng & Bazant 2013
        # Mass matrix is common for each shape, diffn or CHR
        if shape == "sphere":
            Vp = 4./3. * np.pi * Rs**3
        elif shape == "cylinder":
            Vp = np.pi * Rs**2  # per unit height
        elif shape == "plate":
            Vp = 1.
        vol_vec = Vp * volfrac_vec
        M1 = sprs.diags([1./8, 3./4, 1./8], [-1, 0, 1],
                        shape=(N, N), format="csr")
        M1[1,0] = M1[-2,-1] = 1./4
        M2 = sprs.diags(vol_vec, 0, format="csr")
        Mmat = M1*M2
    return Mmat


def calc_flux_diffn(c, D, Dfunc, E_D, Flux_bc, dr, T, noise):
    N = len(c)
    Flux_vec = np.empty(N+1, dtype=object)
    Flux_vec[0] = 0  # Symmetry at r=0
    Flux_vec[-1] = Flux_bc
    c_edges = utils.mean_linear(c)
    if noise is None:
        Flux_vec[1:N] = -D/T * Dfunc(c_edges) * np.exp(-E_D/T + E_D/1) * np.diff(c)/dr
    else:
        Flux_vec[1:N] = -D/T * Dfunc(c_edges) * np.exp(-E_D/T + E_D/1) * \
            np.diff(c + noise(dae.Time().Value))/dr
    return Flux_vec


def calc_flux_CHR(c, mu, D, Dfunc, E_D, Flux_bc, dr, T, noise):
    N = len(c)
    Flux_vec = np.empty(N+1, dtype=object)
    Flux_vec[0] = 0  # Symmetry at r=0
    Flux_vec[-1] = Flux_bc
    c_edges = utils.mean_linear(c)
    if noise is None:
        Flux_vec[1:N] = -D/T * Dfunc(c_edges) * np.exp(-E_D/T + E_D/1) * np.diff(mu)/dr
    else:
        Flux_vec[1:N] = -D/T * Dfunc(c_edges) * np.exp(-E_D/T + E_D/1) * \
            np.diff(mu + noise(dae.Time().Value))/dr
    return Flux_vec

def calc_flux_CHR_2D(c, str, mu, D, Dfunc, E_D, Flux_bc, dr, T, noise):
    N = len(c)
    Flux_vec = np.empty(N+1, dtype=object)
    Flux_vec[0] = 0
    Flux_vec[-1] = Flux_bc
    c_edges = utils.mean_linear(c)
    str_vert_edges = utils.mean_linear(str[:,1])
    str_a = utils.mean_linear(str[:,0])
    str_c = utils.mean_linear(str[:,2])
    # D_of_c_eps = D*(c_edges*(1-c_edges))*np.exp(100*str_vert_edges)
    # D_of_c_eps = D*(c_edges*(1-c_edges))*np.exp(100*0.04*c_edges)
    D_of_c_eps = D*(c_edges*(1-c_edges))
    if noise is None:
        Flux_vec[1:N] = -D/T * D_of_c_eps * np.exp(-E_D/T + E_D/1) * np.diff(mu)/dr
    else:
        Flux_vec[1:N] = -D/T * D_of_c_eps * np.exp(-E_D/T + E_D/1) * \
            np.diff(mu + noise(dae.Time().Value))/dr
    return Flux_vec


def calc_flux_C3ver(c, mu, D, Dfunc, E_D, Flux_bc, dr, T, noise):
    N = len(c)
    Flux_vec = np.empty(N+1, dtype=object)
    Flux_vec[0] = 0  # Symmetry at r=0
    Flux_vec[-1] = Flux_bc
    c_edges = utils.mean_linear(c)
    if noise is None:
        Flux_vec[1:N] = -D/T * Dfunc(c_edges) * np.exp(-E_D/T + E_D/1) * np.diff(mu)/dr
    else:
        Flux_vec[1:N] = -D/T * Dfunc(c_edges) * np.exp(-E_D/T + E_D/1) * \
            np.diff(mu + noise(dae.Time().Value))/dr
    return Flux_vec


def calc_flux_CHR2(c1, c2, mu1_R, mu2_R, D, Dfunc, E_D, Flux1_bc, Flux2_bc, dr, T, noise1, noise2):
    N = len(c1)
    Flux1_vec = np.empty(N+1, dtype=object)
    Flux2_vec = np.empty(N+1, dtype=object)
    Flux1_vec[0] = 0.  # symmetry at r=0
    Flux2_vec[0] = 0.  # symmetry at r=0
    Flux1_vec[-1] = Flux1_bc
    Flux2_vec[-1] = Flux2_bc
    c1_edges = utils.mean_linear(c1)
    c2_edges = utils.mean_linear(c2)
    if noise1 is None:
        Flux1_vec[1:N] = -D/T * Dfunc(c1_edges) * np.exp(-E_D/T + E_D/1) * np.diff(mu1_R)/dr
        Flux2_vec[1:N] = -D/T * Dfunc(c2_edges) * np.exp(-E_D/T + E_D/1) * np.diff(mu2_R)/dr
    else:
        Flux1_vec[1:N] = -D/T * Dfunc(c1_edges) * np.exp(-E_D/T + E_D/1) * \
            np.diff(mu1_R+noise1(dae.Time().Value))/dr
        Flux2_vec[1:N] = -D/T * Dfunc(c2_edges) * np.exp(-E_D/T + E_D/1) * \
            np.diff(mu2_R+noise2(dae.Time().Value))/dr
    return Flux1_vec, Flux2_vec


def calc_mu_O(c_lyte, phi_lyte, phi_sld, T, elyteModelType):
    if elyteModelType == "SM":
        mu_lyte = phi_lyte
        act_lyte = c_lyte
    elif elyteModelType == "dilute":
        act_lyte = c_lyte
        mu_lyte = T*np.log(act_lyte) + phi_lyte
    mu_O = mu_lyte - phi_sld
    return mu_O, act_lyte


def calc_muR(c, cbar, T, config, trode, ind):
    muRfunc = props_am.muRfuncs(config, trode, ind).muRfunc
    muR_ref = config[trode, "muR_ref"]
    muR, actR = muRfunc(c, cbar, T, muR_ref)
    return muR, actR

def mech_tensors():
    # FePo4 elastic constants (GPa)
    c11 = 157.4
    c22 = 175.8
    c33 = 154
    c44 = 37.8
    c55 = 49.05
    c66 = 51.6
    c13 = 51.2
    c12 = 53.35
    c23 = 32.7

    # c11 = 175.9
    # c22 = 153.6
    # c33 = 135.0
    # c44 = 38.8
    # c55 = 47.5
    # c66 = 55.6
    # c13 = 54.0
    # c12 = 29.6
    # c23 = 19.6

    # rotatated 
    Cij = np.array([
        [152.5, 43, 54.4,   0, 0.85,  0],
        [43, 175.8, 43,     0, 10.32, 0],
        [54.4, 43, 152.5,   0, 0.85,  0],
        [0,     0,   0,     44.7, 0,    6.9],
        [0.85,10.32,0.85,  0,  52.25, 0],
        [0,   0,   0,       6.9,   0,  44.7]
        ])

    # Cij = np.array([
    #     [c11, c12, c13, 0, 0, 0],
    #     [c12, c22, c23, 0, 0, 0],
    #     [c13, c23, c33, 0, 0, 0],
    #     [0,   0,   0, c44, 0, 0],
    #     [0,   0,   0, 0, c55, 0],
    #     [0,   0,   0, 0, 0, c66]
    #     ])
    
    
    # # strain
    # e01 = 0.0517
    # e02 = 0.0359
    # e03 = -0.0186
    e01 = 0.05
    e02 = 0.028
    e03 = -0.025

    # strain_tensor = np.array([
    #     [e01, 0, 0],
    #     [0, e02, 0],
    #     [0, 0, e03]
    # ])

    strain_tensor = np.array([
        [0.0125,    0,   0.0375],
        [0,         0.028,     0],
        [0.0375,   0,    0.0125]
    ])

    e0 = np.array([strain_tensor[0,0], strain_tensor[1,1], strain_tensor[2,2],
                   strain_tensor[1,2], strain_tensor[0,2], strain_tensor[0,1]])

    return Cij, e0

def calc_muR_el(c_mat, u_x, u_y, conf, trode, ind):
    # pier symm
    Ny = np.size(c_mat, 1)
    Nx = np.size(c_mat, 0)
    dys = 1./(Ny-1)
    dxs = 1./Nx

    max_conc = conf[trode, "rho_s"]
    T_ref = 298
    k = 1.381e-23
    N_A = 6.022e23
    kT = k * T_ref
    
    Cij, e0 = mech_tensors()
    Cij = Cij*1e9

    # u enters as Nx  - 2 and Ny - 1

    u_x_tmp = np.zeros((Nx-1,Ny), dtype=object) # Nx, Ny 
    u_x_tmp[:int(Nx/2),1:] = u_x[:int(Nx/2),:]
    u_x_tmp[int(Nx/2)+1:,1:] = u_x[int(Nx/2):,:]
    u_x_tmp[:,0] = u_x_tmp[:,1]

    # u_y_tmp = np.zeros((Nx-1,Ny), dtype=object) # Nx-1, Ny
    # u_y_tmp[:int(Nx/2),1:] = u_y[:int(Nx/2),:]
    # u_y_tmp[int(Nx/2)+1:,1:] = u_y[int(Nx/2):,:]
    # u_y_tmp[int(Nx/2),1:] = 0.5*(u_y[int(Nx/2),:] + u_y[int(Nx/2)-1,:])

    u_y_tmp = np.zeros((Nx,Ny), dtype=object) # Nx-2, Ny
    u_y_tmp[1:-1,1:] = u_y[:,:]
    u_y_tmp[0,1:] = u_y_tmp[1,1:]
    u_y_tmp[-1,1:] = u_y_tmp[-2,1:]


    # e1_tmp = np.zeros((Nx-2,Ny), dtype=object)
    e1_tmp = np.diff(u_x_tmp, axis=0)/dxs # Nx, Ny

    # e1 = np.zeros((Nx-2,Ny-1), dtype=object)
    e1 = e1_tmp[:,1:] # Nx-2, Ny-1
    # e1[:,:] =0.5*(e1_tmp[1:,1:] + e1_tmp[:-1,1:]) # Nx-2, Ny-1

    # e2_tmp = np.zeros((Nx+2,Ny), dtype=object)
    e2_tmp = np.diff(u_y_tmp, axis=1)/dys # Nx-1, Ny-1
    # e2 = np.zeros((Nx+1,Ny), dtype=object)
    # e2 = 0.5*(e2_tmp[1:,:] + e2_tmp[:-1,:])
    e2 = e2_tmp[1:-1,:] # Nx-2, Ny-1

    # duydx = np.zeros((Nx-2,Ny-1), dtype=object)
    duydx_tmp = np.diff(u_y_tmp[:,1:], axis=0)/dxs # Nx-2, Ny -1
    duydx = 0.5*(duydx_tmp[1:,:] + duydx_tmp[:-1,:]) # Nx-2, Ny -1
    # duydx = duydx_tmp

    # duxdy = np.zeros((Nx-2,Ny-1), dtype=object) # Nx-2, Ny -1
    duxdy_tmp = np.diff(u_x_tmp, axis=1)/dys # Nx-2, Ny-1
    duxdy = 0.5*(duxdy_tmp[1:,:] + duxdy_tmp[:-1,:]) # Nx-2, Ny-1
    # duxdy = duxdy_tmp[1:-1,:] # Nx-2, Ny-1


    e12 = 0.5*(duydx + duxdy) # Nx-2 , Ny-1 

    e_mat = np.zeros((Nx-2,Ny-1,6), dtype=object)
    sigma_mat = np.zeros((Nx-2,Ny-1,6), dtype=object)
    str_mat = np.zeros((Nx-2,Ny-1,6), dtype=object)

    for i in range(Nx-2):
        for j in range(Ny-1):
            str_mat[i,j,:] = np.array([e1[i,j],
                                    e2[i,j],
                                    e0[2]*c_mat[i+1,j],
                                    0,
                                    0,
                                    e12[i,j]])
            
            # e_mat[i,j,:] = np.array([e1[i,j]- e0[0]*c_mat[i+1,j],
            #                         e2[i,j]- e0[1]*c_mat[i+1,j],
            #                         0,
            #                         0 - e0[3]*c_mat[i+1,j],
            #                         0 - e0[4]*c_mat[i+1,j],
            #                         e12[i,j] - e0[5]*c_mat[i+1,j]
            #                         ])
            
            e_mat[i,j,:] = np.array([e1[i,j]- e0[0]*(1/(1+np.exp(-10*(c_mat[i+1,j]-0.5)))),
                                    e2[i,j]- e0[1]*(1/(1+np.exp(-10*(c_mat[i+1,j]-0.5)))),
                                    0,
                                    0 - e0[3]*(1/(1+np.exp(-10*(c_mat[i+1,j]-0.5)))),
                                    0 - e0[4]*(1/(1+np.exp(-10*(c_mat[i+1,j]-0.5)))),
                                    e12[i,j]- e0[5]*(1/(1+np.exp(-10*(c_mat[i+1,j]-0.5))))
                                    ])
            
            sigma_mat[i,j,:] = np.dot(Cij,e_mat[i,j,:])


    sigma_mat_temp = np.zeros((Nx,Ny,6), dtype=object)
    sigma_mat_temp[1:-1,:-1,:] = sigma_mat[:,:,:]

    muR_el = np.zeros((Nx,Ny), dtype=object)

    for i in range(Nx):
        for j in range(Ny):
            muR_el[i,j] = np.dot(sigma_mat_temp[i,j,:],e0)/(kT * max_conc)
            
    dsigma1dx_mat_tmp = np.diff(sigma_mat_temp[:,:-1,0], axis=0)/dxs # Nx-1, Ny -1
    dsigma1dx_mat = 0.5*(dsigma1dx_mat_tmp[1:,:] + dsigma1dx_mat_tmp[:-1,:]) # Nx-2, Ny-1

    dsigma2dy_mat_tmp = np.diff(sigma_mat_temp[:,:,1], axis=1)/dys # Nx, Ny-1
    # dsigma2dy_mat = 0.5*(dsigma2dy_mat_tmp[1:,:] + dsigma2dy_mat_tmp[:-1,:]) # Nx-1, Ny-1
    dsigma2dy_mat = dsigma2dy_mat_tmp[1:-1,:] # Nx-2, Ny-1

    dsigma12dx_mat_tmp = np.diff(sigma_mat_temp[:,:-1,3], axis=0)/dxs # Nx, Ny -1
    dsigma12dx_mat = 0.5*(dsigma12dx_mat_tmp[1:,:]+dsigma12dx_mat_tmp[:-1,:]) # Nx-2, Ny-1

    dsigma12dy_mat_tmp = np.diff(sigma_mat_temp[:,:,3], axis=1)/dys # Nx, Ny-1
    # dsigma12dy_mat = 0.5*(dsigma12dy_mat_tmp[1:,:] + dsigma12dy_mat_tmp[:-1,:]) # Nx-1, Ny-1
    dsigma12dy_mat = dsigma12dy_mat_tmp[1:-1,:] # Nx-2, Ny-1

    div_stress_mat = np.zeros((Nx-2,Ny-1,2), dtype=object)

    for i in range(Nx-2):
        for j in range(Ny-1):
            div_stress_mat[i,j,:] = np.array([
                dsigma1dx_mat[i,j] + dsigma12dy_mat[i,j],
                dsigma2dy_mat[i,j] + dsigma12dx_mat[i,j]
            ]
            )

    return muR_el, div_stress_mat, str_mat



# def calc_muR_el(c_mat, u_x, u_y, conf, trode, ind):
#     # shakul
#     Ny = np.size(c_mat, 1)
#     Nx = np.size(c_mat, 0)
#     dys = 1./(Ny-1)
#     dxs = 1./Nx

#     Nx = Nx - 1
#     Ny = Ny - 1

#     max_conc = conf[trode, "rho_s"]
#     T_ref = 298
#     k = 1.381e-23
#     N_A = 6.022e23
#     kT = k * T_ref
    
#     Cij, e0 = mech_tensors()
#     Cij = Cij*1e9

#     u_x_tmp = np.zeros((Nx,Ny), dtype=object) # Nx +1, Ny + 1
#     u_x_tmp[:,:] = u_x[:,:]

#     u_y_tmp = np.zeros((Nx,Ny), dtype=object) # Nx + 1, Ny + 1
#     u_y_tmp[:,:] = u_y[:,:]

#     e1_tmp = np.zeros((Nx,Ny), dtype=object)
#     e1_tmp = utils.mean_linear_diff_2D_ndiff(u_x_tmp,dxs,axis=0)
#     e1 = np.zeros((Nx,Ny), dtype=object)
#     e1[:,:] = e1_tmp[:,:]

#     e2_tmp = np.zeros((Nx,Ny), dtype=object)
#     e2_tmp = utils.mean_linear_diff_2D_ndiff(u_y_tmp,dys,axis=1)
#     e2 = np.zeros((Nx,Ny), dtype=object)
#     e2[:,:] = e2_tmp[:,:]

#     duydx = np.zeros((Nx,Ny), dtype=object)
#     duydx = utils.mean_linear_diff_2D_ndiff(u_y_tmp,dxs,axis=0)

#     duxdy = np.zeros((Nx,Ny), dtype=object)
#     duxdy = utils.mean_linear_diff_2D_ndiff(u_x_tmp,dys,axis=1)

#     e12 = 0.5*(duydx + duxdy) # Nx , Ny 

#     e_mat = np.zeros((Nx,Ny,6), dtype=object)
#     sigma_mat = np.zeros((Nx,Ny,6), dtype=object)

#     for i in range(Nx):
#         for j in range(Ny):
#             e_mat[i,j,:] = np.array([e1[i,j]- e0[0]*c_mat[i,j],
#                                     e2[i,j]- e0[1]*c_mat[i,j],
#                                     0,
#                                     e12[i,j],
#                                     0,
#                                     0])
#             sigma_mat[i,j,:] = np.dot(Cij,e_mat[i,j,:])
#     sigma_mat_temp = np.zeros((Nx+2,Ny+2,6), dtype=object)
#     sigma_mat_temp[1:-1,:-1,:] = sigma_mat[:,:,:]

#     muR_el = np.zeros((Nx+1,Ny+1), dtype=object)
#     for i in range(Nx+1):
#         for j in range(Ny+1):
#             muR_el[i,j] = np.dot(sigma_mat_temp[i,j,:],e0)/(kT * max_conc)
          
#     dsigma1dx_mat_temp = np.diff(sigma_mat_temp[:,:,0], axis=0)/dxs
#     dsigma1dx_mat = dsigma1dx_mat_temp[:-1,1:-1]

#     dsigma2dy_mat_temp = np.diff(sigma_mat_temp[:,:,1], axis=1)/dys
#     dsigma2dy_mat = dsigma2dy_mat_temp[1:-1,:-1]

#     dsigma12dx_mat_temp = np.diff(sigma_mat_temp[:,:,3], axis=0)/dxs
#     dsigma12dx_mat = dsigma12dx_mat_temp[:-1,1:-1]

#     dsigma12dy_mat_temp = np.diff(sigma_mat_temp[:,:,3], axis=1)/dys
#     dsigma12dy_mat = dsigma12dy_mat_temp[1:-1,:-1]

#     div_stress_mat = np.zeros((Nx,Ny,2), dtype=object)

#     for i in range(Nx):
#         for j in range(Ny):
#             div_stress_mat[i,j,:] = np.array([
#                 dsigma1dx_mat[i,j] + dsigma12dy_mat[i,j],
#                 dsigma2dy_mat[i,j] + dsigma12dx_mat[i,j]
#             ]
#             )

#     return muR_el, div_stress_mat

def MX(mat, objvec):
    if not isinstance(mat, sprs.csr.csr_matrix):
        raise Exception("MX function designed for csr mult")
    n = objvec.shape[0]
    if isinstance(objvec[0], dae.pyCore.adouble):
        out = np.empty(n, dtype=object)
    else:
        out = np.zeros(n, dtype=float)
    # Loop through the rows
    for i in range(n):
        low = mat.indptr[i]
        up = mat.indptr[i+1]
        if up > low:
            out[i] = np.sum(
                mat.data[low:up] * objvec[mat.indices[low:up]])
        else:
            out[i] = 0.0
    return out
