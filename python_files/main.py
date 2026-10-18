"""MathHacks 2.0 — wind navigation simulation.

Two interfaces:
  MAP VIEW: click an airport to board and begin a flight.
  COCKPIT VIEW: steer the plane while wind changes the ground track.

Controls in the cockpit:
  LEFT / RIGHT or A / D : turn the plane's heading
  M                    : return to the world map (flight pauses)
  R                    : restart the current route
  ESC                  : quit

Put images/worldMap.jpg next to this file in an images/ directory if you
want to use your team's map. The simulation also works without that image.
"""

from __future__ import annotations

import math
import os
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
pygame.display.set_caption("MathHacks 2.0 — Wind Navigation")
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAP_PATH = os.path.join(BASE_DIR, "images", "worldMap.jpg")
try:
    world_map = pygame.image.load(MAP_PATH).convert()
    world_map = pygame.transform.smoothscale(world_map, (SCREEN_WIDTH, SCREEN_HEIGHT))
except (pygame.error, FileNotFoundError, OSError):
    world_map = None
    print("Map image not found; using the built-in map background.")

# ---------------------------------------------------------------------------
# Airports and the world-map projection
# ---------------------------------------------------------------------------
# Coordinates are approximate airport latitudes / longitudes.
AIRPORTS = {
    "Toronto Pearson (YYZ)": (43.6777, -79.6248),
    "New York JFK (JFK)": (40.6413, -73.7781),
    "Los Angeles (LAX)": (33.9416, -118.4085),
    "London Heathrow (LHR)": (51.4700, -0.4543),
    "Paris CDG (CDG)": (49.0097, 2.5479),
    "Dubai (DXB)": (25.2532, 55.3657),
    "Tokyo Haneda (HND)": (35.5494, 139.7798),
    "Sydney (SYD)": (-33.9399, 151.1753),
    "Reykjavik (KEF)": (63.9850, -22.6056),
}
START_AIRPORT = "Toronto Pearson (YYZ)"


def geo_to_screen(latitude: float, longitude: float) -> Vector:
    """Project latitude/longitude onto a simple equirectangular map."""
    x = (longitude + 180.0) / 360.0 * SCREEN_WIDTH
    y = (90.0 - latitude) / 180.0 * SCREEN_HEIGHT
    return Vector(x, y)


AIRPORT_POSITIONS = {
    name: geo_to_screen(lat, lon)
    for name, (lat, lon) in AIRPORTS.items()
}

# ---------------------------------------------------------------------------
# Flight physics
# ---------------------------------------------------------------------------
# Flight-vector values are expressed in km/h, not arbitrary speed units.
# The fixed airspeed is representative of a passenger jet. The wind field is
# intentionally strong enough to make drift and groundspeed changes visible.
AIR_SPEED = 850.0                # fixed airspeed in km/h; user cannot change it
WIND_X_STRENGTH = 220.0          # maximum wind component, km/h
WIND_Y_STRENGTH = 185.0          # maximum wind component, km/h

# The cockpit world is a time-compressed, abstract map so a flight fits a demo.
# This calibration maps 850 km/h to about 42 simulation units per wall-clock sec.
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


def target_bearing(position: Vector, target: Vector) -> float:
    """Return the screen-coordinate angle from position toward target."""
    difference = target - position
    return math.atan2(difference.y, difference.x)


def signed_cross_track(position: Vector) -> float:
    """Signed side distance from the initial planned route centreline."""
    # 2-D cross product of the unit route direction and position offset.
    return route_direction.x * position.y - route_direction.y * position.x


def wind_at(position: Vector) -> Vector:
    """Return the local wind velocity in km/h.

    Wind direction and magnitude vary across the simulated world. Both wind
    components use km/h, so they can be added directly to the air-velocity
    vector without a unit mismatch.
    """
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


def calculate_velocities(position: Vector, target: Vector, heading: float):
    """Return bearing, air velocity, wind velocity, and their sum (ground velocity)."""
    bearing = target_bearing(position, target)
    air_velocity = air_velocity_from_heading(heading)
    wind_velocity = wind_at(position)
    ground_velocity = air_velocity + wind_velocity
    return bearing, air_velocity, wind_velocity, ground_velocity


def compass_heading(screen_angle: float) -> float:
    """Convert screen-coordinate angle (0=east, positive=down) to compass degrees."""
    return (90.0 - math.degrees(screen_angle)) % 360.0


def route_vector_for_airport(destination_name: str) -> Vector:
    """Get the shortest map-direction vector from Toronto to the destination.

    Wrap horizontal map distance across the dateline for routes like Toronto–Tokyo.
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
mode = "MAP"  # either MAP or FLIGHT

destination_name = None
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
elapsed_flight_time = 0.0
path_history = [Vector(0.0, 0.0)]
path_sample_timer = 0.0


def start_flight(new_destination: str) -> None:
    """Initialise a route scaled to real airport distance with slight variation."""
    global mode, destination_name, plane_pos, target_pos, heading_angle, route_heading
    global route_direction, flight_distance, route_distance_km, km_per_sim_unit
    global simulation_time_acceleration, arrival_radius_sim, corridor_half_width
    global steering_offset_degrees, arrived, out_of_course, missed_destination
    global elapsed_flight_time, path_history, path_sample_timer

    destination_name = new_destination
    base_route_vector = route_vector_for_airport(new_destination)
    base_direction = base_route_vector.unit_vector()

    # Each flight gets a tiny route-angle variation (at most 2 degrees), so
    # retries aren't pixel-for-pixel identical without making the route unfair.
    route_variation = math.radians(random.uniform(-2.0, 2.0))
    c, s = math.cos(route_variation), math.sin(route_variation)
    direction = Vector(
        base_direction.x * c - base_direction.y * s,
        base_direction.x * s + base_direction.y * c,
    ).unit_vector()

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
    steering_offset_degrees = 0.0
    arrived = False
    out_of_course = False
    missed_destination = False
    elapsed_flight_time = 0.0
    path_history = [Vector(plane_pos.x, plane_pos.y)]
    path_sample_timer = 0.0
    mode = "FLIGHT"


def restart_flight() -> None:
    if destination_name is not None:
        start_flight(destination_name)


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
def draw_text(surface, text, x, y, font=FONT, colour=WHITE):
    surface.blit(font.render(str(text), True, colour), (int(x), int(y)))


def format_flight_time(seconds: float) -> str:
    """Format accelerated simulation time as hours and minutes."""
    total_minutes = max(0, int(seconds // 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours:02d}h {minutes:02d}m"
    return f"{minutes:02d}m {int(seconds % 60):02d}s"


def draw_panel(surface, rect, colour=(9, 18, 30, 220), border=(92, 126, 148, 160), radius=12):
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
    direction = difference / total_length
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
    x, y = round(position.x), round(position.y)
    colour = YELLOW if is_start else (GREEN if selected else WHITE)
    pygame.draw.circle(surface, (8, 20, 31), (x, y), 10)
    pygame.draw.circle(surface, colour, (x, y), 6)
    pygame.draw.circle(surface, (8, 20, 31), (x, y), 2)
    label = name.split(" (")[0]
    # Keep the airport text compact; it is a map label, not the main UI.
    label_x = x + 10
    label_y = y - 17
    if name.startswith("Tokyo") or name.startswith("Sydney"):
        label_x = x - 105
    draw_text(surface, label, label_x, label_y, SMALL_FONT, colour)


def fallback_map_background(surface):
    surface.fill((16, 43, 61))
    for x in range(0, SCREEN_WIDTH, 80):
        pygame.draw.line(surface, (27, 63, 81), (x, 0), (x, SCREEN_HEIGHT), 1)
    for y in range(0, SCREEN_HEIGHT, 80):
        pygame.draw.line(surface, (27, 63, 81), (0, y), (SCREEN_WIDTH, y), 1)
    # Decorative, map-like silhouettes so the fallback still feels like a map.
    land_colour = (35, 76, 84)
    pygame.draw.polygon(surface, land_colour, [(45, 100), (170, 70), (260, 125), (255, 215),
                                                (190, 270), (125, 220), (70, 245), (30, 170)])
    pygame.draw.polygon(surface, land_colour, [(470, 90), (570, 75), (640, 125), (610, 210),
                                                (540, 225), (485, 165)])
    pygame.draw.polygon(surface, land_colour, [(790, 130), (890, 100), (1015, 140), (1080, 205),
                                                (1030, 270), (900, 240), (820, 195)])
    pygame.draw.polygon(surface, land_colour, [(1030, 405), (1135, 420), (1190, 505), (1110, 560),
                                                (1035, 510)])


def draw_map_view():
    """Airport-selection interface shown before boarding or when pressing M."""
    if world_map is not None:
        screen.blit(world_map, (0, 0))
        shade = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        shade.fill((5, 15, 25, 58))
        screen.blit(shade, (0, 0))
    else:
        fallback_map_background(screen)

    # Show a thin route on the world map once a destination has been chosen.
    if destination_name is not None:
        origin = AIRPORT_POSITIONS[START_AIRPORT]
        destination = AIRPORT_POSITIONS[destination_name]
        delta = route_vector_for_airport(destination_name)
        if abs(delta.x) < SCREEN_WIDTH / 2:
            pygame.draw.line(screen, GREEN,
                             (round(origin.x), round(origin.y)),
                             (round(destination.x), round(destination.y)), 2)
        else:
            # Dateline-crossing route: draw toward the nearest edge on each side.
            edge_x = 0 if delta.x < 0 else SCREEN_WIDTH
            opposite_edge = SCREEN_WIDTH if edge_x == 0 else 0
            pygame.draw.line(screen, GREEN, (round(origin.x), round(origin.y)),
                             (edge_x, round(origin.y + delta.y * (edge_x-origin.x) / delta.x)), 2)
            pygame.draw.line(screen, GREEN, (opposite_edge, round(destination.y)),
                             (round(destination.x), round(destination.y)), 2)

    # Start marker and airport markers.
    for airport_name, airport_position in AIRPORT_POSITIONS.items():
        draw_airport(screen, airport_name, airport_position,
                     selected=(airport_name == destination_name),
                     is_start=(airport_name == START_AIRPORT))

    draw_panel(screen, pygame.Rect(18, 18, 415, 156), (5, 14, 26, 226))
    draw_text(screen, "MATHHACKS 2.0", 34, 29, TITLE_FONT, WHITE)
    draw_text(screen, "WORLD MAP  /  SELECT DESTINATION", 34, 61, SMALL_FONT, CYAN)
    draw_text(screen, "Starting airport: Toronto Pearson (YYZ)", 34, 88, SMALL_FONT, WHITE)
    if destination_name is None:
        draw_text(screen, "Click any other airport to board the plane.", 34, 113, SMALL_FONT, GREEN)
        draw_text(screen, "A cockpit view opens after you choose a destination.",
                  34, 135, TINY_FONT, MUTED)
    else:
        draw_text(screen, "Selected: " + destination_name, 34, 112, SMALL_FONT, GREEN)
        draw_text(screen, "Click another airport to change your route.",
                  34, 136, TINY_FONT, MUTED)

    draw_panel(screen, pygame.Rect(18, SCREEN_HEIGHT - 53, SCREEN_WIDTH - 36, 35),
               (5, 14, 26, 222), border=None, radius=8)
    draw_text(screen, "YELLOW: departure     GREEN: selected destination / planned route     CLICK AIRPORT: board   |   ESC: quit",
              31, SCREEN_HEIGHT - 44, SMALL_FONT, WHITE)


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

    ground_unit = ground_velocity.unit_vector()
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


def draw_dashboard(heading: float, reference_heading: float, air_velocity: Vector,
                   wind_velocity: Vector, ground_velocity: Vector,
                   distance_to_target: float):
    """Cockpit instrument panel along the bottom of the screen."""
    top = 548
    pygame.draw.polygon(screen, (12, 23, 35), [
        (0, top + 20), (355, top - 8), (925, top - 8),
        (SCREEN_WIDTH, top + 20), (SCREEN_WIDTH, SCREEN_HEIGHT), (0, SCREEN_HEIGHT)
    ])
    pygame.draw.line(screen, (72, 102, 122), (0, top + 20),
                     (SCREEN_WIDTH, top + 20), 2)
    draw_text(screen, "MATHHACKS AIR NAVIGATION", 28, 558, TITLE_FONT, WHITE)
    draw_text(screen, "KM/H VECTORS  /  COMPRESSED DEMO FLIGHT TIME", 364, 563, TINY_FONT, MUTED)

    route_offset = math.degrees(wrap_angle(heading - reference_heading))
    air_heading = compass_heading(heading)
    ground_heading = compass_heading(math.atan2(ground_velocity.y, ground_velocity.x))

    cards = [
        ("AIR SPEED", f"{air_velocity.magnitude():,.0f} km/h", YELLOW),
        ("WIND SPEED", f"{wind_velocity.magnitude():,.0f} km/h", WIND_COLOUR),
        ("GROUND SPEED", f"{ground_velocity.magnitude():,.0f} km/h", CYAN),
        ("NOSE HEADING", f"{air_heading:03.0f} deg", YELLOW),
        ("GROUND TRACK", f"{ground_heading:03.0f} deg", CYAN),
        ("DISTANCE LEFT", f"{distance_to_target:,.0f} km", WHITE),
    ]
    card_width = 190
    card_gap = 18
    start_x = 29
    for i, (label, value, colour) in enumerate(cards):
        x = start_x + i * (card_width + card_gap)
        rect = pygame.Rect(x, 589, card_width, 69)
        draw_panel(screen, rect, (18, 33, 47, 238), (72, 103, 122, 170), radius=8)
        draw_text(screen, label, x + 11, 599, TINY_FONT, MUTED)
        draw_text(screen, value, x + 11, 622, FONT, colour)

    draw_text(screen, f"ROUTE HEADING OFFSET: {route_offset:+.0f} deg",
              29, 680, SMALL_FONT, WHITE)
    draw_text(screen, "A / D or LEFT / RIGHT: steer     M: map     R: restart     ESC: quit",
              340, 680, SMALL_FONT, WHITE)

def draw_cockpit_view():
    """First-person flight screen; the top-right mini-map shows the route and vectors."""
    if target_pos is None:
        return
    bearing, air_velocity, wind_velocity, ground_velocity = calculate_velocities(
        plane_pos, target_pos, heading_angle
    )
    distance_to_target = (target_pos - plane_pos).magnitude() * km_per_sim_unit
    draw_cockpit_background(heading_angle, bearing)

    # Compact information in the upper left.
    top_left = pygame.Rect(18, 18, 360, 115)
    draw_panel(screen, top_left, (7, 16, 28, 216), radius=11)
    draw_text(screen, "COCKPIT VIEW  /  EN ROUTE", 32, 29, TITLE_FONT, WHITE)
    draw_text(screen, destination_name, 33, 60, SMALL_FONT, GREEN)
    draw_text(screen, f"Flight time  {format_flight_time(elapsed_flight_time)}",
              33, 83, SMALL_FONT, MUTED)
    draw_text(screen, f"Route heading offset  {math.degrees(wrap_angle(heading_angle-route_heading)):+.0f} deg",
              33, 106, SMALL_FONT, YELLOW)

    # Keep the vector addition diagram only inside the enlarged route monitor.
    monitor = pygame.Rect(SCREEN_WIDTH - 470, 18, 452, 438)
    draw_route_monitor(monitor, plane_pos, target_pos, heading_angle,
                       air_velocity, wind_velocity, ground_velocity)
    draw_dashboard(heading_angle, route_heading, air_velocity, wind_velocity,
                   ground_velocity, distance_to_target)

    if arrived:
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
running = True
while running:
    dt = min(clock.tick(FPS) / 1000.0, 0.05)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
            elif event.key == pygame.K_m:
                if mode == "FLIGHT":
                    mode = "MAP"
                elif destination_name is not None:
                    mode = "FLIGHT"
            elif event.key == pygame.K_r and mode == "FLIGHT":
                restart_flight()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and mode == "MAP":
            mouse_pos = Vector(event.pos[0], event.pos[1])
            # Pick the closest airport marker under the mouse so close markers
            # cannot be swallowed by a different airport earlier in the dict.
            hit = None
            hit_distance = MAP_CLICK_RADIUS + 1
            for airport_name, airport_position in AIRPORT_POSITIONS.items():
                distance = (mouse_pos - airport_position).magnitude()
                if distance <= MAP_CLICK_RADIUS and distance < hit_distance:
                    hit = airport_name
                    hit_distance = distance
            if hit is not None and hit != START_AIRPORT:
                start_flight(hit)

    # Pause the flight while the world-map interface is open. Reaching the
    # arrival radius or leaving the permitted route corridor stops the flight.
    if mode == "FLIGHT" and not arrived and not out_of_course and not missed_destination:
        if target_pos is None:
            continue
        keys = pygame.key.get_pressed()
        turn_input = 0.0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            turn_input -= 1.0
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            turn_input += 1.0

        # The heading is controlled by the pilot and constrained around the
        # INITIAL planned route, not automatically snapped toward the airport.
        # This keeps heading independent from the changing ground track.
        heading_angle = wrap_angle(
            heading_angle + math.radians(STEERING_RATE) * turn_input * dt
        )
        relative_heading = wrap_angle(heading_angle - route_heading)
        max_offset = math.radians(MAX_STEERING_DEGREES)
        relative_heading = max(-max_offset, min(max_offset, relative_heading))
        heading_angle = wrap_angle(route_heading + relative_heading)
        steering_offset_degrees = math.degrees(relative_heading)

        # Core model: fixed airspeed plus local wind gives ground velocity.
        # Groundspeed is |v_ground|, so a headwind/tailwind changes the speed
        # while a crosswind also changes the direction of travel.
        _, air_velocity, wind_velocity, ground_velocity = calculate_velocities(
            plane_pos, target_pos, heading_angle
        )
        # Integrate real km/h velocities through an accelerated simulation clock:
        # km/h -> km, then km -> this route's local simulation coordinates.
        position_scale = simulation_time_acceleration / (3600.0 * km_per_sim_unit)
        next_position = plane_pos + ground_velocity * (position_scale * dt)
        elapsed_flight_time += dt * simulation_time_acceleration
        path_sample_timer += dt

        # Keep actual movement; never snap/teleport the plane to the target.
        plane_pos = next_position
        distance_to_target = (target_pos - plane_pos).magnitude()
        if distance_to_target <= arrival_radius_sim:
            arrived = True
        elif abs(signed_cross_track(plane_pos)) > corridor_half_width:
            out_of_course = True
        elif plane_pos.dot(route_direction) > flight_distance + MAX_OVERSHOOT:
            # The aircraft crossed beyond the destination without entering its
            # arrival radius. Stop the flight rather than steering/teleporting it
            # back toward the airport.
            missed_destination = True

        if path_sample_timer >= PATH_SAMPLE_INTERVAL or arrived or out_of_course or missed_destination:
            path_history.append(Vector(plane_pos.x, plane_pos.y))
            path_sample_timer = 0.0
            # Keep a bounded amount of history for smooth rendering.
            if len(path_history) > 1800:
                path_history = path_history[::2]

    # Draw whichever interface is active.
    if mode == "MAP":
        draw_map_view()
    elif destination_name is not None and target_pos is not None:
        draw_cockpit_view()
    else:
        draw_map_view()

    pygame.display.flip()

pygame.quit()
sys.exit()