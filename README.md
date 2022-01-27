Development: [![Coverage Status](https://coveralls.io/repos/github/TRI-AMDD/mpet-dev/badge.svg?branch=development)](https://coveralls.io/github/TRI-AMDD/mpet-dev?branch=development)
Master: [![Coverage Status](https://coveralls.io/repos/github/TRI-AMDD/mpet-dev/badge.svg?branch=master)](https://coveralls.io/github/TRI-AMDD/mpet-dev?branch=master)
# MPET -- Multiphase Porous Electrode Theory

This software is designed to run simulations of batteries with porous electrodes using porous electrode theory, which is a volume-averaged, multiscale approach to capture the coupled behavior of electrolyte and active material within electrodes. As a result, with physical parameter inputs and run protocols (specified current or voltage profiles), it makes predictions about the internal dynamics within a battery (electrolyte concentration and potential, solid phase concentrations, reaction rates, etc.) and also macroscopic, easily measurable electrochemical quantities such as total current and voltage. In this way, it is similar to the [`dualfoil`](http://www.cchem.berkeley.edu/jsngrp/fortran.html) code released by Newman and coworkers from Berkeley. This software has much of the functionality contained in `dualfoil` (it is currently missing, e.g., temperature dependence). However, beyond the standard porous electrode theory simulations, this software can also simulate electrodes in which the active materials phase separate using non-equilibrium thermodynamics within a phase field modeling framework. Such behavior is common in widely used electrode materials, including graphite and LiFePO4.

If you use this software in academic work, please cite the relevant references detailing its development as presented in the `LICENSE` file. For more details on the theory implemeneted in the code, see:

Smith, R. B., and Bazant M. Z., Multiphase Porous Electrode Theory, [Journal of the Electrochemical Society](https://doi.org/10.1149/2.0171711jes), 2017, 164 (11) E3291-E3310, [arXiv preprint](https://arxiv.org/abs/1702.08432).

## Prerequisites

1.  [Python 3.7](https://www.python.org/) with the following packages installed: `numpy`, `scipy`, `matplotlib`, `pyqt5`, and `h5py`.
2.  [DAE Tools](http://www.daetools.com/) version 1.9.0, which can be [downloaded here](https://sourceforge.net/projects/daetools/files/daetools/1.9.0/).

## Installation

1.  Install the prerequisites above.
2.  Download the [latest release of MPET](https://bitbucket.org/bazantgroup/mpet/downloads/?tab=tags), or clone a copy of this source code repository.
3.  Enter the mpet folder, and use the setup.py script to install the mpet Python package:
    - We recommend using the pip package manager: `pip install .`
    - The legacy approach also works: `python setup.py install`

MPET is also available on [PyPI](https://pypi.org/project/mpet/), the Python Package Index, and can be installed with `pip install mpet`.

## Simulation

1.  Copy the overall system parameters file, `configs/params_system.cfg`, to your working directory.
2.  Copy the material parameter files referred to in the system parameters file (e.g. `configs/params_LFP.cfg` and `configs/params__graphite_1param.cfg`) to the working directory.
3.  Edit `params_system.cfg` to suit the simulation you're trying to run. Be sure to reference a material parameters file for the cathode and optionally one (the same or separate file) for the anode.
4.  Edit the material parameters file(s) serving as the electrode materials.
5.  Run `mpetrun.py`, passing `params_system.cfg` as an argument:
    `mpetrun.py params_system.cfg`

The software will save the simulation output in a time-stamped subdirectory, which is also stamped with the name of the used system parameter file, within a directory called `history`. The data contents of the most recent output will also be copied to a directory called `sim_output`. Each output directory should contain:

- the output data (`.mat` file)
- copies of the input parameters files defining the simulation
- a copy of the daetools config parameters (e.g. solver tolerances)
- information about the script used to run the simulation
- information about the simulation (e.g. run time)
- processed, dimensional and nondimensional parameters as
  Python-pickled dictionary objects

## Running multiple simulations on a cluster
If you have many simulations you want to run, you can use `bin/run_jobs.py` to run them efficiently on a cluster using [Dask](https://dask.org), either locally or on a slurm or PBS cluster. Using the parallel running option requires the following packages to be installed: `dask distributed` and `dask-jobqueue`.

1. Follow steps 1-4 from the description above for each of the simulations you want to run. Then create a text file in your working directory containing the system parameter files for your simulations. This text file should contain the file names of each of the system parameter configuration files for which you want to run a simulation. For example, if you have all your parameter files saved in the `configs` directory, create: `configs/parallel_configs.txt`, which contains the lines:\
    <i>params_system.cfg\
    params_system_XX.cfg\
    params_system_YY.cfg</i>\
    etc.
2. Run multiple simulaiton on a cluster using `run_jobs.py`. Pass the text file containing the system parameter files (e.g. `configs/parallel_configs.txt`) and the cluster arguments:
    - `-s`: scheduler type. Options: `slurm`, `pbs`, and `local`. Default is `slurm`.
    - `-t`: Maximum walltime per job (hh:mm:ss format). Argument is not used with a local cluster.
    - `-n`: Number of CPU cores per job. Argument is not used with a local cluster.
    - `-m`: Max memory usage per job. When using a local cluster it sets the memory limit per worker process.
    - `-q`: Queue to use. Argument is not used with a local cluster.
    - `-d`: Port for Dask dashboard (default 4096).
    - `--min_jobs`: Minimum number of jobs to launch. Default = 1. Argument is not used with a local cluster.
    - `--max_jobs`: Maximum number of jobs to launch. Default = 1. Argument is not used with a local cluster.
3. The simulation output is the same as described above. For each simulation a separate output folder is created in the `history` folder.


## Analysis
Analyze output with `mpetplot.py`. Pass the output data directory, then use the optional plotting arguments. The options for `mpetplot.py` are:
- `-pt` for plotting types
- `-t` for saving output to text format
- `-s` for options to save the plot
- `-c` for color_map options that are used with plot type `cbar_{full,c,a}`
- `-st` to specify the smooth colormap used with plot type `cbar_{full,c,a}`

1.  Analyze output with plots using `mpetplot.py`. Pass output data directory, then use `-pt [plottype]` with one (or more) of the plot types listed below. Default is `v`.
    - e.g., voltage plot: `mpetplot.py sim_output -pt v`
    - other options (`full`, `c`, `a` indicate full cell, cathode, and anode):
      - `v` or `vt` -- voltage vs filling fraction or vs time
      - `curr` -- current vs time
      - `elytec{f}` -- electrolyte concentration (movie) or final snapshot with `f`
      - `elytep{f}` -- electrolyte potential (movie) or final snapshot with `f`
      - `elytei{f}` -- electrolyte current density (movie) or final snapshot with `f`
      - `surf_{c,a}` -- solid surface concentrations
      - `soc_{c,a}` -- overall utilization / state of charge of electrode
      - `csld_{c,a}` -- solid concentrations of particles in electrode (movie; used with `solidType_{c,a}` not homog)
      - `cbarLine_{c,a}` -- average concentration in each particle of electrode
      - `cbar_{full,c,a}` -- average solid concentrations as changing colors (movie)
        - There are two options for the color map type that is used: `smooth` or `discrete`. This can be set with the `-c` option, e.g., `mpetplot.py sim_output -pt cbar_full -c discrete`. The default value is `discrete`.
        - When using the `smooth` color map option, the colors are selected from colormao_custom.npz, which includes three options (`GnYlRd_1`, `GnYlRd_2`, and `GnYlRd_3`) that can be selected with the `st` option, e.g., `mpetplot.py sim_output -pt cbar_full -c discrete -st GnYlRd_1`. The default value is `GnYlRd_3`.
      - `bulkp_{c,a}` -- macroscopic electrode solid phase potential (movie)
2.  Alternatively, convert the output to plain text (csv) format using the -t text argument: `mpetplot.py sim_output -t text` (or replace `sim_output` with any subfolder in the `history` folder). Then analyze using whatever tools you prefer.

If you want to save output to a movie (or figure), use the `-s` option with the argument `save` or `saveonly`, e.g.,`mpetplot.py sim_output -pt cbar -s save`. The `save` argument shows the plot or movie and saves the output, whereas the `saveonly` option only does the latter.

Movie output requires that you have `ffmpeg` or `mencoder` (part of `MPlayer`) installed.

## Troubleshooting

Please use the Issues section of the Bitbucket repository (https://bitbucket.org/bazantgroup/mpet/issues) to file issues and/or bug reports with the software.
