"""MathHacks 2.0 — wind navigation simulation.

Two interfaces:
  MAP VIEW: click an airport to choose the destination.
  AIRCRAFT MENU: choose one of three planes before takeoff.
  COCKPIT VIEW: steer the plane, monitor fuel, and compensate for wind.

Controls in the cockpit:
  LEFT / RIGHT or A / D : turn the plane's heading
  M                    : return to the grid map (flight pauses)
  1 / 2 / 3            : choose aircraft in the aircraft menu
  ENTER                : start the flight from the aircraft menu
  R                    : restart the current route and refuel
  ESC                  : quit

The airport-selection screen intentionally uses a simple grid with airport
markers rather than a world-map image. Keep vector.py beside this file.

MAIN IDEA: the plane has a velocity through the air, and wind has its own
velocity. Adding those vectors gives the plane's velocity over the ground:
    ground_velocity = air_velocity + wind_velocity
The ground velocity moves the plane and determines its actual trail.

This is a learning/demo model, not a realistic or safety-critical flight
simulator. Coordinates, wind, fuel use, and time compression are simplified.
"""

from __future__ import annotations

import math
import random
import sys

import pygame
from vector import Vector

# ---------------------------------------------------------------------------
# Pygame setup
# ---------------------------------------------------------------------------
pygame.init()

SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 60
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("AeroNav - MathHacks 2.0")
clock = pygame.time.Clock()

FONT = pygame.font.SysFont("consolas", 18)
SMALL_FONT = pygame.font.SysFont("consolas", 14)
TINY_FONT = pygame.font.SysFont("consolas", 11)
TITLE_FONT = pygame.font.SysFont("consolas", 22, bold=True)
BIG_FONT = pygame.font.SysFont("consolas", 28, bold=True)

# Palette
WHITE = (241, 247, 252)
MUTED = (164, 185, 201)
DARK = (10, 18, 29)
PANEL = (9, 18, 30)
GREEN = (66, 238, 127)       # selected destination / arrival status
YELLOW = (255, 207, 76)      # plane heading / nose direction
CYAN = (78, 221, 255)        # ground velocity / actual ground track
WIND_COLOUR = (148, 183, 199)
BLUE = (54, 143, 202)

# The airport-selection screen intentionally uses a simple grid instead of
# a world-map image. This keeps the interface lightweight and easy to read.

# ---------------------------------------------------------------------------
# Airports and the world-map projection
# ---------------------------------------------------------------------------
# Fictional cities and airport codes. The coordinate pairs act like a
# latitude/longitude grid for route directions and approximate gameplay distance;
# they do not represent real cities or real airports.
AIRPORTS = {
    "Northport (NPT)": (44.0, -78.0),       # home airport
    "Bellwick (BWK)": (43.6, -74.9),        # very short hop from Northport
    "Eastmere (ESM)": (42.0, -68.0),        # another nearby destination
    "Redcliff (RDC)": (37.0, -123.0),       # far west
    "Mistvale (MSV)": (54.0, -18.0),        # north Atlantic region
    "Evermere (EVM)": (51.0, -9.0),         # relatively close to Mistvale
    "Sunspire (SNS)": (22.0, 51.0),         # warm southern/eastern region
    "Jadeport (JDP)": (36.0, 140.0),        # far east
    "Southreach (STR)": (-34.0, 150.0),     # southern hemisphere
    "Frostmere (FRM)": (66.0, -27.0),       # far north
}
START_AIRPORT = "Northport (NPT)"


def geo_to_screen(latitude: float, longitude: float) -> Vector:
    """Project latitude/longitude onto a simple equirectangular map."""
    x = (longitude + 180.0) / 360.0 * SCREEN_WIDTH
    y = (90.0 - latitude) / 180.0 * SCREEN_HEIGHT
    return Vector(x, y)


AIRPORT_POSITIONS = {
    name: geo_to_screen(lat, lon)
    for name, (lat, lon) in AIRPORTS.items()
}

# Display-only nudges make the nearby airports individually clickable and
# keep labels from overlapping. Northport–Bellwick is intentionally a very
# short trip, while Mistvale–Evermere is another close pair. Route distances
# use AIRPORTS, not these display-only offsets.
AIRPORT_POSITIONS["Bellwick (BWK)"] = AIRPORT_POSITIONS["Bellwick (BWK)"] + Vector(27, 24)
AIRPORT_POSITIONS["Eastmere (ESM)"] = AIRPORT_POSITIONS["Eastmere (ESM)"] + Vector(52, -13)
AIRPORT_POSITIONS["Evermere (EVM)"] = AIRPORT_POSITIONS["Evermere (EVM)"] + Vector(34, 17)

# ---------------------------------------------------------------------------
# Flight physics
# ---------------------------------------------------------------------------
# Three aircraft choices. Fuel use depends on current gross mass (aircraft
# mass + fuel remaining), distance travelled, and airspeed. These are simplified
# gameplay models, not certified real aircraft performance data.
AIRCRAFT = {
    "small": {
        "name": "Small propeller",
        "tagline": "Light, efficient, best for short routes.",
        "speed_kmh": 420.0,
        "dry_weight_kg": 7500.0,
        "fuel_capacity_kg": 1800.0,
        "colour": (117, 213, 175),
    },
    "medium": {
        "name": "Medium passenger jet",
        "tagline": "A balanced choice for medium-length flights.",
        "speed_kmh": 780.0,
        "dry_weight_kg": 65000.0,
        "fuel_capacity_kg": 28000.0,
        "colour": (92, 190, 255),
    },
    "large": {
        "name": "Large long-haul jet",
        "tagline": "Very heavy, but carries enough fuel for long routes.",
        "speed_kmh": 900.0,
        "dry_weight_kg": 250000.0,
        "fuel_capacity_kg": 240000.0,
        "colour": (255, 207, 76),
    },
}
AIRCRAFT_ORDER = ["small", "medium", "large"]
AIR_SPEED = AIRCRAFT["medium"]["speed_kmh"]  # Set from the selected aircraft at takeoff.
WIND_X_STRENGTH = 260.0          # maximum wind component, km/h
WIND_Y_STRENGTH = 220.0          # maximum wind component, km/h
FUEL_BASE_KG_PER_1000_KM = 1000.0

# The cockpit world is a time-compressed, abstract map so a flight fits a demo.
# The medium jet moves about 42 simulation units per wall-clock second; the
# other aircraft move faster or slower in proportion to their selected airspeed.
SIM_UNITS_PER_KMH_SECOND = 42.0 / AIR_SPEED

MAX_STEERING_DEGREES = 60.0      # wider steering range around the initial route
STEERING_RATE = 58.0             # degrees per second while turning
ARRIVAL_RADIUS_KM = 30.0         # actual arrival radius, converted per route
MAX_ARRIVAL_RADIUS_SIM = 24.0
MAX_OVERSHOOT = 70.0              # miss the airport if we pass too far beyond it
MIN_ROUTE_DISTANCE = 560.0       # nearby destinations still give a useful flight
MAX_ROUTE_DISTANCE = 2800.0      # long-haul destinations get substantially more room
MIN_REFERENCE_DISTANCE_KM = 550.0
MAX_REFERENCE_DISTANCE_KM = 15500.0
MIN_CORRIDOR_HALF_WIDTH = 135.0  # wider minimum lateral deviation from planned route
MAX_CORRIDOR_HALF_WIDTH = 760.0  # long-haul routes get much more lateral room
MAP_CLICK_RADIUS = 16.0
PATH_SAMPLE_INTERVAL = 0.075


def wrap_angle(angle: float) -> float:
    """Wrap an angle to [-pi, pi], avoiding discontinuities around 360 degrees."""
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def is_vector(value) -> bool:
    """True when a value is a usable Vector-like object, not None."""
    return value is not None and hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "magnitude")


def safe_unit(vector: Vector) -> Vector:
    """Return a unit vector without dividing by zero.

    Uses multiplication by a reciprocal instead of Vector division, so this
    also works with the team's original, minimal Vector class.
    """
    if not is_vector(vector):
        return Vector(0.0, 0.0)
    length = vector.magnitude()
    if length <= 1e-9:
        return Vector(0.0, 0.0)
    return vector * (1.0 / length)


def target_bearing(position: Vector, target: Vector) -> float:
    """Return the screen-coordinate angle toward target, safely handling missing state."""
    if not is_vector(position) or not is_vector(target):
        return 0.0
    difference = target - position
    return math.atan2(difference.y, difference.x)


def signed_cross_track(position: Vector) -> float:
    """Signed side distance from the initial planned route centreline."""
    # 2-D cross product of the unit route direction and position offset.
    return route_direction.x * position.y - route_direction.y * position.x


def wind_at(position: Vector) -> Vector:
    """Return the local wind velocity in km/h; missing position falls back safely."""
    if not is_vector(position):
        position = Vector(0.0, 0.0)
    wind_x = WIND_X_STRENGTH * math.sin(position.y * 0.009 + position.x * 0.004 + 1.0)
    wind_y = WIND_Y_STRENGTH * math.cos(position.x * 0.007 - position.y * 0.006 + 2.2)
    return Vector(wind_x, wind_y)


def air_velocity_from_heading(heading: float) -> Vector:
    """The air-relative velocity in km/h; its magnitude is always AIR_SPEED."""
    return Vector(math.cos(heading), math.sin(heading)) * AIR_SPEED


def speed_vector_kmh(vector: Vector) -> Vector:
    """Return a copy of a velocity vector in km/h (already km/h internally)."""
    return Vector(vector.x, vector.y)


def great_circle_distance_km(origin_name: str, destination_name: str) -> float:
    """Approximate real airport-to-airport distance using the haversine formula."""
    lat1, lon1 = map(math.radians, AIRPORTS[origin_name])
    lat2, lon2 = map(math.radians, AIRPORTS[destination_name])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2.0) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2)
    a = max(0.0, min(1.0, a))
    return 6371.0 * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def fuel_burn_kg_per_1000_km(aircraft_id: str, fuel_remaining_kg: float) -> float:
    """Estimate fuel used per 1,000 km; heavier gross mass burns more fuel."""
    spec = AIRCRAFT[aircraft_id]
    gross_weight = spec["dry_weight_kg"] + max(0.0, fuel_remaining_kg)
    weight_factor = (gross_weight / 10000.0) ** 0.65
    speed_factor = math.sqrt(spec["speed_kmh"] / 800.0)
    return FUEL_BASE_KG_PER_1000_KM * weight_factor * speed_factor


def estimated_range_km(aircraft_id: str) -> float:
    """Approximate full-tank range at takeoff weight, before detours/wind effects."""
    capacity = AIRCRAFT[aircraft_id]["fuel_capacity_kg"]
    burn_per_1000 = fuel_burn_kg_per_1000_km(aircraft_id, capacity)
    return capacity / max(burn_per_1000, 0.001) * 1000.0


def calculate_velocities(position: Vector, target: Vector, heading: float):
    """Return bearing, air velocity, wind velocity, and ground velocity.

    If route state is temporarily incomplete, return harmless zero vectors rather
    than allowing a NoneType subtraction to crash the whole Pygame loop.
    """
    if not is_vector(position) or not is_vector(target):
        zero = Vector(0.0, 0.0)
        return 0.0, zero, zero, zero
    bearing = target_bearing(position, target)
    air_velocity = air_velocity_from_heading(heading)
    wind_velocity = wind_at(position)
    ground_velocity = air_velocity + wind_velocity
    return bearing, air_velocity, wind_velocity, ground_velocity


def compass_heading(screen_angle: float) -> float:
    """Convert screen-coordinate angle (0=east, positive=down) to compass degrees."""
    return (90.0 - math.degrees(screen_angle)) % 360.0


def route_vector_for_airport(destination_name: str) -> Vector:
    """Get the shortest map-direction vector from Northport to a destination.

    Wrap horizontal map distance across the dateline for routes like Northport–Jadeport.
    This vector determines the flight direction; flight distance is scaled separately.
    """
    start = AIRPORT_POSITIONS[START_AIRPORT]
    destination = AIRPORT_POSITIONS[destination_name]
    dx = destination.x - start.x
    if dx > SCREEN_WIDTH / 2:
        dx -= SCREEN_WIDTH
    elif dx < -SCREEN_WIDTH / 2:
        dx += SCREEN_WIDTH
    return Vector(dx, destination.y - start.y)


# ---------------------------------------------------------------------------
# Current simulation state
# ---------------------------------------------------------------------------
# These variables persist between frames. Pygame redraws the screen many
# times per second, so we store the current flight here instead of starting
# it over every frame. The mode controls which screen is currently visible.
mode = "MAP"  # MAP -> PLANE_SELECT -> FLIGHT

destination_name = None
active_destination_name = None
selected_aircraft_id = "medium"
plane_pos = Vector(0.0, 0.0)
target_pos = None
heading_angle = 0.0
route_heading = 0.0
route_direction = Vector(1.0, 0.0)
flight_distance = 0.0                 # abstract simulation units
route_distance_km = 0.0               # approximate real distance between airports
km_per_sim_unit = 1.0                 # converts route-monitor distance into km
simulation_time_acceleration = 1.0    # game time runs faster to keep flights demo-sized
arrival_radius_sim = MAX_ARRIVAL_RADIUS_SIM
corridor_half_width = MIN_CORRIDOR_HALF_WIDTH
steering_offset_degrees = 0.0
arrived = False
out_of_course = False
missed_destination = False
out_of_fuel = False
fuel_remaining_kg = AIRCRAFT[selected_aircraft_id]["fuel_capacity_kg"]
fuel_used_kg = 0.0
elapsed_flight_time = 0.0
path_history = [Vector(0.0, 0.0)]
path_sample_timer = 0.0

# Clickable aircraft cards and the takeoff button on the aircraft-selection screen.
AIRCRAFT_CARD_RECTS = [
    pygame.Rect(45, 160, 375, 390),
    pygame.Rect(452, 160, 375, 390),
    pygame.Rect(859, 160, 375, 390),
]
START_FLIGHT_RECT = pygame.Rect(470, 574, 340, 62)


def start_flight(new_destination: str, aircraft_id: str) -> None:
    """Initialise a route and load the selected aircraft's fuel tank."""
    global mode, destination_name, active_destination_name, selected_aircraft_id, AIR_SPEED
    global plane_pos, target_pos, heading_angle, route_heading
    global route_direction, flight_distance, route_distance_km, km_per_sim_unit
    global simulation_time_acceleration, arrival_radius_sim, corridor_half_width
    global arrived, out_of_course, missed_destination, out_of_fuel
    global fuel_remaining_kg, fuel_used_kg, elapsed_flight_time, path_history, path_sample_timer

    # Validate state before doing any dictionary lookups or vector arithmetic.
    # This prevents incomplete menu state from turning into a NoneType crash.
    if (not isinstance(new_destination, str)
            or new_destination not in AIRPORTS
            or new_destination == START_AIRPORT):
        mode = "MAP"
        return

    destination_name = new_destination
    active_destination_name = new_destination
    if aircraft_id in AIRCRAFT:
        selected_aircraft_id = aircraft_id
    if selected_aircraft_id not in AIRCRAFT:
        selected_aircraft_id = "medium"
    AIR_SPEED = AIRCRAFT[selected_aircraft_id]["speed_kmh"]
    base_route_vector = route_vector_for_airport(new_destination)
    base_direction = safe_unit(base_route_vector)
    if base_direction.magnitude() <= 1e-9:
        # A malformed/overlapping route should not crash on unit normalization.
        base_direction = Vector(1.0, 0.0)

    # Each flight gets a tiny route-angle variation (at most 2 degrees), so
    # retries aren't pixel-for-pixel identical without making the route unfair.
    route_variation = math.radians(random.uniform(-2.0, 2.0))
    c, s = math.cos(route_variation), math.sin(route_variation)
    direction = Vector(
        base_direction.x * c - base_direction.y * s,
        base_direction.x * s + base_direction.y * c,
    )
    direction = safe_unit(direction)
    if direction.magnitude() <= 1e-9:
        direction = Vector(1.0, 0.0)

    route_distance_km = great_circle_distance_km(START_AIRPORT, new_destination)
    # Nearby airports stay close to the old flight length. Long-haul routes
    # scale nonlinearly, giving them much more distance without taking forever.
    fraction = (route_distance_km - MIN_REFERENCE_DISTANCE_KM) / (
        MAX_REFERENCE_DISTANCE_KM - MIN_REFERENCE_DISTANCE_KM
    )
    fraction = max(0.0, min(1.0, fraction))
    flight_distance = MIN_ROUTE_DISTANCE + (
        MAX_ROUTE_DISTANCE - MIN_ROUTE_DISTANCE
    ) * (fraction ** 0.78)
    km_per_sim_unit = route_distance_km / max(flight_distance, 1.0)
    # Explicit time compression keeps the displayed physical km/h and route km
    # consistent while shrinking an hours-long flight to a demo-friendly time.
    simulation_time_acceleration = (
        SIM_UNITS_PER_KMH_SECOND * 3600.0 * km_per_sim_unit
    )
    arrival_radius_sim = max(
        4.0,
        min(MAX_ARRIVAL_RADIUS_SIM, ARRIVAL_RADIUS_KM / max(km_per_sim_unit, 0.001)),
    )

    plane_pos = Vector(0.0, 0.0)
    target_pos = direction * flight_distance
    route_direction = direction
    route_heading = math.atan2(direction.y, direction.x)
    heading_angle = route_heading
    corridor_half_width = max(
        MIN_CORRIDOR_HALF_WIDTH,
        min(MAX_CORRIDOR_HALF_WIDTH, flight_distance * 0.27),
    )
    arrived = False
    out_of_course = False
    missed_destination = False
    out_of_fuel = False
    fuel_remaining_kg = AIRCRAFT[selected_aircraft_id]["fuel_capacity_kg"]
    fuel_used_kg = 0.0
    elapsed_flight_time = 0.0
    path_history = [Vector(plane_pos.x, plane_pos.y)]
    path_sample_timer = 0.0
    mode = "FLIGHT"


def restart_flight() -> None:
    """Restart the selected route from the beginning and refill the selected aircraft."""
    if destination_name is not None:
        start_flight(destination_name, selected_aircraft_id)


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
def draw_text(surface, text, x, y, font=FONT, colour=WHITE):
    """Render text at a screen position; this helper keeps font drawing consistent."""
    surface.blit(font.render(str(text), True, colour), (int(x), int(y)))


def format_flight_time(seconds: float) -> str:
    """Format accelerated simulation time as hours and minutes."""
    total_minutes = max(0, int(seconds // 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours:02d}h {minutes:02d}m"
    return f"{minutes:02d}m {int(seconds % 60):02d}s"


def draw_panel(surface, rect, colour=(9, 18, 30, 220), border=(92, 126, 148, 160), radius=12):
    """Draw a rounded translucent UI panel, optionally with an outline."""
    panel_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(panel_surface, colour, panel_surface.get_rect(), border_radius=radius)
    if border is not None:
        pygame.draw.rect(panel_surface, border, panel_surface.get_rect(), width=1, border_radius=radius)
    surface.blit(panel_surface, rect.topleft)


def draw_dashed_line(surface, colour, start: Vector, end: Vector,
                     dash_length=9.0, gap_length=6.0, width=2):
    """Draw a dashed line between two points."""
    difference = end - start
    total_length = difference.magnitude()
    if total_length <= 0.001:
        return
    direction = difference * (1.0 / total_length)
    distance = 0.0
    while distance < total_length:
        dash_end = min(distance + dash_length, total_length)
        p1 = start + direction * distance
        p2 = start + direction * dash_end
        pygame.draw.line(surface, colour,
                         (round(p1.x), round(p1.y)),
                         (round(p2.x), round(p2.y)), width)
        distance += dash_length + gap_length


def draw_arrow(surface, colour, start: Vector, direction: Vector,
               length: float, width=2, head_length=6.0, head_width=4.0):
    """Draw an arrow from a start point in a direction, scaled to the requested pixel length."""
    if direction.magnitude() <= 0.001:
        return
    unit = direction.unit_vector()
    end = start + unit * length
    pygame.draw.line(surface, colour,
                     (round(start.x), round(start.y)),
                     (round(end.x), round(end.y)), width)
    side = Vector(-unit.y, unit.x)
    back = end - unit * head_length
    left = back + side * head_width
    right = back - side * head_width
    pygame.draw.line(surface, colour, (round(end.x), round(end.y)),
                     (round(left.x), round(left.y)), width)
    pygame.draw.line(surface, colour, (round(end.x), round(end.y)),
                     (round(right.x), round(right.y)), width)


def draw_plane(surface, position: Vector, heading: float, size=10):
    """Draw a small top-down plane marker pointing in its heading direction."""
    forward = Vector(math.cos(heading), math.sin(heading))
    side = Vector(-forward.y, forward.x)
    tip = position + forward * size * 1.5
    rear = position - forward * size
    left = rear + side * size * 0.65
    right = rear - side * size * 0.65
    points = [(round(tip.x), round(tip.y)),
              (round(left.x), round(left.y)),
              (round(right.x), round(right.y))]
    pygame.draw.polygon(surface, DARK, points)
    pygame.draw.polygon(surface, YELLOW, points)
    pygame.draw.polygon(surface, WHITE, points, 1)


def draw_airport(surface, name: str, position: Vector, selected=False, is_start=False):
    """Draw an airport marker and its readable city label on the grid map."""
    x, y = round(position.x), round(position.y)
    colour = YELLOW if is_start else (CYAN if selected else WHITE)
    pygame.draw.circle(surface, (8, 20, 31), (x, y), 10)
    pygame.draw.circle(surface, colour, (x, y), 6)
    pygame.draw.circle(surface, (8, 20, 31), (x, y), 2)
    label = name.split(" (")[0]
    # Keep the airport text compact; it is a map label, not the main UI.
    label_x = x + 10
    label_y = y - 17
    if name.startswith("Jadeport") or name.startswith("Southreach"):
        label_x = x - 105
    draw_text(surface, label, label_x, label_y, SMALL_FONT, colour)


def fallback_map_background(surface):
    """A deliberately simple grid-only airport map (no world/land polygons)."""
    surface.fill((20, 28, 37))
    grid_minor = (39, 51, 62)
    grid_major = (52, 67, 78)
    for x in range(0, SCREEN_WIDTH, 40):
        colour = grid_major if x % 200 == 0 else grid_minor
        pygame.draw.line(surface, colour, (x, 0), (x, SCREEN_HEIGHT), 1)
    for y in range(0, SCREEN_HEIGHT, 40):
        colour = grid_major if y % 200 == 0 else grid_minor
        pygame.draw.line(surface, colour, (0, y), (SCREEN_WIDTH, y), 1)
    draw_text(surface, "GRID MAP / SCHEMATIC AIRPORT POSITIONS", 20, SCREEN_HEIGHT - 22,
              TINY_FONT, (105, 127, 142))


def draw_map_view():
    """Airport-selection screen using a simple grid rather than a world map."""
    fallback_map_background(screen)

    # Show a subtle planned-route preview if a destination has been chosen.
    if destination_name in AIRPORT_POSITIONS:
        origin = AIRPORT_POSITIONS[START_AIRPORT]
        destination = AIRPORT_POSITIONS[destination_name]
        delta = destination - origin
        if abs(delta.x) < SCREEN_WIDTH / 2:
            draw_dashed_line(screen, (105, 130, 145), origin, destination,
                             dash_length=8, gap_length=6, width=2)
        else:
            edge_x = 0 if delta.x < 0 else SCREEN_WIDTH
            opposite_edge = SCREEN_WIDTH if edge_x == 0 else 0
            crossing_y = origin.y + delta.y * (edge_x - origin.x) / delta.x
            draw_dashed_line(screen, (105, 130, 145), origin,
                             Vector(edge_x, crossing_y), 8, 6, 2)
            draw_dashed_line(screen, (105, 130, 145),
                             Vector(opposite_edge, destination.y), destination, 8, 6, 2)

    for airport_name, airport_position in AIRPORT_POSITIONS.items():
        draw_airport(screen, airport_name, airport_position,
                     selected=(airport_name == destination_name),
                     is_start=(airport_name == START_AIRPORT))

    draw_panel(screen, pygame.Rect(18, 18, 470, 168), (12, 19, 27, 235))
    draw_text(screen, "AeroNav - MATHHACKS 2.0", 34, 29, TITLE_FONT, WHITE)
    draw_text(screen, "AIRPORT SELECTOR  /  GRID MAP", 34, 62, SMALL_FONT, CYAN)
    draw_text(screen, "FROM: Northport (NPT)", 34, 88, SMALL_FONT, WHITE)
    if destination_name is None:
        draw_text(screen, "Click an airport marker to choose your destination.",
                  34, 118, SMALL_FONT, GREEN)
        draw_text(screen, "Next: choose an aircraft, then begin the flight.",
                  34, 143, TINY_FONT, MUTED)
    else:
        draw_text(screen, "TO: " + destination_name, 34, 115, SMALL_FONT, CYAN)
        draw_text(screen, "Click another airport to change destination.",
                  34, 141, TINY_FONT, MUTED)

    draw_panel(screen, pygame.Rect(18, SCREEN_HEIGHT - 53, SCREEN_WIDTH - 36, 35),
               (12, 19, 27, 232), border=None, radius=8)
    draw_text(screen, "YELLOW: DEPARTURE     CYAN: SELECTED DESTINATION     CLICK AIRPORT TO CONTINUE     |     ESC: QUIT",
              31, SCREEN_HEIGHT - 44, SMALL_FONT, WHITE)


def draw_fuel_bar(surface, rect: pygame.Rect, fraction: float,
                  fill_colour=(85, 222, 151), background=(38, 51, 62)):
    """Draw a compact fuel gauge clipped to its track."""
    pygame.draw.rect(surface, background, rect, border_radius=5)
    fraction = max(0.0, min(1.0, fraction))
    if fraction > 0.25:
        colour = fill_colour
    elif fraction > 0.10:
        colour = (255, 190, 74)
    else:
        colour = (255, 91, 91)
    if fraction > 0:
        fill_rect = pygame.Rect(rect.x, rect.y, max(1, int(rect.width * fraction)), rect.height)
        pygame.draw.rect(surface, colour, fill_rect, border_radius=5)
    pygame.draw.rect(surface, (105, 132, 147), rect, 1, border_radius=5)


def draw_aircraft_select_view():
    """Show the three aircraft choices after destination selection and before takeoff."""
    if destination_name is None:
        return

    fallback_map_background(screen)

    # Small route preview at the top ties the aircraft decision to the selected trip.
    draw_panel(screen, pygame.Rect(18, 16, SCREEN_WIDTH - 36, 119), (12, 19, 27, 238))
    draw_text(screen, "CHOOSE YOUR AIRCRAFT", 36, 27, TITLE_FONT, WHITE)
    draw_text(screen, f"FROM: {START_AIRPORT}     ->     TO: {destination_name}",
              36, 61, FONT, CYAN)
    route_km = great_circle_distance_km(START_AIRPORT, destination_name)
    draw_text(screen, f"APPROXIMATE ROUTE DISTANCE: {route_km:,.0f} km",
              36, 94, SMALL_FONT, MUTED)
    draw_text(screen, "Select a card, then press START FLIGHT. Keys 1 / 2 / 3 also select.",
              520, 96, TINY_FONT, WHITE)

    for index, aircraft_id in enumerate(AIRCRAFT_ORDER):
        spec = AIRCRAFT[aircraft_id]
        rect = AIRCRAFT_CARD_RECTS[index]
        selected = aircraft_id == selected_aircraft_id
        border_colour = spec["colour"] if selected else (79, 101, 115)
        fill_colour = (20, 37, 49) if not selected else (23, 48, 60)
        draw_panel(screen, rect, (*fill_colour, 245), (*border_colour, 245), radius=14)
        if selected:
            draw_text(screen, "SELECTED", rect.right - 100, rect.y + 14,
                      TINY_FONT, spec["colour"])
        draw_text(screen, f"{index + 1}. {spec['name'].upper()}",
                  rect.x + 20, rect.y + 21, SMALL_FONT, spec["colour"])

        # A simple silhouette changes size with the selected aircraft class.
        plane_size = [17, 23, 29][index]
        draw_plane(screen, Vector(rect.centerx, rect.y + 92), 0.0, plane_size)
        draw_text(screen, spec["tagline"], rect.x + 20, rect.y + 141,
                  TINY_FONT, MUTED)

        takeoff_weight = spec["dry_weight_kg"] + spec["fuel_capacity_kg"]
        fuel_burn = fuel_burn_kg_per_1000_km(aircraft_id, spec["fuel_capacity_kg"])
        range_km = estimated_range_km(aircraft_id)
        stats = [
            ("AIR SPEED", f"{spec['speed_kmh']:,.0f} km/h"),
            ("TAKEOFF WEIGHT", f"{takeoff_weight:,.0f} kg"),
            ("FUEL TANK", f"{spec['fuel_capacity_kg']:,.0f} kg"),
            ("EST. RANGE", f"{range_km:,.0f} km"),
            ("FUEL USE", f"{fuel_burn:,.0f} kg / 1,000 km"),
        ]
        y = rect.y + 175
        for label, value in stats:
            draw_text(screen, label, rect.x + 20, y, TINY_FONT, (137, 160, 175))
            draw_text(screen, value, rect.x + 20, y + 15, SMALL_FONT, WHITE)
            y += 33

        button_rect = pygame.Rect(rect.x + 18, rect.bottom - 48, rect.width - 36, 30)
        button_colour = spec["colour"] if selected else (67, 87, 99)
        pygame.draw.rect(screen, button_colour, button_rect, 1, border_radius=7)
        draw_text(screen, "CURRENT SELECTION" if selected else "CLICK TO SELECT",
                  button_rect.x + 13, button_rect.y + 7, TINY_FONT,
                  spec["colour"] if selected else MUTED)

    pygame.draw.rect(screen, (30, 80, 65), START_FLIGHT_RECT, border_radius=10)
    pygame.draw.rect(screen, (105, 240, 176), START_FLIGHT_RECT, 2, border_radius=10)
    button_text = "START FLIGHT  ->"
    text_surface = FONT.render(button_text, True, WHITE)
    screen.blit(text_surface, (START_FLIGHT_RECT.centerx - text_surface.get_width() // 2,
                               START_FLIGHT_RECT.centery - text_surface.get_height() // 2))
    draw_text(screen, "Fuel consumption increases with aircraft weight and distance travelled.",
              300, 650, SMALL_FONT, MUTED)
    draw_text(screen, "M: BACK TO AIRPORT GRID     |     ESC: QUIT",
              444, 680, SMALL_FONT, WHITE)


def draw_cockpit_background(heading: float, bearing: float):
    """A lightweight first-person cockpit view made from Pygame shapes."""
    # Sky gradient.
    sky_top = (18, 75, 124)
    sky_bottom = (106, 190, 225)
    sky_height = 430
    for y in range(0, sky_height, 4):
        t = y / float(sky_height)
        colour = tuple(int(sky_top[i] * (1.0 - t) + sky_bottom[i] * t) for i in range(3))
        pygame.draw.rect(screen, colour, (0, y, SCREEN_WIDTH, 4))

    # The horizon responds subtly to heading offset, providing a sense of banking.
    offset = math.degrees(wrap_angle(heading - bearing))
    horizon_y = 350 + int(offset * 0.58)
    horizon_tilt = max(-38, min(38, int(offset * 0.68)))
    left_horizon = horizon_y + horizon_tilt
    right_horizon = horizon_y - horizon_tilt

    # Distant hills / terrain.
    pygame.draw.polygon(screen, (65, 111, 111), [
        (0, left_horizon), (110, left_horizon - 25), (215, left_horizon + 4),
        (365, left_horizon - 39), (510, left_horizon + 8),
        (680, right_horizon - 20), (825, right_horizon + 8),
        (1000, right_horizon - 31), (1130, right_horizon + 2),
        (1280, right_horizon - 14), (1280, SCREEN_HEIGHT), (0, SCREEN_HEIGHT)
    ])
    pygame.draw.polygon(screen, (45, 83, 76), [
        (0, left_horizon + 42), (150, left_horizon + 18), (310, left_horizon + 55),
        (475, left_horizon + 27), (640, horizon_y + 58), (840, right_horizon + 26),
        (1020, right_horizon + 47), (1155, right_horizon + 20),
        (1280, right_horizon + 55), (1280, SCREEN_HEIGHT), (0, SCREEN_HEIGHT)
    ])
    pygame.draw.line(screen, (193, 229, 239), (0, left_horizon),
                     (SCREEN_WIDTH, right_horizon), 2)

    # Fixed clouds are subtle depth cues, not physics objects.
    cloud_positions = [(120, 150, 1.0), (320, 220, 0.75), (620, 130, 1.1),
                       (840, 220, 0.8), (1090, 145, 0.9)]
    for cx, cy, scale in cloud_positions:
        pygame.draw.ellipse(screen, (219, 239, 244),
                            (int(cx - 40*scale), int(cy - 9*scale), int(80*scale), int(23*scale)))
        pygame.draw.ellipse(screen, (231, 246, 249),
                            (int(cx - 23*scale), int(cy - 18*scale), int(48*scale), int(29*scale)))

    # Simple forward sight reticle, fixed to the screen like a HUD.
    cx, cy = SCREEN_WIDTH // 2, 300
    pygame.draw.circle(screen, (226, 246, 250), (cx, cy), 13, 1)
    pygame.draw.line(screen, (226, 246, 250), (cx - 25, cy), (cx - 8, cy), 1)
    pygame.draw.line(screen, (226, 246, 250), (cx + 8, cy), (cx + 25, cy), 1)
    pygame.draw.line(screen, (226, 246, 250), (cx, cy - 25), (cx, cy - 8), 1)
    pygame.draw.line(screen, (226, 246, 250), (cx, cy + 8), (cx, cy + 25), 1)


def draw_route_monitor(rect: pygame.Rect, position: Vector, target: Vector,
                       heading: float, air_velocity: Vector,
                       wind_velocity: Vector, ground_velocity: Vector):
    """Draw the route trail plus a visible, local air + wind = ground diagram."""
    draw_panel(screen, rect, (7, 16, 28, 238), (104, 151, 173, 215), radius=13)
    if (not is_vector(position) or not is_vector(target)
            or not is_vector(air_velocity) or not is_vector(wind_velocity)
            or not is_vector(ground_velocity)):
        draw_text(screen, "ROUTE DATA NOT READY", rect.x + 14, rect.y + 45,
                  SMALL_FONT, MUTED)
        return
    draw_text(screen, "ROUTE MONITOR", rect.x + 13, rect.y + 9, SMALL_FONT, WHITE)
    draw_text(screen, "LIVE GROUND TRACK", rect.right - 142, rect.y + 10, TINY_FONT, CYAN)

    # Reserve the lower part of this enlarged panel for a head-to-tail vector
    # diagram, so the local wind vector is obvious rather than buried in the
    # faint background wind-field arrows.
    area = pygame.Rect(rect.x + 12, rect.y + 34, rect.width - 24, rect.height - 165)
    old_clip = screen.get_clip()
    screen.set_clip(area)
    pygame.draw.rect(screen, (14, 33, 47), area, border_radius=7)

    dx = max(abs(target.x), 1.0)
    dy = max(abs(target.y), 1.0)
    scale = min((area.width - 34) / dx, (area.height - 30) / dy)
    origin_screen = Vector(area.centerx - target.x * scale * 0.5,
                           area.centery - target.y * scale * 0.5)

    def to_monitor(point: Vector) -> Vector:
        """Convert a simulation-space point into pixels inside the route monitor."""
        return Vector(origin_screen.x + point.x * scale,
                      origin_screen.y + point.y * scale)

    # Plot grid and local wind-field arrows.
    for gx in range(area.left + 22, area.right, 52):
        pygame.draw.line(screen, (28, 53, 68), (gx, area.top), (gx, area.bottom), 1)
    for gy in range(area.top + 18, area.bottom, 36):
        pygame.draw.line(screen, (28, 53, 68), (area.left, gy), (area.right, gy), 1)
    for gy in range(area.top + 27, area.bottom - 8, 43):
        for gx in range(area.left + 25, area.right - 8, 59):
            world_point = Vector((gx - origin_screen.x) / max(scale, 0.001),
                                 (gy - origin_screen.y) / max(scale, 0.001))
            local_wind = wind_at(world_point)
            draw_arrow(screen, (88, 128, 145), Vector(gx, gy), local_wind, 7, width=1)

    # Planned route in grey, with corridor boundaries. Cyan shows the path
    # actually flown; the ground-vector direction is calculated independently.
    start_screen = to_monitor(Vector(0.0, 0.0))
    dest_screen = to_monitor(target)
    route_normal = Vector(-route_direction.y, route_direction.x)
    for side_sign in (-1.0, 1.0):
        boundary_start = to_monitor(route_normal * (corridor_half_width * side_sign))
        boundary_end = to_monitor(target + route_normal * (corridor_half_width * side_sign))
        draw_dashed_line(screen, (57, 82, 96), boundary_start, boundary_end,
                         dash_length=4, gap_length=5, width=1)
    pygame.draw.line(screen, (102, 132, 145),
                     (round(start_screen.x), round(start_screen.y)),
                     (round(dest_screen.x), round(dest_screen.y)), 1)

    if len(path_history) > 1:
        visible_path = [to_monitor(point) for point in path_history]
        pygame.draw.lines(screen, CYAN, False,
                          [(round(point.x), round(point.y)) for point in visible_path], 2)

    plane_screen = to_monitor(position)
    destination_screen = to_monitor(target)
    vector_world_length = max(75.0, min(145.0, flight_distance * 0.17))
    heading_direction = Vector(math.cos(heading), math.sin(heading))
    heading_length = vector_world_length * scale
    draw_arrow(screen, YELLOW, plane_screen, heading_direction,
               heading_length, width=2)

    ground_unit = safe_unit(ground_velocity)
    ground_length = heading_length * (ground_velocity.magnitude() / max(AIR_SPEED, 0.001))
    ground_end = plane_screen + ground_unit * ground_length
    draw_dashed_line(screen, CYAN, plane_screen, ground_end, 5, 3, 2)
    draw_arrow(screen, CYAN, ground_end - ground_unit * 8,
               ground_velocity, 8, width=2)

    pygame.draw.circle(screen, YELLOW,
                       (round(start_screen.x), round(start_screen.y)), 4)
    pygame.draw.circle(screen, GREEN,
                       (round(destination_screen.x), round(destination_screen.y)), 5, 2)
    draw_plane(screen, plane_screen, heading, size=6)
    screen.set_clip(old_clip)

    # Explicit numerical components make the route monitor useful for the math
    # explanation as well as navigation. All values shown here are km/h.
    vector_panel = pygame.Rect(rect.x + 12, area.bottom + 6, rect.width - 24, 100)
    draw_panel(screen, vector_panel, (12, 29, 42, 245), (55, 88, 108, 190), radius=8)
    draw_text(screen, "LOCAL VECTOR ADDITION  /  KM/H",
              vector_panel.x + 9, vector_panel.y + 5, TINY_FONT, WHITE)
    component_text = (
        f"A({air_velocity.x:+.0f},{air_velocity.y:+.0f}) + "
        f"W({wind_velocity.x:+.0f},{wind_velocity.y:+.0f}) = "
        f"G({ground_velocity.x:+.0f},{ground_velocity.y:+.0f})"
    )
    draw_text(screen, component_text, vector_panel.x + 9, vector_panel.y + 20,
              TINY_FONT, MUTED)
    diagram_rect = pygame.Rect(vector_panel.x + 8, vector_panel.y + 34,
                               vector_panel.width - 16, 60)
    draw_vector_addition_diagram(screen, diagram_rect,
                                 air_velocity, wind_velocity, ground_velocity)

    footer = "GREY route  |  FAINT limits  |  GOLD nose  |  CYAN track"
    draw_text(screen, footer, rect.x + 10, rect.bottom - 20, TINY_FONT, WHITE)


def draw_vector_addition_diagram(surface, rect: pygame.Rect,
                                 air_velocity: Vector, wind_velocity: Vector,
                                 ground_velocity: Vector) -> None:
    """Draw a centred, scaled vector triangle: air + wind = ground."""
    # Endpoints in vector-space coordinates. These are the three points that
    # define the head-to-tail construction: 0, air, and air + wind.
    points = [Vector(0.0, 0.0), air_velocity, ground_velocity]
    min_x = min(point.x for point in points)
    max_x = max(point.x for point in points)
    min_y = min(point.y for point in points)
    max_y = max(point.y for point in points)
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    padding_x, padding_y = 16.0, 4.0
    scale = min(
        max((rect.width - 2.0 * padding_x) / span_x, 0.01),
        max((rect.height - 2.0 * padding_y) / span_y, 0.01),
    )
    mid_x = (min_x + max_x) / 2.0
    mid_y = (min_y + max_y) / 2.0

    def project(vector: Vector) -> Vector:
        """Scale a velocity vector into the small diagram and keep it centred."""
        return Vector(
            rect.centerx + (vector.x - mid_x) * scale,
            rect.centery + (vector.y - mid_y) * scale,
        )

    origin = project(Vector(0.0, 0.0))
    air_tip = project(air_velocity)
    ground_tip = project(ground_velocity)

    # Resultant first, then its two components on top, so all three colours
    # remain distinguishable. The wind arrow starts at the air arrow's tip.
    draw_arrow(surface, CYAN, origin, ground_velocity,
               (ground_tip - origin).magnitude(), 3, head_length=9.0, head_width=6.0)
    draw_arrow(surface, YELLOW, origin, air_velocity,
               (air_tip - origin).magnitude(), 3, head_length=9.0, head_width=6.0)
    draw_arrow(surface, WIND_COLOUR, air_tip, wind_velocity,
               (ground_tip - air_tip).magnitude(), 3, head_length=9.0, head_width=6.0)


def draw_dashboard(air_velocity: Vector, wind_velocity: Vector,
                   ground_velocity: Vector, distance_to_target: float) -> None:
    """Draw the bottom instrument panel with only the four useful readouts.

    The heading-angle readouts have deliberately been removed from this panel.
    The route monitor still draws the directions visually, while this dashboard
    focuses on easy-to-understand quantities: airspeed, wind speed, ground speed,
    and distance left.
    """
    # This dark polygon forms the dashboard background and the sloped top edge.
    top = 548
    pygame.draw.polygon(screen, (12, 23, 35), [
        (0, top + 20), (355, top - 8), (925, top - 8),
        (SCREEN_WIDTH, top + 20), (SCREEN_WIDTH, SCREEN_HEIGHT), (0, SCREEN_HEIGHT)
    ])
    pygame.draw.line(screen, (72, 102, 122), (0, top + 20),
                     (SCREEN_WIDTH, top + 20), 2)

    # Show a title and remind the player that the vector values use km/h.
    draw_text(screen, "MATHHACKS AIR NAVIGATION", 28, 558, TITLE_FONT, WHITE)
    draw_text(screen, "AIR + WIND = GROUND  /  SPEEDS IN KM/H",
              364, 563, TINY_FONT, MUTED)

    # Magnitude means vector length. For a velocity vector, its magnitude is speed.
    # These four measurements explain how fast the plane moves and how far remains.
    cards = [
        ("AIR SPEED", f"{air_velocity.magnitude():,.0f} km/h", YELLOW),
        ("WIND SPEED", f"{wind_velocity.magnitude():,.0f} km/h", WIND_COLOUR),
        ("GROUND SPEED", f"{ground_velocity.magnitude():,.0f} km/h", CYAN),
        ("DISTANCE LEFT", f"{distance_to_target:,.0f} km", WHITE),
    ]

    # Four evenly spaced cards use the dashboard width more cleanly than six.
    card_width = 260
    card_gap = 22
    start_x = (SCREEN_WIDTH - (len(cards) * card_width + (len(cards) - 1) * card_gap)) // 2
    for index, (label, value, colour) in enumerate(cards):
        x = start_x + index * (card_width + card_gap)
        card_rect = pygame.Rect(x, 589, card_width, 69)
        draw_panel(screen, card_rect, (18, 33, 47, 238),
                   (72, 103, 122, 170), radius=8)
        draw_text(screen, label, x + 12, 599, TINY_FONT, MUTED)
        draw_text(screen, value, x + 12, 622, FONT, colour)

    # Keep the controls in the bottom row, but remove all heading-angle numbers.
    draw_text(screen, "A / D or LEFT / RIGHT: steer     M: map     R: restart     ESC: quit",
              29, 680, SMALL_FONT, WHITE)

def draw_cockpit_view():
    """First-person flight screen; the top-right mini-map shows the route and vectors."""
    if (not is_vector(target_pos) or destination_name not in AIRPORTS
            or selected_aircraft_id not in AIRCRAFT):
        return
    if target_pos is None:
        return
    bearing, air_velocity, wind_velocity, ground_velocity = calculate_velocities(
        plane_pos, target_pos, heading_angle
    )
    distance_to_target = (target_pos - plane_pos).magnitude() * km_per_sim_unit
    draw_cockpit_background(heading_angle, bearing)

    # Top-left flight card explicitly shows departure, arrival, aircraft and fuel.
    top_left = pygame.Rect(18, 18, 470, 176)
    draw_panel(screen, top_left, (7, 16, 28, 226), radius=11)
    aircraft = AIRCRAFT.get(selected_aircraft_id, AIRCRAFT["medium"])
    draw_text(screen, "FLIGHT STATUS  /  COCKPIT", 32, 28, TITLE_FONT, WHITE)
    draw_text(screen, f"FROM: {START_AIRPORT}", 33, 58, SMALL_FONT, WHITE)
    draw_text(screen, f"TO:   {destination_name}", 33, 80, SMALL_FONT, CYAN)
    draw_text(screen, f"AIRCRAFT: {aircraft['name']}", 33, 102, SMALL_FONT, aircraft["colour"])
    draw_text(screen,
              f"TIME {format_flight_time(elapsed_flight_time)}   HEADING {math.degrees(wrap_angle(heading_angle-route_heading)):+.0f} deg",
              33, 124, TINY_FONT, MUTED)
    fuel_fraction = fuel_remaining_kg / max(aircraft["fuel_capacity_kg"], 1.0)
    draw_text(screen,
              f"FUEL {fuel_fraction * 100:4.0f}%  {fuel_remaining_kg:,.0f} / {aircraft['fuel_capacity_kg']:,.0f} kg",
              33, 143, TINY_FONT, WHITE)
    draw_fuel_bar(screen, pygame.Rect(33, 162, 430, 13), fuel_fraction)

    # Keep the vector addition diagram only inside the enlarged route monitor.
    monitor = pygame.Rect(SCREEN_WIDTH - 470, 18, 452, 438)
    draw_route_monitor(monitor, plane_pos, target_pos, heading_angle,
                       air_velocity, wind_velocity, ground_velocity)
    draw_dashboard(air_velocity, wind_velocity, ground_velocity, distance_to_target)

    if out_of_fuel:
        banner = pygame.Rect(395, 270, 490, 125)
        draw_panel(screen, banner, (36, 12, 15, 245), (255, 84, 84, 235), radius=14)
        draw_text(screen, "OUT OF FUEL — CRASH!", banner.x + 58, banner.y + 17,
                  BIG_FONT, (255, 106, 106))
        draw_text(screen, "The fuel tank is empty. Press R to retry or M for the grid.",
                  banner.x + 18, banner.y + 64, SMALL_FONT, WHITE)
    elif arrived:
        banner = pygame.Rect(405, 280, 470, 100)
        draw_panel(screen, banner, (6, 20, 31, 238), (69, 238, 130, 220), radius=14)
        draw_text(screen, "DESTINATION REACHED!", banner.x + 47, banner.y + 17,
                  BIG_FONT, GREEN)
        draw_text(screen, "You entered the arrival radius. Press R to retry or M for map.",
                  banner.x + 18, banner.y + 59, SMALL_FONT, WHITE)
    elif out_of_course:
        banner = pygame.Rect(395, 280, 490, 112)
        draw_panel(screen, banner, (30, 14, 17, 242), (255, 119, 102, 225), radius=14)
        draw_text(screen, "OUT OF ROUTE CORRIDOR", banner.x + 39, banner.y + 17,
                  BIG_FONT, (255, 131, 111))
        draw_text(screen, "The lateral limit was exceeded. Press R to retry.",
                  banner.x + 26, banner.y + 59, SMALL_FONT, WHITE)
    elif missed_destination:
        banner = pygame.Rect(395, 280, 490, 112)
        draw_panel(screen, banner, (30, 14, 17, 242), (255, 119, 102, 225), radius=14)
        draw_text(screen, "DESTINATION MISSED", banner.x + 69, banner.y + 17,
                  BIG_FONT, (255, 131, 111))
        draw_text(screen, "You flew past the arrival zone. Press R to retry.",
                  banner.x + 31, banner.y + 59, SMALL_FONT, WHITE)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
# The main loop repeats until the user closes the window or presses ESC.
# Each pass: measure elapsed time, handle input, update the flight physics,
# draw the current screen, and show that finished frame.
running = True
while running:
    # clock.tick(FPS) limits the frame rate. Dividing milliseconds by 1000
    # converts them to seconds; the cap prevents a long pause/window drag
    # from making the plane jump a huge distance in one update.
    dt = min(clock.tick(FPS) / 1000.0, 0.05)

    # Handle user input before updating physics. KEYDOWN is used for one-time
    # actions (menus/restart/quit); held steering keys are checked later each frame.
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            # ESC always quits. M changes screens, while the number/enter keys
            # only affect aircraft selection when that menu is open.
            if event.key == pygame.K_ESCAPE:
                running = False
            elif event.key == pygame.K_m:
                if mode in ("FLIGHT", "PLANE_SELECT"):
                    mode = "MAP"
                elif mode == "MAP" and destination_name is not None and active_destination_name == destination_name and target_pos is not None:
                    mode = "FLIGHT"
            elif mode == "PLANE_SELECT":
                if event.key == pygame.K_1:
                    selected_aircraft_id = "small"
                elif event.key == pygame.K_2:
                    selected_aircraft_id = "medium"
                elif event.key == pygame.K_3:
                    selected_aircraft_id = "large"
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and destination_name is not None:
                    start_flight(destination_name, selected_aircraft_id)
            elif event.key == pygame.K_r and mode == "FLIGHT":
                restart_flight()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Pygame reports mouse pixels as a tuple; convert it to a Vector so
            # we can use Vector subtraction and magnitude to find clicked airports.
            mouse_pos = Vector(event.pos[0], event.pos[1])
            if mode == "MAP":
                # Pick the nearest airport marker under the mouse.
                hit = None
                hit_distance = MAP_CLICK_RADIUS + 1
                for airport_name, airport_position in AIRPORT_POSITIONS.items():
                    distance = (mouse_pos - airport_position).magnitude()
                    if distance <= MAP_CLICK_RADIUS and distance < hit_distance:
                        hit = airport_name
                        hit_distance = distance
                # The starting airport is departure-only. Clicking any other
                # airport sets the route and opens the aircraft-selection menu.
                if hit is not None and hit != START_AIRPORT:
                    destination_name = hit
                    selected_aircraft_id = "medium"
                    mode = "PLANE_SELECT"
            elif mode == "PLANE_SELECT":
                # First determine whether an aircraft card was clicked. The
                # separate start button below begins the flight after selection.
                for index, card_rect in enumerate(AIRCRAFT_CARD_RECTS):
                    if card_rect.collidepoint(event.pos):
                        selected_aircraft_id = AIRCRAFT_ORDER[index]
                        break
                if START_FLIGHT_RECT.collidepoint(event.pos) and destination_name is not None:
                    start_flight(destination_name, selected_aircraft_id)

    # If flight state is incomplete, return to the map instead of doing vector
    # arithmetic with None. A valid destination + target must exist for flight.
    # Defensive state validation: if a destination or target vector ever goes
    # missing, leave flight mode instead of attempting arithmetic with None.
    if mode == "FLIGHT" and (
            not is_vector(target_pos)
            or destination_name not in AIRPORTS
            or selected_aircraft_id not in AIRCRAFT):
        mode = "MAP"

    # Pause flight updates in the airport grid and aircraft-selection menu.
    # During flight, actual travelled distance determines fuel consumed.
    if (mode == "FLIGHT" and is_vector(target_pos)
            and destination_name in AIRPORTS
            and selected_aircraft_id in AIRCRAFT
            and not arrived and not out_of_course
            and not missed_destination and not out_of_fuel):
        if target_pos is None:
            continue
        keys = pygame.key.get_pressed()
        turn_input = 0.0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            turn_input -= 1.0
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            turn_input += 1.0

        # Steering changes the direction the plane points (heading). It does
        # NOT set the direction of movement directly: wind is added afterward.
        # The allowed heading is clamped to a cone around the planned route.
        heading_angle = wrap_angle(
            heading_angle + math.radians(STEERING_RATE) * turn_input * dt
        )
        relative_heading = wrap_angle(heading_angle - route_heading)
        max_offset = math.radians(MAX_STEERING_DEGREES)
        relative_heading = max(-max_offset, min(max_offset, relative_heading))
        heading_angle = wrap_angle(route_heading + relative_heading)

        # Build all three velocity vectors. Air speed is fixed for the chosen
        # aircraft; wind varies with position; their sum is ground velocity.
        _, air_velocity, wind_velocity, ground_velocity = calculate_velocities(
            plane_pos, target_pos, heading_angle
        )
        position_scale = SIM_UNITS_PER_KMH_SECOND
        old_position = Vector(plane_pos.x, plane_pos.y)
        # Basic numerical integration: position change = velocity * elapsed time.
        # position_scale converts km/h into the simulation's screen-like units.
        next_position = plane_pos + ground_velocity * (position_scale * dt)
        step_distance_km = (next_position - old_position).magnitude() * km_per_sim_unit

        # Fuel burn is based on actual ground distance and current gross mass.
        # As fuel is consumed, the plane becomes lighter and its burn rate falls.
        current_burn_per_1000 = fuel_burn_kg_per_1000_km(
            selected_aircraft_id, fuel_remaining_kg
        )
        fuel_step = step_distance_km * current_burn_per_1000 / 1000.0
        fuel_remaining_kg = max(0.0, fuel_remaining_kg - fuel_step)
        fuel_used_kg += fuel_step

        elapsed_flight_time += dt * simulation_time_acceleration
        path_sample_timer += dt
        plane_pos = next_position

        # Check flight outcomes after moving: arrive, run out of fuel, leave the
        # allowed corridor, or pass beyond the target without entering its radius.
        distance_to_target = (target_pos - plane_pos).magnitude()
        if distance_to_target <= arrival_radius_sim:
            arrived = True
        elif fuel_remaining_kg <= 0.0:
            out_of_fuel = True
        elif abs(signed_cross_track(plane_pos)) > corridor_half_width:
            out_of_course = True
        elif (plane_pos.x * route_direction.x + plane_pos.y * route_direction.y) > flight_distance + MAX_OVERSHOOT:
            missed_destination = True

        # Save the plane's position periodically, not every frame, so the trail
        # looks smooth but the history list does not grow without limit.
        if path_sample_timer >= PATH_SAMPLE_INTERVAL or arrived or out_of_course or missed_destination or out_of_fuel:
            path_history.append(Vector(plane_pos.x, plane_pos.y))
            path_sample_timer = 0.0
            if len(path_history) > 1800:
                path_history = path_history[::2]

    # Draw exactly one interface per frame, based on the current program mode.
    if mode == "MAP":
        draw_map_view()
    elif mode == "PLANE_SELECT":
        draw_aircraft_select_view()
    elif destination_name in AIRPORTS and is_vector(target_pos):
        draw_cockpit_view()
    else:
        draw_map_view()

    pygame.display.flip()

pygame.quit()
sys.exit()
