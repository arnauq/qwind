# physical constants #
import astropy.constants as astroconst
from astropy import units as u
import scipy.constants as const
import numpy as np

# basic physical constants #
G = astroconst.G.cgs.value
Ms = astroconst.M_sun.cgs.value
c = astroconst.c.cgs.value
m_p = astroconst.m_p.cgs.value
k_B = astroconst.k_B.cgs.value
Ryd = u.astrophys.Ry.cgs.scale
sigma_sb = astroconst.sigma_sb.cgs.value
sigma_t = const.physical_constants['Thomson cross section'][0] * 1e4
year = u.yr.cgs.scale

# useful normalization factors #
ionization_parameter_critical = 1e5 # / ( 4 * np.pi * Ryd * c)
emissivity_constant = 4 * np.pi * m_p * c**3 / sigma_t # GE in qwind

def convert_units(value, current_unit, new_unit):
    """
    Convinient function to convert units using astropy.
    """
    try: # make sure value is unitless
        value = value.value
    except:
        value = value

    current = value * current_unit 
    new = current.to(new_unit)
    return new.value


