mosaik-csv
==========

This is pseudo simulator that presents CSV data sets to mosaik as models.

The following code shows an example how to use the mosaik-csv simulator.
The date_format and delimiter parameter are optional.
If they are not defined the standard value is 'YYYY-MM-DD HH:mm:ss' for the date_format and ',' for delimiter.::

    sim_config = {
        'CSV': {
            'python': 'mosaik_csv:CSV',
        }
    }
    world = mosaik.World(sim_config)
    csv_sim = world.start('CSV', sim_start='01.01.2016 00:00',
                                datafile='data.csv',
                                date_format='DD.MM.YYYY HH:mm',
                                delimiter=',')
    csv = csv_sim.CSV.create(20)

Installation
------------

::

    $ pip install mosaik-csv

Tests
-----

You can run the tests with::

    $ git clone https://gitlab.com/mosaik/mosaik-csv.git
    $ cd mosaik-csv
    $ pip install -r requirements.txt
    $ pip install -e .
    $ pytest tests

If installation of psutil fails, installing python developer edition and gcc should help::

    $ sudo apt-get install gcc python3-dev
