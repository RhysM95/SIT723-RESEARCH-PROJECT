from os.path import dirname, join

import pytest

import mosaik_csv


DATA_FILE = join(dirname(__file__), 'data', 'test.csv')


def test_init_create():
    sim = mosaik_csv.CSV()
    meta = sim.init('sid', 1., sim_start='2014-01-01 00:00:00',
                    datafile=DATA_FILE)
    assert meta['models'] == {
        'ModelName': {
            'public': True,
            'params': [],
            'attrs': ['P', 'Q'],
        },
    }

    entities = sim.create(2, 'ModelName')

    assert entities == [
        {'eid': 'ModelName_%s' % i, 'type': 'ModelName', 'rel': []}
        for i in range(2)
    ]


def test_init_create_errors():
    sim = mosaik_csv.CSV()

    # Profile file not found
    pytest.raises(FileNotFoundError, sim.init, 'sid', 1.,
                  sim_start='2014-01-01 00:00:00', datafile='spam')

    # Invalid model name
    sim.modelname = 'foo'
    pytest.raises(ValueError, sim.create, 1, 'bar')


@pytest.mark.parametrize('start_date', [
    '2013-01-01 00:00:00',
    '2015-01-01 00:00:00',
])
def test_start_date_out_of_range(start_date):
    sim = mosaik_csv.CSV()
    pytest.raises(ValueError, sim.init, 'sid', 1., sim_start=start_date,
                  datafile=DATA_FILE)


@pytest.mark.parametrize('time_resolution, next_step', [
    (1., 60),
    (2., 30),
    (.5, 120),
])
def test_step_get_data(time_resolution, next_step):
    sim = mosaik_csv.CSV()
    sim.init('sid', time_resolution, sim_start='2014-01-01 00:00:00',
             datafile=DATA_FILE)
    sim.create(2, 'ModelName')

    ret = sim.step(0, {}, 60)
    assert ret == next_step
    data = sim.get_data({'ModelName_0': ['P', 'Q'],
                         'ModelName_1': ['P', 'Q']})
    assert data == {
        'ModelName_0': {'P': 0, 'Q': 1},
        'ModelName_1': {'P': 0, 'Q': 1},
    }

    sim.step(next_step, {}, 120)
    data = sim.get_data({'ModelName_0': ['P', 'Q'],
                         'ModelName_1': ['P', 'Q']})
    assert data == {
        'ModelName_0': {'P': 1, 'Q': 2},
        'ModelName_1': {'P': 1, 'Q': 2},
    }


def test_step_with_offset():
    sim = mosaik_csv.CSV()
    sim.init('sid', 1., sim_start='2014-01-01 00:03:00', datafile=DATA_FILE)
    sim.create(2, 'ModelName')

    sim.step(0, {}, 60)
    data = sim.get_data({'ModelName_0': ['P', 'Q'],
                         'ModelName_1': ['P', 'Q']})
    assert data == {
        'ModelName_0': {'P': 3, 'Q': 4},
        'ModelName_1': {'P': 3, 'Q': 4},
    }
    pytest.raises(IndexError, sim.step, 60, {}, 120)
