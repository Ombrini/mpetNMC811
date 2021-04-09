# global constants

#: Reference temperature, K
T_ref = 298.
#: Boltzmann constant, J/(K particle)
k = 1.381e-23
#: Electron charge, C
e = 1.602e-19
#: Avogadro constant, particle / mol
N_A = 6.022e23
#: TODO: this parameter needs a name, C/mol
F = e * N_A
#: General particle classification (1 var)
two_var_types = ["diffn2", "CHR2", "homog2", "homog2_sdn"]
#: General particle classification (2 var)
one_var_types = ["ACR", "diffn", "CHR", "homog", "homog_sdn"]
#: Concentration, mol/m^3 = 1M
c_ref = 1000.

#: parameter that are defined per electrode with a _{electrode} suffix
PARAMS_PER_TRODE = ['Nvol', 'Npart', 'mean', 'stddev', 'cs0', 'simBulkCond', 'sigma_s',
                    'simPartCond', 'G_mean', 'G_stddev', 'L', 'P_L', 'poros', 'BruggExp',
                    'specified_psd']
#: subset of PARAMS_PER_TRODE that is defined for the separator as well
PARAMS_SEPARATOR = ['Nvol', 'L', 'poros', 'BruggExp']
#: parameters that are used with several names. TODO: can we get rid of these?
PARAMS_ALIAS = {'CrateCurr': '1C_current_density', 'n_refTrode': 'n', 'Tabs': 'T',
                'td': 't_ref', 'Omga': 'Omega_a', 'Omgb': 'Omega_b', 'Omgc': 'Omega_c'}
