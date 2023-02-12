HouseholdSim
============

This is pseudo simulator to serve residual load profiles to mosaik.


Installation
------------

::

    $ pip install mosaik-householdsim

Tests
-----

You can run the tests with::

    $ git clone https://gitlab.com/mosaik/mosaik-householdsim
    $ cd mosaik-householdsim
    $ pip install -r requirements.txt
    $ pip install -e .
    $ pytest


Documentation
-------------

This simulator consists of a *model* (``householdsim/model.py``) and the
mosaik API implementation (``householdsim/mosaik.py``).

The model processes the data from a NumPy *\*.npz* file (see
``householdsim/test/test_model.py`` for an example of its layout). Basically,
the file contains a number of load profiles for a given period of time. It
also contains *ID lists* that describe which load profile belongs to which
node ID in a power grid. The first entry in an ID list relates to the first
entry of the profiles list, the second entry in the ID list to the second
load profile and so on. If the number of entries in the ID list is larger than
the number of load profiles, we start again with the first load profile.

Internally, the model works with minute. Since mosaik allows to set the time
resolution in the scenario (seconds as default), the mosaik API implementation
converts between them.

Usually, residual load profiles have a resolution of 15 minutes. It is no
problem for this simulator to step in 1 minute steps, though.
