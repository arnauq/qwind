import numpy as np
import qwind.constants as const
from qwind import radiation
from scipy import interpolate
from multiprocessing import Pool
from qwind import utils
import os
import shutil
import pandas as pd
from numba import jitclass, jit
from qwind import aux_numba


# check backend to import appropiate progress bar #
def tqdm_dump(array):
    return array
backend = utils.type_of_script()
if(backend == 'jupyter'):
    from tqdm import tqdm_notebook as tqdm
else:
    tqdm = tqdm_dump

def evolve(line, niter):
    line.iterate(niter=niter)
    return line

class Qwind:
    """
    A class used to represent the global properties of the wind, i.e, the accretion disc and black hole properties as well as attributes shared among streamlines.
    """
    def __init__(self, 
                M = 2e8,
                mdot = 0.5, 
                spin=0.,
                eta=0.06, 
                r_in = 200, 
                r_out = 1600, 
                r_min = 6., 
                r_max=1400, 
                T = 2e6, 
                mu = 1, 
                modes = [], 
                rho_shielding = 2e8, 
                intsteps=1, 
                nr=20, 
                save_dir="Results", 
                radiation_mode = "Qwind", 
                n_cpus = 1):
        """
        Parameters
        ----------
        r_init : float
            Radius of the first streamline to launch, in Rg units.
        M : float
            Black Hole Mass in solar mass units.
        mdot : float
            Accretion rate (mdot = L / Ledd)
        spin : float
            Spin black hole parameter between [0,1]
        eta : float
            Accretion efficiency (default is for scalar black hole).
        Rmin : float
            Minimum radius of acc. disc, default is ISCO for scalar black hole.
        Rmax : float
            Maximum radius of acc. disc.
        T : float
            Temperature of the disc atmosphere. Wind is assumed to be isothermal.
        mu : float
            Mean molecular weight ( 1 = pure atomic hydrogen)
        modes : list 
            List of modes for debugging purposes. Available modes are:
                - 'old_integral': Non adaptive disc integration (much faster but convergence is unreliable.)
                - 'altopts': Alternative opacities (experimental)
                - 'gravityonly': Disable radiation force, very useful for debugging.
        rho_shielding : float
            Initial density of the shielding material.
        intsteps : int
            If old_integral mode enabled, this refined the integration grid.
        save_dir : str
            Directory to save results.
        """

        self.n_cpus = n_cpus
        
        # array containing different modes for debugging #
        self.modes = modes
        # black hole and disc variables #
        self.M = M * const.Ms
        self.mdot = mdot
        self.spin = spin
        self.mu = mu
        self.r_min = r_min 
        self.r_max = r_max 
        self.eta = eta

        
        self.Rg = const.G * self.M / (const.c ** 2) # gravitational radius
        self.rho_shielding = rho_shielding
        self.bol_luminosity = self.mdot * self.eddington_luminosity
        self.radiation = radiation.Radiation(self)
        self.r_in = 2. * self.radiation.sed_class.corona_radius
        self.r_out = self.radiation.sed_class.gravity_radius
        if('old_boundaries' in self.modes or 'old' in self.modes):
            self.r_in = r_in
            self.r_out = r_out
        print("r_in: %f \n r_out: %f"%(self.r_in, self.r_out))
        self.tau_dr_0 = self.tau_dr(rho_shielding)
        self.v_thermal = self.thermal_velocity(T)
       
        # create directory if it doesnt exist. Warning, this overwrites previous outputs.
        self.save_dir = save_dir
        try:
            os.mkdir(save_dir)
        except BaseException:
            pass

        self.radiation = radiation.Radiation(self)
        
        self.reff_hist = [0] # for debugging
        dr = (self.r_out - self.r_in) / (nr -1)
        self.lines_r_range = [self.r_in + (i-0.5) * dr for i in range(1,nr+1)]
        self.r_init = self.lines_r_range[0]

        self.nr = nr
        self.lines = [] # list of streamline objects
        self.lines_hist = [] # save all iterations info

    def norm2d(self, vector):
        return np.sqrt(vector[0] ** 2 + vector[-1] ** 2)
    
    def dist2d(self, x, y):
        # 2d distance in cyl coordinates #
        dr = y[0] - x[0]
        dz = y[2] - x[2]
        return np.sqrt(dr**2 + dz**2)   
    
    def v_kepler(self, r ):
        """
        Keplerian tangential velocity in units of c.
        """
        
        return np.sqrt(1. / r)

    def v_esc(self,d):
        """
        Escape velocity in units of c.
        
        Parameters
        -----------
        d : float
            spherical radial distance.
        """
        
        return np.sqrt(2. / d)

    @property
    def eddington_luminosity(self):
        """ 
        Returns the Eddington Luminosity. 
        """
        return const.emissivity_constant * self.Rg

    def thermal_velocity(self, T):
        """
        Thermal velocity for gas with molecular weight mu and temperature T
        """
        
        return np.sqrt(const.k_B * T / (self.mu * const.m_p)) / const.c

    def tau_dr(self, density):
        """ 
        Differential optical depth.
        
        Parameters
        -----------
        opacity : float
            opacity of the material.
        density : float
            shielding density.
        """
        tau_dr = const.sigma_t * self.mu * density * self.Rg
        return tau_dr
    
    def line(self,
            r_0=375.,
            z_0=10., 
            rho_0=2e8,
            T=2e6,
            v_r_0=0.,
            v_z_0=1e7,
            dt=4.096 / 10.
            ):
        """
        Initialises a streamline object.
        
        Parameters
        -----------
        r_0 : float
            Initial radius in Rg units.
        z_0: float
            Initial height in Rg units.
        rho_0 : float
            Initial number density. Units of 1/cm^3.
        T : float
            Initial stramline temperature.
        v_r_0 : float
            Initial radial velocity in units of cm/s.
        v_z_0 : float
            Initial vertical velocity in units of cm/s.
        dt : float
            Timestep in units of Rg/c.
        """
        from qwind.streamline import streamline
        return streamline(
            self.radiation,
            parent = self,
            r_0 = r_0,
            z_0 = z_0,
            rho_0 = rho_0,
            T = T,
            v_r_0 = v_r_0,
            v_z_0 = v_z_0,
            dt = dt
            )

    
    def start_lines(self, v_z_0 = 1e7, niter=5000):        
        """
        Starts and evolves a set of equally spaced streamlines.
        
        Parameters
        -----------
        nr : int 
            Number of streamlines.
        v_z_0 : float
            Initial vertical velocity.
        niter : int 
            Number of timesteps.
        """
        print("Starting line iteration")

        self.lines = []

        for i, r in enumerate(self.lines_r_range):
            if ('custom_vel' in self.modes or 'old' in self.modes):
                v_z_0 = v_z_0
            elif ( r > self.radiation.sed_class.corona_radius):
                if ( r < 2 * self.radiation.sed_class.corona_radius):
                    v_z_0 = self.thermal_velocity(2e6) * const.c
                else:
                    v_z_0 = self.thermal_velocity(self.radiation.sed_class.disk_temperature4(r)**(1./4.)) * const.c
            else:
                print("streamline would be inside corona radius, ignoring.")
                continue
            self.lines.append(self.line(r_0=r,v_z_0=v_z_0))
        i = 0
        if(self.n_cpus==1):
            for line in self.lines:
               i += 1
               print("Line %d of %d"%(i, len(self.lines)))
               line.iterate(niter=niter)
            return self.lines
        print("multiple cpus")
        niter_array = niter * np.ones(len(self.lines))
        niter_array = niter_array.astype('int')

        with Pool(self.n_cpus) as multiprocessing_pool:
            self.lines = multiprocessing_pool.starmap(evolve, zip(self.lines, niter_array))
        self.mdot_w = self.compute_wind_mass_loss()
        return self.lines

    def compute_wind_mass_loss(self):
        """
        Computes wind mass loss rate after evolving the streamlines.
        """
        escaped_mask = []
        for line in self.lines:
            escaped_mask.append(line.escaped)
        escaped_mask = np.array(escaped_mask, dtype = int)
        wind_exists = False
        lines_escaped = np.array(self.lines)[escaped_mask == True]

        if(len(lines_escaped) == 0):
            print("No wind escapes")
            return 0 

        dR = self.lines_r_range[1] - self.lines_r_range[0]
        mdot_w_total = 0

        for line in lines_escaped:
            area = 2 * np.pi * ( (line.r_0 + dR)**2. - line.r_0**2) * self.Rg**2.
            mdot_w = line.rho_0 * const.m_p * line.v_T_0 * const.c * area
            mdot_w_total += mdot_w

        return mdot_w_total

if __name__ == '__main__':
    qwind = Qwind( M = 1e8, mdot = 0.1, rho_shielding = 2e8,  n_cpus = 4, nr = 4)
    qwind.start_lines(niter=50000)
    utils.save_results(qwind,"Results")
