"""
The simulation manager is responsible for starting simulation processes and
shutting them down. It also manages the communication between mosaik and the
processes.

It is able to start pure Python simulators in-process (by importing and
instantiating them), to start external simulation processes and to connect to
already running simulators and manage access to them.
"""
from __future__ import annotations

from ast import literal_eval
from itertools import count

import collections
import copy
import heapq as hq
import importlib
import os
import shlex
import subprocess
import sys
from loguru import logger

from simpy.io import select as backend
from simpy.io.packet import PacketUTF8 as Packet
from simpy.io.json import JSON as JSON_RPC  # JSON is actually an object
from mosaik import _version
import mosaik_api

from mosaik.exceptions import ScenarioError, SimulationError
from mosaik.util import sync_process

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from typing import Any, Callable, Dict, Iterable, List, Literal, Optional, OrderedDict, Tuple, Union
    from simpy.events import Event, Process
    from mosaik.scenario import Meta, OutputData, SimId, World, DataflowEdge

API_MAJOR = _version.VERSION_INFO[0]  # Current major version of the sim API
API_MINOR = _version.VERSION_INFO[1]  # Current minor version of the sim API
API_VERSION = '%s.%s' % (API_MAJOR, API_MINOR)  # Current version of the API
FULL_ID_SEP = '.'  # Separator for full entity IDs
FULL_ID = '%s.%s'  # Template for full entity IDs ('sid.eid')


def start(
    world: World,
    sim_name: str,
    sim_id: SimId,
    time_resolution: float,
    sim_params: Dict[str, Any],
):
    """
    Start the simulator *sim_name* based on the configuration im
    *world.sim_config*, give it the ID *sim_id* and pass the time_resolution
    and the parameters of the dict *sim_params* to it.

    The sim config is a dictionary with one entry for every simulator. The
    entry itself tells mosaik how to start the simulator::

        {
            'ExampleSimA': {
                'python': 'example_sim.mosaik:ExampleSim',
            },
            'ExampleSimB': {
                'cmd': 'example_sim %(addr)s',
                'cwd': '.',
            },
            'ExampleSimC': {
                'connect': 'host:port',
            },
        }

    *ExampleSimA* is a pure Python simulator. Mosaik will import the module
    ``example_sim.mosaik`` and instantiate the class ``ExampleSim`` to start
    the simulator.

    *ExampleSimB* would be started by executing the command *example_sim* and
    passing the network address of mosaik das command line argument. You can
    optionally specify a *current working directory*. It defaults to ``.``.

    *ExampleSimC* can not be started by mosaik, so mosaik tries to connect to
    it.

    *time_resolution* (in seconds) is a global scenario parameter, which tells
    the simulators what the integer time step means in seconds. Its default
    value is 1., meaning one integer step corresponds to one second simulated
    time.

    The function returns a :class:`mosaik_api.Simulator` instance.

    It raises a :exc:`~mosaik.exceptions.SimulationError` if the simulator
    could not be started.

    Return a :class:`SimProxy` instance.
    """
    try:
        sim_config = world.sim_config[sim_name]
    except KeyError:
        raise ScenarioError('Simulator "%s" could not be started: Not found '
                            'in sim_config' % sim_name)

    # Try available starters in that order and raise an error if none of them
    # matches. Default starters are:
    # - python: start_inproc
    # - cmd: start_proc
    # - connect: start_connect
    starters = StarterCollection()

    for sim_type, start in starters.items():
        if sim_type in sim_config:
            proxy = start(world, sim_name, sim_config, sim_id, time_resolution,
                          sim_params)
            try:
                proxy.meta['api_version'] = validate_api_version(  # type: ignore
                    proxy.meta['api_version'])
                type_check(proxy.meta, sim_name, sim_id)
                proxy.meta = expand_meta(proxy.meta, sim_name)
                return proxy
            except ScenarioError as se:
                raise ScenarioError('Simulator "%s" could not be started:'
                                    ' Invalid version "%s": %s' %
                                    (sim_name, proxy.meta['api_version'], se))
    else:
        raise ScenarioError('Simulator "%s" could not be started: '
                            'Invalid configuration' % sim_name)


def start_inproc(
    world: World,
    sim_name: str,
    sim_config: Dict[Literal['python', 'env'], str],
    sim_id: SimId,
    time_resolution: float,
    sim_params: Dict[str, Any]
) -> SimProxy:
    """
    Import and instantiate the Python simulator *sim_name* based on its
    config entry *sim_config*.

    Return a :class:`LocalProcess` instance.

    Raise a :exc:`~mosaik.exceptions.ScenarioError` if the simulator cannot be
    instantiated.
    """
    try:
        mod_name, cls_name = sim_config['python'].split(':')
        mod = importlib.import_module(mod_name)
        cls = getattr(mod, cls_name)
    except (AttributeError, ImportError, KeyError, ValueError) as err:
        if sys.version_info.major <= 3 and sys.version_info.minor < 6:
            detail_msgs = {
                ValueError: 'Malformed Python class name: Expected "module:Class"',
                ImportError: 'Could not import module: %s' % err.args[0],
                AttributeError: 'Class not found in module',
            }
        else:
            detail_msgs = {
                ValueError: 'Malformed Python class name: Expected "module:Class"',
                ModuleNotFoundError: 'Could not import module: %s' % err.args[0],
                AttributeError: 'Class not found in module',
            }
        details = detail_msgs[type(err)]
        origerr = err.args[0]
        raise ScenarioError('Simulator "%s" could not be started: %s --> %s' %
                            (sim_name, details, origerr)) from None
    sim = cls()

    if int(mosaik_api.__version__.split('.')[0]) < 3:
        raise ScenarioError("Mosaik 3 requires mosaik_api's version also "
                            "to be >=3.")

    # Check if the simulator's api implementation complies with api 3, and
    # raise a deprecation warning otherwise. Compliance should be enforced
    # after a reasonable time after the release of mosaik 3.
    api_compliant = mosaik_api.check_api_compliance(sim)
    if api_compliant:
        time_resolution_dict = {'time_resolution': time_resolution}
    else:
        time_resolution_dict = {}

    meta = sim.init(sim_id, **time_resolution_dict, **sim_params)
    # "meta" is module global and thus shared between all "LocalProcess"
    # instances. This may lead to problems if a user modifies it, so make
    # a deep copy of it for each instance:
    meta = copy.deepcopy(meta)
    return LocalProcess(sim_name, sim_id, meta, sim, world)


def start_proc(
    world: World,
    sim_name: str,
    sim_config: Dict[Literal['cmd', 'cwd', 'env'], str],
    sim_id: SimId,
    time_resolution: float,
    sim_params: Dict[str, Any]
) -> SimProxy:
    """
    Start a new process for simulator *sim_name* based on its config entry
    *sim_config*.

    Return a :class:`RemoteProcess` instance.

    Raise a :exc:`~mosaik.exceptions.ScenarioError` if the simulator cannot be
    instantiated.
    """
    replacements = {
        'addr': '%s:%s' % (world.config['addr'][0], world.config['addr'][1]),
        'python': sys.executable,
    }
    cmd = sim_config['cmd'] % replacements
    if 'posix' in sim_params.keys():
        posix = sim_params.pop('posix')
        cmd = shlex.split(cmd, posix=posix)
    else:
        cmd = shlex.split(cmd, posix=(os.name != 'nt'))
    cwd = sim_config['cwd'] if 'cwd' in sim_config else '.'

    # Make a copy of the current env. vars dictionary and update it with the
    # user provided values (or an empty dict as a default):
    env = dict(os.environ)
    env.update(sim_config.get('env', {}))  # type: ignore

    kwargs = {
        'bufsize': 1,
        'cwd': cwd,
        'universal_newlines': True,
        'env': env,  # pass the new env dict to the sub process
    }
    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except (FileNotFoundError, NotADirectoryError) as e:
        # This distinction has to be made due to a change in python 3.8.0.
        # It might become unecessary for future releases supporting
        # python >= 3.8 only.
        if str(e).count(':') == 2:
            eout = e.args[1]
        else:
            eout = str(e).split('] ')[1]
        raise ScenarioError('Simulator "%s" could not be started: %s'
                            % (sim_name, eout)) from None

    proxy = make_proxy(world, sim_name, sim_config, sim_id, time_resolution,
                       sim_params, proc=proc)
    return proxy


def start_connect(
    world: World,
    sim_name: str,
    sim_config,
    sim_id: SimId,
    time_resolution: float,
    sim_params: Dict[str, Any]
):
    """
    Connect to the already running simulator *sim_name* based on its config
    entry *sim_config*.

    Return a :class:`RemoteProcess` instance.

    Raise a :exc:`~mosaik.exceptions.ScenarioError` if the simulator cannot be
    instantiated.
    """
    addr = sim_config['connect']
    try:
        host, port = addr.strip().split(':')
        addr = (host, int(port))
    except ValueError:
        raise ScenarioError('Simulator "%s" could not be started: Could not '
                            'parse address "%s"' %
                            (sim_name, sim_config['connect'])) from None

    proxy = make_proxy(world, sim_name, sim_config, sim_id,
                       time_resolution, sim_params, addr=addr)
    return proxy


def make_proxy(world, sim_name, sim_config, sim_id, time_resolution,
               sim_params, proc=None, addr=None) -> SimProxy:
    """
    Try to establish a connection with *sim_name* and perform the ``init()``
    API call.

    Return a new :class:`RemoteProcess` sim proxy.

    Raise a :exc:`~mosaik.exceptions.ScenarioError` if something goes wrong.

    This method is a SimPy process used by :func:`start_proc()` and
    :func:`start_connect()`.
    """
    start_timeout = world.env.timeout(world.config['start_timeout'])

    def greeter():
        if proc:
            # Wait for connection from "sim_name"
            accept_con = world.srv_sock.accept()
            results = yield accept_con | start_timeout
            if start_timeout in results:
                raise SimulationError('Simulator "%s" did not connect to '
                                      'mosaik in time.' % sim_name)
            else:
                sock = results[accept_con]
        else:
            # Connect to "sim_name"
            try:
                sock = backend.TCPSocket.connection(world.env, addr)
            except (ConnectionError, OSError):
                raise SimulationError('Simulator "%s" could not be started: '
                                      'Could not connect to "%s"' %
                                      (sim_name, sim_config['connect']))

        rpc_con = JSON_RPC(Packet(sock, max_packet_size=10 * 1024 * 1024))

        # Make init() API call and wait for sim_name's meta data.
        init = rpc_con.remote.init(sim_id, time_resolution=time_resolution,
                                   **sim_params)
        try:
            results = yield init | start_timeout
        except ConnectionError as e:
            raise SimulationError('Simulator "%s" closed its connection during'
                                  ' the init() call.' % sim_name, e)

        if start_timeout in results:
            raise SimulationError('Simulator "%s" did not reply to the init() '
                                  'call in time.' % sim_name)
        else:
            meta = results[init]

        return RemoteProcess(sim_name, sim_id, meta, proc, rpc_con, world)

    # Add a error callback that waits for "proc" to stop if "proc" is not None:
    def terminate():
        try:
            # See if it terminates on its own ...
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            # ... or kill it ...
            proc.terminate()
            proc.wait(timeout=1)

    cb = None if proc is None else terminate
    return sync_process(greeter(), world, errback=cb)


def validate_api_version(
    version: str
) -> Union[Tuple[int, int], Tuple[int, int, int]]:
    """
    Validate the *version*.

    Raise a :exc: `ScenarioError` if the version format is wrong or
    does not match the min requirements.
    """
    try:
        version_tuple = str(version).split('.')
        v_tuple = tuple(map(int, version_tuple))
    except ValueError:
        raise ScenarioError('Version parts of %r must be integer' %
                            version) from None
    if len(v_tuple) < 2:
        raise ScenarioError('Version must follow at least the format '
                            '"major.minor" and can optionally include '
                            'the patch version like "major.minor.patch", '
                            'but is %r' % version) from None
    if not (v_tuple[0] == API_MAJOR and v_tuple[1] <= API_MINOR):
        raise ScenarioError('Version must be between %(major)s.0 and '
                            '%(major)s.%(minor)s' % {'major': API_MAJOR,
                                                     'minor': API_MINOR})

    return v_tuple


def expand_meta(meta: Meta, sim_name: str):
    """
        Checks if (non-)triggering attributes ("(non-)trigger") are given and
        adds them to each model's meta data if necessary.

        Raise a :exc: `ScenarioError` if the given values are not consistent.
        """
    sim_type = meta['type']

    for model, model_meta in meta['models'].items():
        attrs = set(model_meta.get('attrs', []))
        trigger = model_meta.setdefault('trigger', [])
        if trigger is True:
            trigger = attrs
        trigger = set(trigger)
        non_trigger = set(model_meta.get('non-trigger', []))
        if any(i in trigger for i in non_trigger):
            raise ScenarioError('Triggering and non-triggering attributes must'
                                ' not overlap, but actually do for model '
                                f'{model} of simulator {sim_name}.')  # TODO: Add overlapping attrs
        if trigger and non_trigger:
            if trigger.union(non_trigger) != attrs:
                raise ScenarioError('Triggering and non-triggering attributes '
                                    'have to be a disjoint split of attrs, '
                                    f'but are not for {model} of simulator '
                                    f'{sim_name}.')
        elif trigger:
            if not trigger.issubset(attrs):
                raise ScenarioError('Triggering attributes must be a subset of'
                                    f' attrs, but are not for {model} of '
                                    f'simulator {sim_name}.')
        elif non_trigger:
            trigger = attrs - non_trigger
        else:
            if sim_type == 'event-based':
                trigger = attrs

        model_meta['trigger'] = trigger

        if sim_type == 'time-based':
            model_meta['persistent'] = attrs
        elif sim_type == 'hybrid':
            non_persistent = model_meta.get('non-persistent', [])
            if non_persistent is True:
                non_persistent = attrs
            non_persistent = set(non_persistent)
            model_meta['persistent'] = attrs - non_persistent
        else:
            model_meta['persistent'] = []

    return meta


def type_check(meta, sim_name, sim_id):
    """
        Checks if  meta's type exists and is correctly set.
        Raise a :exc: `ScenarioError` if the type ist not correct.
        """
    if 'type' not in meta:
        sim_type = meta['type'] = 'time-based'
        meta['old-api'] = True
        logger.warning('DEPRECATION: Simulator {sim_name}\'s meta doesn\'t '
                       'contain a type. \'{sim_type}\' is set as default. '
                       'This might cause an error in future releases.',
                       sim_name=sim_name, sim_type=sim_type)
    else:
        types = ['time-based', 'event-based', 'hybrid']
        if meta['type'] not in types:
            typo = meta['type']
            meta['type'] = 'time-based'
            raise ScenarioError(f'{sim_id} contains an unknown type: \'{typo}\'. '
                                f'Please check for typos in your Simulators \'{sim_name}\' meta and scenario.')


class SimProxy:
    """
    Handler for an external simulator.

    It stores its simulation state and own the proxy object to the external
    simulator.
    """

    name: str
    """The name of this simulator (in the SIM_CONFIG)."""
    sid: SimId
    """This simulator's ID."""
    meta: Meta
    """This simulator's meta."""

    proxy: Any
    """The actual proxy for this simulator."""

    rt_start: float
    """The real time when this simulator started (as returned by
    `perf_counter()`."""

    next_steps: List[int]
    """The scheduled next steps this simulator will take, organized as a heap.
    Once the immediate next step has been chosen (and the `has_next_step` event
    has been triggered), the step is moved to `next_step` instead."""
    next_step: Optional[int]
    """This simulator's immediate next step once it has been determined. The
    step is removed from the `next_steps` heap at that point and the
    `has_next_step` event is triggered."""
    has_next_step: Event
    """An event that is triggered once this simulator's next step has been
    determined."""
    next_self_step: Optional[int]
    """The next self-scheduled step for this simulator."""
    interruptable: bool
    """Set when this simulator's next step has been scheduled but it is still
    waiting for dependencies which might trigger earlier steps for this
    simulator."""

    predecessors: Dict[Any, Tuple[SimProxy, DataflowEdge]]
    """This simulator's predecessors in the dataflow graph and the corresponding
    edges."""
    successors: Dict[Any, Tuple[SimProxy, DataflowEdge]]
    """This simulator's successors in the dataflow graph and the corresponding
    edge.."""
    triggering_ancestors: Iterable[Tuple[SimId, bool]]
    """
    An iterable of this sim's ancestors that can trigger a step of this
    simulator. The second component specifies whether the connecting is weak or
    time-shifted (False) or immediate (True).
    """

    input_buffer: Dict
    """Inputs received via `set_data`."""
    input_memory: Dict
    """Memory of previous inputs for persistent attributes."""
    timed_input_buffer: TimedInputBuffer
    """'Usual' inputs. (But also see `world._df_cache`.)"""

    progress: int
    """This simulator's progress in mosaik time.

    This simulator has done all its work before time `progress`; its next stept will be
    at time `progress` or later. For time-based simulators, the next step will happen
    at time `progress`."""
    last_step: int
    """The most recent step this simulator performed."""

    output_time: int
    """The output time associated with `data`. Usually, this will be equal to
    `last_step` but simulators may specify a different time for their output."""
    data: OutputData
    """The newest data returned by this simulator."""
    related_sims: Iterable[SimProxy]
    """Simulators related to this simulator. (Currently all other simulators.)"""
    sim_proc: Process
    """The SimPy process for this simulator."""
    wait_events: Event
    """The event (usually an AllOf event) this simulator is waiting for."""

    def __init__(self, name: str, sid: SimId, meta: Meta, world: World):
        self.name = name
        self.sid = sid
        self.meta = meta
        self._world = world

        # Meta data and remote method checks
        api_methods = [
            # "init" was called before the SimProxy was created
            'create',
            'setup_done',
            'step',
            'get_data',
        ]
        # Set default value for optional "extra_methods" property
        extra_methods = meta.setdefault('extra_methods', [])

        self._check_model_and_meth_names(meta['models'], api_methods,
                                         extra_methods)

        # Set default value for optional "any_inputs" property
        for model, props in meta['models'].items():
            props.setdefault('any_inputs', False)

        # Actual proxy object
        self.proxy = self._get_proxy(api_methods + extra_methods)

        # Simulation state
        self.last_step = -1
        if self.meta.get('type', 'time-based') != 'event-based':
            self.next_steps = [0]
        else:
            self.next_steps = []
        self.next_self_step = None
        self.progress = 0
        self.input_buffer = {}  # Buffer used by "MosaikRemote.set_data()"
        self.input_memory = {}
        self.timed_input_buffer = TimedInputBuffer()
        self.buffered_output = {}
        self.sim_proc = None  # type: ignore  # will be set in Mosaik's init
        self.has_next_step = None  # type: ignore
        self.wait_events = None  # type: ignore
        self.interruptable = False
        self.is_in_step = False
        self.trigger_cycles = []
        self.rank = None  # topological rank

    def stop(self):
        """
        Stop the simulator behind the proxy.

        The default implementation does nothing.
        """
        raise NotImplementedError

    def _get_proxy(self, methods):
        raise NotImplementedError

    def _check_model_and_meth_names(self, models, api_methods, extra_methods):
        """
        Check if there are any overlaps in model names and reserved API
        methods as well as in them and extra API methods.

        Raise a :exc:`~mosaik.exception.ScenarioError` if that's the case.
        """
        models = list(models)
        illegal_models = set(models) & set(api_methods)
        if illegal_models:
            raise ScenarioError('Simulator "%s" uses illegal model names: %s'
                                % (self.sid, ', '.join(illegal_models)))

        illegal_meths = set(models + api_methods) & set(extra_methods)
        if illegal_meths:
            raise ScenarioError('Simulator "%s" uses illegal extra method '
                                'names: %s' %
                                (self.sid, ', '.join(illegal_meths)))


class LocalProcess(SimProxy):
    """
    Proxy for internal simulators.
    """

    def __init__(self, name, sid, meta, inst, world):
        self._inst = inst

        # Add MosaikRemote and patch its RPC methods to return events:
        inst.mosaik = MosaikRemote(world, sid)
        for attr in dir(inst.mosaik):
            if attr.startswith('_'):
                continue

            func = getattr(inst.mosaik, attr)
            if hasattr(func, '__call__') and hasattr(func, 'rpc'):
                setattr(inst.mosaik, attr,
                        mosaik_api.get_wrapper(func, world.env))

        super().__init__(name, sid, meta, world)

    def stop(self):
        """
        Yield a triggered event but do nothing else.
        """
        self._inst.finalize()
        yield self._world.env.event().succeed()

    def _get_proxy(self, methods):
        """
        Return a proxy for the local simulator.
        """
        proxy_dict = {
            name: mosaik_api.get_wrapper(getattr(self._inst, name),
                                         self._world.env)
            for name in methods
        }
        Proxy = type('Proxy', (), proxy_dict)
        return Proxy


class RemoteProcess(SimProxy):
    """
    Proxy for external simulator processes.
    """

    def __init__(self, name, sid, meta, proc, rpc_con, world):
        self._proc = proc
        self._rpc_con = rpc_con
        self._mosaik_remote = MosaikRemote(world, sid)
        self._stop_timeout = world.config['stop_timeout']
        rpc_con.router = self._mosaik_remote.rpc
        super().__init__(name, sid, meta, world)

    def stop(self):
        """
        Send a *stop* message to the process represented by this proxy and
        wait for it to terminate.
        """
        try:
            timeout = self._world.env.timeout(self._stop_timeout)
            res = yield (self._rpc_con.remote.stop() | timeout)
            if timeout in res:
                logger.warning('Simulator "{sim_id}" did not close its connection in time.',
                               sim_id=self.sid)
                self._rpc_con.close()
        except ConnectionError:
            # We may get a ConnectionError if the remote site closes its
            # socket during the "stop()" call.
            pass

        if self._proc:
            self._proc.wait()

    def _get_proxy(self, methods):
        """
        Return a proxy object for the remote simulator.
        """
        return self._rpc_con.remote


class MosaikRemote:
    """
    This class provides an RPC interface for remote processes to query
    mosaik and other processes (simulators) for data while they are executing
    a ``step()`` command.
    """

    @JSON_RPC.Descriptor
    class rpc(JSON_RPC.Accessor):
        parent = None

    def __init__(self, world, sim_id):
        self.world = world
        self.sim_id = sim_id

    @rpc
    def get_progress(self):
        """
        Return the current simulation progress from
        :attr:`~mosaik.scenario.World.sim_progress`.
        """
        return self.world.sim_progress

    @rpc
    def get_related_entities(self, entities=None):
        """
        Return information about the related entities of *entities*.

        If *entities* omitted (or ``None``), return the complete entity
        graph, e.g.::

            {
                'nodes': {
                    'sid_0.eid_0': {'type': 'A'},
                    'sid_0.eid_1': {'type': 'B'},
                    'sid_1.eid_0': {'type': 'C'},
                },
                'edges': [
                    ['sid_0.eid_0', 'sid_1.eid0', {}],
                    ['sid_0.eid_1', 'sid_1.eid0', {}],
                ],
            }

        If *entities* is a single string (e.g., ``sid_1.eid_0``), return a dict
        containing all entities related to that entity::

            {
                'sid_0.eid_0': {'type': 'A'},
                'sid_0.eid_1': {'type': 'B'},
            }

        If *entities* is a list of entity IDs (e.g., ``['sid_0.eid_0',
        'sid_0.eid_1']``), return a dict mapping each entity to a dict of
        related entities::

            {
                'sid_0.eid_0': {
                    'sid_1.eid_0': {'type': 'B'},
                },
                'sid_0.eid_1': {
                    'sid_1.eid_1': {'type': 'B'},
                },
            }
        """
        graph = self.world.entity_graph
        if entities is None:
            # repackage NodeViews and EdgeViews to maintain compatibility
            nodes_list = literal_eval(str(graph.nodes(data=True)))
            nodes_dict = dict({node[0]: node[1] for node in nodes_list})

            edges_list = literal_eval(str(graph.edges))
            edges_tuple = tuple(list(edge) + [{}] for edge in edges_list)

            return {'nodes': nodes_dict, 'edges': edges_tuple}
        elif type(entities) is str:
            return {n: graph.nodes[n] for n in graph[entities]}
        else:
            return {
                eid: {n: graph.nodes[n] for n in graph[eid]}
                for eid in entities
            }

    @rpc.process
    def get_data(self, attrs):
        """
        Return the data for the requested attributes *attrs*.

        *attrs* is a dict of (fully qualified) entity IDs mapping to lists
        of attribute names (``{'sid/eid': ['attr1', 'attr2']}``).

        The return value is a dictionary, which maps the input entity IDs to
        data dictionaries, which in turn map attribute names to their
        respective values:
        (``{'sid/eid': {'attr1': val1, 'attr2': val2}}``).
        """
        sim = self.world.sims[self.sim_id]
        assert sim.is_in_step        
        cache_slice = (self.world._df_cache[sim.last_step]
                       if self.world._df_cache is not None else {})

        data = {}
        missing = collections.defaultdict(
            lambda: collections.defaultdict(list))
        dfg = self.world.df_graph
        dest_sid = self.sim_id
        # Try to get data from cache
        for full_id, attr_names in attrs.items():
            sid, eid = full_id.split(FULL_ID_SEP, 1)
            # Check if async_requests are enabled.
            self._assert_async_requests(dfg, sid, dest_sid)

            data[full_id] = {}
            for attr in attr_names:
                try:
                    data[full_id][attr] = cache_slice[sid][eid][attr]
                except KeyError:
                    missing[sid][eid].append(attr)

        # Query simulator for data not in the cache
        for sid, attrs in missing.items():
            dep = self.world.sims[sid]
            assert (dep.progress > sim.last_step >= dep.last_step)
            dep_data = yield dep.proxy.get_data(attrs)
            for eid, vals in dep_data.items():
                # Maybe there's already an entry for full_id, so we need
                # to update the dict in that case.
                data.setdefault(FULL_ID % (sid, eid), {}).update(vals)

        return data

    @rpc
    def set_data(self, data):
        """
        Set *data* as input data for all affected simulators.

        *data* is a dictionary mapping source entity IDs to destination entity
        IDs with dictionaries of attributes and values (``{'src_full_id':
        {'dest_full_id': {'attr1': 'val1', 'attr2': 'val2'}}}``).
        """
        sims = self.world.sims
        dfg = self.world.df_graph
        dest_sid = self.sim_id
        for src_full_id, dest in data.items():
            for full_id, attributes in dest.items():
                sid, eid = full_id.split(FULL_ID_SEP, 1)
                self._assert_async_requests(dfg, sid, dest_sid)
                inputs = sims[sid].input_buffer.setdefault(eid, {})
                for attr, val in attributes.items():
                    inputs.setdefault(attr, {})[src_full_id] = val

    @rpc
    def set_event(self, event_time):
        """
        Schedules an event/step at simulation time *event_time*.
        """
        sim = self.world.sims[self.sim_id]
        """
        if not sim.set_events:
            # TODO: The error is not raised at simulation level and just causes the
            # function not being executed
            print("Error: Simulator '%s' tried to set an event, but "
                  "hasn't set set_events to True." % self.sim_sid)
            #raise SimulationError("Simulator '%s' tried to set an event, but "
            #                     "hasn't set set_events to True." % self.sim_sid)
        """
        if not self.world.rt_factor:
            raise SimulationError('Simulator "%s" tried to set an event in '
                                  'non-real-time mode.' % self.sim_id)
        if event_time < self.world.until:
            sim.progress = min(event_time, sim.progress)
            earlier_step = sim.next_steps and event_time < sim.next_steps[0]
            hq.heappush(sim.next_steps, event_time)


            if sim.has_next_step and not sim.has_next_step.triggered:
                sim.has_next_step.succeed()
            # We interrupt the simulator if the new step is smaller than
            # next_step, unless it is already executing a step:
            elif sim.interruptable and earlier_step:
                sim.sim_proc.interrupt('Earlier step')
        else:
            logger.warning("Event set at {event_time} by {sim_id} is after "
                           "simulation end {until} and will be ignored.",
                           event_time=event_time, sim_id=sim.sid, until=self.world.until)

    def _assert_async_requests(self, dfg, src_sid, dest_sid):
        """
        Check if async. requests are allowed from *dest_sid* to *src_sid*
        and raise a :exc:`ScenarioError` if not.
        """
        data = {
            'src': src_sid,
            'dest': dest_sid,
        }
        if dest_sid not in dfg[src_sid]:
            raise ScenarioError(
                'No connection from "%(src)s" to "%(dest)s": You need to '
                'connect entities from both simulators and set '
                '"async_requests=True".' % data)
        if dfg[src_sid][dest_sid]['async_requests'] is not True:
            raise ScenarioError(
                'Async. requests not enabled for the connection from '
                '"%(src)s" to "%(dest)s". Add the argument '
                '"async_requests=True" to the connection of entities from '
                '"%(src)s" to "%(dest)s".' % data)


class StarterCollection(object):
    """
    This class provides a singleton instance of a collection of simulation
    starters. Default starters are:
    - python: start_inproc
    - cmd: start_proc
    - connect: start_connect

    External packages may add additional methods of starting simulations by
    adding new elements:

        from mosaik.simmanager import StarterCollection
        s = StarterCollection()
        s['my_starter'] = my_starter_func
    """

    # Singleton instance of the starter collection.
    __instance = None

    def __new__(cls) -> OrderedDict[str, Callable[..., SimProxy]]:
        if StarterCollection.__instance is None:
            # Create collection with default starters (i.e., starters defined
            # my mosaik core).
            StarterCollection.__instance = collections.OrderedDict(
                python=start_inproc,
                cmd=start_proc,
                connect=start_connect)

        return StarterCollection.__instance


class TimedInputBuffer:
    """
    A buffer to store inputs with its corresponding *time*.

    When the data is queried for a specific *step* time, all entries with
    *time* <= *step* are added to the input_dictionary.

    If there are several entries for the same connection at the same time, only
    the most recent value is added.
    """

    def __init__(self):
        self.input_queue = []
        self.counter = count()  # Used to chronologically sort entries

    def add(self, time, src_sid, src_eid, dest_eid, dest_var, value):
        src_full_id = '.'.join(map(str, (src_sid, src_eid)))
        hq.heappush(self.input_queue, (time, next(self.counter), src_full_id,
                                       dest_eid, dest_var, value))

    def get_input(self, input_dict, step):
        while len(self.input_queue) > 0 and self.input_queue[0][0] <= step:
            _, _, src_full_id, eid, attr, value = hq.heappop(self.input_queue)
            input_dict.setdefault(eid, {}).setdefault(attr, {})[
                src_full_id] = value

        return input_dict

    def __bool__(self):
        return bool(len(self.input_queue))
