"""Scenic world model for scenarios using the generic driving domain."""

from abc import ABC, abstractmethod

from scenic.domains.driving.workspace import DrivingWorkspace
import scenic.domains.driving.network as networkModule
from scenic.domains.driving.roads import ManeuverType

from scenic.simulators.utils.colors import Color

## Various useful objects and regions

network = networkModule.network
if not network:
    raise RuntimeError('need to load road network before importing driving model '
                       '(call scenic.domains.driving.network.loadNetwork)')

workspace = DrivingWorkspace(network)

road = network.drivableRegion
curb = network.curbRegion
sidewalk = network.sidewalkRegion
intersection = network.intersectionRegion

roadDirection = network.roadDirection

## Standard object types

class DrivingObject:
    """Abstract class for objects in a road network.

    Provides convenience properties for the lane, road, intersection, etc. at the
    object's current position (if any).

    Also defines the 'elevation' property as a standard way to access the Z
    component of an object's position, since the Scenic built-in property
    'position' is only 2D. If 'elevation' is set to `None`, the simulator is
    responsible for choosing an appropriate Z coordinate so that the object is
    on the ground, then updating the property. 2D simulators should set the
    property to zero.
    """

    elevation[dynamic]: None

    requireVisible: False

    # Convenience properties

    @property
    def lane(self):
        return network.laneAt(self)

    @property
    def laneSection(self):
        return network.laneSectionAt(self)

    @property
    def laneGroup(self):
        return network.laneGroupAt(self)

    @property
    def road(self):
        return network.roadAt(self)

    @property
    def intersection(self):
        return network.intersectionAt(self)

    @property
    def crossing(self):
        return network.crossingAt(self)

    @property
    def element(self):
        return network.elementAt(self)

    # Simulator interface implemented by subclasses

    def setPosition(self, pos, elevation):
        raise NotImplementedError

    def setVelocity(self, vel):
        raise NotImplementedError

class Vehicle(DrivingObject):
    regionContainedIn: road
    position: Point on road
    heading: (roadDirection at self.position) + self.roadDeviation
    roadDeviation: 0
    viewAngle: 90 deg
    width: 2
    height: 4.5
    color: Color.defaultCarColor()

class Car(Vehicle):
    pass

class NPCCar(Car):
    """Car for which accurate physics is not required."""
    pass

class Pedestrian(DrivingObject):
    regionContainedIn: network.walkableRegion
    position: Point on network.walkableRegion
    heading: (0, 360) deg
    viewAngle: 90 deg
    width: 0.75
    height: 0.75
    color: [0, 0.5, 1]

# Mixin classes indicating support for various types of actions

class Steers(ABC):
    @abstractmethod
    def setThrottle(self, throttle): pass

    @abstractmethod
    def setSteering(self, steering): pass

    @abstractmethod
    def setBraking(self, braking): pass

    @abstractmethod
    def setHandbrake(self, handbrake): pass

    @abstractmethod
    def setReverse(self, reverse): pass

class Walks(ABC):
    """Mixin class for agents which can walk with a given direction and speed.

    We provide a simplistic implementation which directly sets the velocity of the agent.
    This implementation needs to be explicitly opted-into, since simulators may provide a
    more sophisticated API that properly animates pedestrians.
    """
    @abstractmethod
    def setWalkingDirection(self, heading):
        velocity = Vector(0, self.speed).rotatedBy(heading)
        self.setVelocity(velocity)

    @abstractmethod
    def setWalkingSpeed(self, speed):
        velocity = speed * self.velocity.normalized()
        self.setVelocity(velocity)

## Utility functions

def distanceToAnyCars(car, thresholdDistance):
    """ returns boolean """
    objects = simulation().objects
    for obj in objects:
        if obj is car or not isinstance(obj, Vehicle):
            continue
        if (distance from car to obj) < thresholdDistance:
            return True
    return False