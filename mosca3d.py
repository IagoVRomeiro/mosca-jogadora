from flygym import Simulation
from flygym.compose import FlatGroundWorld
from flygym.utils.math import Rotation3D
from flygym_demo.complex_terrain import make_locomotion_fly

fly = make_locomotion_fly(name="demo", add_adhesion=True, colorize=True)
body_cam = fly.add_tracking_camera(
    name="body_cam",
    pos_offset=(-0.5, -7.5, 0.0),
    rotation=Rotation3D("euler", (1.57, 0.0, 0.0)),
    fovy=30.0,
)

world = FlatGroundWorld()
world.add_fly(fly, [0, 0, 0.5], Rotation3D("quat", [1, 0, 0, 0]))

sim = Simulation(world)
renderer = sim.set_renderer([body_cam])

sim.reset()
sim.warmup()

print("timestep:", sim.timestep, "| tempo inicial:", sim.time)

duracao_s = 0.5
n_passos = int(duracao_s / sim.timestep)
for _ in range(n_passos):
    sim.step()
    sim.render_as_needed()

renderer.save_video("mosca.mp4")
print("tempo final:", sim.time, "| vídeo salvo em mosca.mp4")