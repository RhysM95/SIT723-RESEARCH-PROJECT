# mosaik-demo.py
# import subprocess

# import mosaik
# import mosaik.util


sim_config = {
    'Odysseus': {
        'connect': '127.0.0.1:5554',
    }
}

# END = 60  # 60 seconds

# Create World
world = mosaik.World(SIM_CONFIG)

# Start simulators
odysseusModel = world.start('Odysseus', step_size=60*15)

# Instantiate models
odysseus = odysseusModel.Odysseus.create(1)
ody = odysseus[0]

# Connect entities
connect_many_to_one(world, nodes, ody, 'P', 'Vm')
connect_many_to_one(world, houses, ody, 'P_out')
connect_many_to_one(world, pvs, ody, 'P')

# Run simulation in real-time
world.run(until=END, rt_factor=1.0)