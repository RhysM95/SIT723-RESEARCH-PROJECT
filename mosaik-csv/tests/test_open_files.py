from os.path import dirname, join
import pytest
import mosaik
import platform
import psutil
from contextlib import contextmanager

if platform.system() != 'Windows':
    import resource

DATA_FILE = join(dirname(__file__), 'data', 'test.csv')
sim_config = {
    'CSV': {
        'python': 'mosaik_csv:CSV',
    }
}


def main():
    world = mosaik.World(sim_config)
    create_scenario(world)
    world.run(until=60)
    return world


@contextmanager
def not_raises(exception):
    """Counterpart to pytest's raises() method."""
    try:
        yield
    except exception:
        raise pytest.fail("DID RAISE {0}".format(exception))


def create_scenario(world):
    # Start simulators
    csv = world.start('CSV', sim_start='2014-01-01 00:00:00', datafile=DATA_FILE)

    # Instantiate models
    csv.ModelName.create(1)


def test_file_closed():
    proc = psutil.Process()
    world = main()
    open_files = [ifile.path for ifile in proc.open_files()]
    assert DATA_FILE not in open_files


@pytest.mark.skipif(platform.system()=='Windows', reason="Only works on linux.")
def test_many_worlds():
    # Manually set max open file limit to linux usual 1024, as IDEs might set it to much higher (e.g. 1048576)
    limit = 1024

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (limit, hard))

    # To stop python garbage collection, save old worlds' references in this list
    worlds = []
    for i in range(limit + 1):
        with not_raises(OSError):
            worlds.append(main())
