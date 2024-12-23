"""Newtonian simulator implementation."""

from cmath import atan, pi, tan
import math
from math import copysign, degrees, radians, sin
import os
import pathlib
import statistics
import time

from PIL import Image
import numpy as np

import scenic.core.errors as errors  # isort: skip

if errors.verbosityLevel == 0:  # suppress pygame advertisement at zero verbosity
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "hide"
import pygame
import shapely

from scenic.core.geometry import allChains, findMinMax
from scenic.core.regions import toPolygon
from scenic.core.simulators import SimulationCreationError
from scenic.core.vectors import Orientation, Vector
from scenic.domains.driving.controllers import (
    PIDLateralController,
    PIDLongitudinalController,
)
from scenic.domains.driving.roads import Network
from scenic.domains.driving.simulators import DrivingSimulation, DrivingSimulator
from scenic.syntax.veneer import verbosePrint

current_dir = pathlib.Path(__file__).parent.absolute()

WIDTH = 1280
HEIGHT = 800
MAX_ACCELERATION = 5.6  # in m/s2, seems to be a pretty reasonable value
MAX_BRAKING = 4.6

ROAD_COLOR = (0, 0, 0)
ROAD_WIDTH = 2
LANE_COLOR = (96, 96, 96)
CENTERLINE_COLOR = (224, 224, 224)
SIDEWALK_COLOR = (0, 128, 255)
SHOULDER_COLOR = (96, 96, 96)


class NewtonianSimulator(DrivingSimulator):
    """Implementation of `Simulator` for the Newtonian simulator.

    Args:
        network (Network): road network to display in the background, if any.
        render (bool): whether to render the simulation in a window.

    .. versionchanged:: 3.0

        The **timestep** argument is removed: it can be specified when calling
        `simulate` instead. The default timestep for the Newtonian simulator
        when not otherwise specified is still 0.1 seconds.
    """

    def __init__(self, network=None, render=False, debug_render=False, export_gif=False):
        super().__init__()
        self.export_gif = export_gif
        self.render = render
        self.debug_render = debug_render
        self.network = network

    def createSimulation(self, scene, **kwargs):
        simulation = NewtonianSimulation(
            scene, self.network, self.render, self.export_gif, self.debug_render, **kwargs
        )
        if self.export_gif and self.render:
            simulation.generate_gif("simulation.gif")
        return simulation


class NewtonianSimulation(DrivingSimulation):
    """Implementation of `Simulation` for the Newtonian simulator."""

    def __init__(
        self, scene, network, render, export_gif, debug_render, timestep, **kwargs
    ):
        self.export_gif = export_gif
        self.render = render
        self.network = network
        self.screen = None
        self.frames = []
        self.debug_render = debug_render

        if timestep is None:
            timestep = 0.1

        super().__init__(scene, timestep=timestep, **kwargs)

    def setup(self):
        super().setup()

        if self.render:
            # determine window size
            min_x, max_x = findMinMax(obj.x for obj in self.objects)
            min_y, max_y = findMinMax(obj.y for obj in self.objects)

            pygame.init()
            pygame.font.init()
            self.screen = pygame.display.set_mode(
                (WIDTH, HEIGHT), pygame.HWSURFACE | pygame.DOUBLEBUF
            )
            self.screen.fill((255, 255, 255))
            x, y, _ = self.objects[0].position
            self.min_x, self.max_x = min_x - 40, max_x + 40
            self.min_y, self.max_y = min_y - 40, max_y + 40
            self.size_x = self.max_x - self.min_x
            self.size_y = self.max_y - self.min_y

            # Generate a uniform screen scaling (applied to width and height)
            # that includes all of both dimensions.
            self.screenScaling = min(WIDTH / self.size_x, HEIGHT / self.size_y)

            # Calculate a screen translation that brings the mean vehicle
            # position to the center of the screen.

            # N.B. screenTranslation is initialized to (0, 0) here intentionally.
            # so that the actual screenTranslation can be set later based off what
            # was computed with this null value.
            self.screenTranslation = (0, 0)

            scaled_positions = map(
                lambda x: self.scenicToScreenVal(x.position), self.objects
            )
            mean_x, mean_y = map(statistics.mean, zip(*scaled_positions))

            self.screenTranslation = (WIDTH / 2 - mean_x, HEIGHT / 2 - mean_y)

            # Create screen polygon to avoid rendering entirely invisible images
            self.screen_poly = shapely.geometry.Polygon(
                (
                    (self.min_x, self.min_y),
                    (self.max_x, self.min_y),
                    (self.max_x, self.max_y),
                    (self.min_x, self.max_y),
                )
            )

            img_path = os.path.join(current_dir, "car.png")
            self.car = pygame.image.load(img_path)

            self.parse_network()
            self.draw_objects()

    def parse_network(self):
        self.network_polygons = []
        if not self.network:
            return

        def addRegion(region, color, width=1):
            poly = toPolygon(region)
            if not poly or not self.screen_poly.intersects(poly):
                return
            for chain in allChains(poly):
                coords = tuple(self.scenicToScreenVal(pt) for pt in chain.coords)
                self.network_polygons.append((coords, color, width))

        addRegion(self.network.walkableRegion, SIDEWALK_COLOR)
        addRegion(self.network.shoulderRegion, SHOULDER_COLOR)
        for road in self.network.roads:  # loop over main roads
            for lane in road.lanes:
                addRegion(lane.leftEdge, LANE_COLOR)
                addRegion(lane.rightEdge, LANE_COLOR)
            addRegion(road, ROAD_COLOR, ROAD_WIDTH)
        for lane in self.network.lanes:  # loop over all lanes, even in intersections
            addRegion(lane.centerline, CENTERLINE_COLOR)
        addRegion(self.network.intersectionRegion, ROAD_COLOR)

    def scenicToScreenVal(self, pos):
        x, y = pos[:2]

        screen_x = (x - self.min_x) * self.screenScaling
        screen_y = HEIGHT - 1 - (y - self.min_y) * self.screenScaling

        screen_x = screen_x + self.screenTranslation[0]
        screen_y = screen_y + self.screenTranslation[1]

        return int(screen_x), int(screen_y)

    def createObjectInSimulator(self, obj):
        # Set actor's initial speed
        obj.speed = math.hypot(*obj.velocity)

        if hasattr(obj, "elevation"):
            obj.elevation = 0.0

    def isOnScreen(self, x, y):
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y

    def step(self):
        for obj in self.objects:
            current_speed = obj.velocity.norm()
            if hasattr(obj, "hand_brake"):
                forward = obj.velocity.dot(Vector(0, 1).rotatedBy(obj.heading)) >= 0
                signed_speed = current_speed if forward else -current_speed
                if obj.hand_brake or obj.brake > 0:
                    braking = MAX_BRAKING * max(obj.hand_brake, obj.brake)
                    acceleration = braking * self.timestep
                    if acceleration >= current_speed:
                        signed_speed = 0
                    elif forward:
                        signed_speed -= acceleration
                    else:
                        signed_speed += acceleration
                else:
                    acceleration = obj.throttle * MAX_ACCELERATION
                    if obj.reverse:
                        acceleration *= -1
                    signed_speed += acceleration * self.timestep

                obj.velocity = Vector(0, signed_speed).rotatedBy(obj.heading)
                if obj.steer:
                    turning_radius = obj.length / sin(obj.steer * math.pi / 2)
                    obj.angularSpeed = -signed_speed / turning_radius
                else:
                    obj.angularSpeed = 0
                obj.speed = abs(signed_speed)
            else:
                obj.speed = current_speed
            obj.position += obj.velocity * self.timestep
            obj.heading += obj.angularSpeed * self.timestep

        if self.render:
            # Handle closing out pygame screen
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.destroy()
                    return
            self.draw_objects()
            pygame.event.pump()

    def draw_objects(self):
        self.screen.fill((255, 255, 255))
        for screenPoints, color, width in self.network_polygons:
            pygame.draw.lines(self.screen, color, False, screenPoints, width=width)

        for i, obj in enumerate(self.objects):
            color = (255, 0, 0) if i == 0 else (0, 0, 255)

            if self.debug_render:
                self.draw_rect(obj, color)

            if hasattr(obj, "isCar") and obj.isCar:
                self.draw_car(obj)
            else:
                self.draw_rect(obj, color)

        pygame.display.update()

        if self.export_gif:
            frame = pygame.surfarray.array3d(self.screen)
            frame = np.transpose(frame, (1, 0, 2))
            self.frames.append(frame)

        time.sleep(self.timestep)

    def draw_rect(self, obj, color):
        corners = [self.scenicToScreenVal(corner) for corner in obj._corners2D]
        pygame.draw.polygon(self.screen, color, corners)

    def draw_car(self, obj):
        car_width = int(obj.width * self.screenScaling)
        car_height = int(obj.height * self.screenScaling)
        scaled_car = pygame.transform.scale(self.car, (car_width, car_height))
        rotated_car = pygame.transform.rotate(scaled_car, math.degrees(obj.heading))
        car_rect = rotated_car.get_rect()
        car_rect.center = self.scenicToScreenVal(obj.position)
        self.screen.blit(rotated_car, car_rect)

    def generate_gif(self, filename="simulation.gif"):
        imgs = [Image.fromarray(frame) for frame in self.frames]
        imgs[0].save(filename, save_all=True, append_images=imgs[1:], duration=50, loop=0)

    def getProperties(self, obj, properties):
        yaw, _, _ = obj.parentOrientation.globalToLocalAngles(obj.heading, 0, 0)

        values = dict(
            position=obj.position,
            yaw=yaw,
            pitch=0,
            roll=0,
            velocity=obj.velocity,
            speed=obj.speed,
            angularSpeed=obj.angularSpeed,
            angularVelocity=obj.angularVelocity,
        )
        if "elevation" in properties:
            values["elevation"] = obj.elevation
        return values

    def destroy(self):
        if self.render:
            pygame.quit()

    def getLaneFollowingControllers(self, agent):
        dt = self.timestep
        if agent.isCar:
            lon_controller = PIDLongitudinalController(K_P=0.5, K_D=0.1, K_I=0.7, dt=dt)
            lat_controller = PIDLateralController(K_P=0.1, K_D=0.1, K_I=0.02, dt=dt)
        else:
            lon_controller = PIDLongitudinalController(
                K_P=0.25, K_D=0.025, K_I=0.0, dt=dt
            )
            lat_controller = PIDLateralController(K_P=0.2, K_D=0.1, K_I=0.0, dt=dt)
        return lon_controller, lat_controller

    def getTurningControllers(self, agent):
        dt = self.timestep
        if agent.isCar:
            lon_controller = PIDLongitudinalController(K_P=0.5, K_D=0.1, K_I=0.7, dt=dt)
            lat_controller = PIDLateralController(K_P=0.2, K_D=0.2, K_I=0.2, dt=dt)
        else:
            lon_controller = PIDLongitudinalController(
                K_P=0.25, K_D=0.025, K_I=0.0, dt=dt
            )
            lat_controller = PIDLateralController(K_P=0.4, K_D=0.1, K_I=0.0, dt=dt)
        return lon_controller, lat_controller

    def getLaneChangingControllers(self, agent):
        dt = self.timestep
        if agent.isCar:
            lon_controller = PIDLongitudinalController(K_P=0.5, K_D=0.1, K_I=0.7, dt=dt)
            lat_controller = PIDLateralController(K_P=0.2, K_D=0.2, K_I=0.02, dt=dt)
        else:
            lon_controller = PIDLongitudinalController(
                K_P=0.25, K_D=0.025, K_I=0.0, dt=dt
            )
            lat_controller = PIDLateralController(K_P=0.1, K_D=0.3, K_I=0.0, dt=dt)
        return lon_controller, lat_controller
