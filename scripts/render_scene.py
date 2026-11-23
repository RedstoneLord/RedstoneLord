#!/usr/bin/env python3
"""Render the foxtrot forest station as a colored ASCII PNG or looping GIF."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import lru_cache
from math import atan2, cos, hypot, pi, radians, sin, tan
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont


# Shadow, highlight, and the surface brightness at which the highlight takes over.
INK_SHADES = (
    ("#142A0E", "#2A4823", 0.39),
    ("#9F4153", "#FC6B6E", 0.53),
    ("#454C5C", "#777C88", 0.47),
    ("#414362", "#656695", 0.31),
    ("#5C5D8B", "#8F8DC6", 0.60),
    ("#245912", "#398E00", 0.31),
    ("#522F1F", "#87543A", 0.47),
    ("#9D672B", "#EBAD42", 0.54),
    ("#7D8B47", "#B9CA77", 0.62),
)
EVERGREEN, PINK, SLATE, GRAPE, PERIWINKLE, GREEN, WOOD, AMBER, FIREFLY = range(len(INK_SHADES))
GLYPHS = " .,:;=+*#%@"
GRID_SIZE = (100, 34)
CELL_SIZE = (10, 16)
SAMPLES_PER_CELL = (10, 16)
BACKGROUND = "#090C16"
STATION_CENTER = (3.45, 1.6)
LOCKED_DIRECTION = (-0.58, -0.37, 0.73)
PIVOT_HEIGHT = 3.91
LAMP_FOOT = (-3.24, -2.38, 0)
LAMP_TOP = (*LAMP_FOOT[:2], 2.21)
LAMP_BULB = (LAMP_TOP[0] + 0.36, LAMP_TOP[1] + 0.02, LAMP_TOP[2] + 0.07)
LOOP_SECONDS = 18
FRAMES_PER_SECOND = 10
# Seconds, azimuth offset, and elevation offset from the signal-lock pose (degrees).
SWEEP_KEYS = (
    (0.0, -16.0, -5.0),
    (3.9, 31.0, 3.0),
    (5.8, -2.1, 0.8),
    (6.6, 0.0, 0.0),
    (12.8, 0.0, 0.0),
    (16.6, -26.0, -7.0),
    (18.0, -16.0, -5.0),
)
# Start time, lifetime, and origin in normalized screen coordinates.
FIREFLY_FLASHES = ((3.0, 1.1, 0.321, 0.774), (8.4, 1.2, 0.444, 0.835), (14.6, 1.1, 0.878, 0.773))


def unit(vector):
    return vector / np.linalg.norm(vector)


@dataclass(frozen=True)
class Mesh:
    vertices: np.ndarray
    faces: list[tuple[int, int, int]]
    ink: int
    brightness: float = 1.0
    two_sided: bool = False


class Camera:
    def __init__(self, eye, target, width, height, vertical_fov):
        self.eye = np.asarray(eye, dtype=float)
        self.forward = unit(np.asarray(target, dtype=float) - self.eye)
        self.right = unit(np.cross(self.forward, (0, 0, 1)))
        self.up = np.cross(self.right, self.forward)
        self.center = np.array((width / 2, height / 2))
        self.focal_length = height / (2 * tan(radians(vertical_fov) / 2))

    def project(self, points):
        offset = np.asarray(points) - self.eye
        depth = offset @ self.forward
        if np.any(depth <= 0):
            raise ValueError("The scene must lie in front of the camera.")
        plane = np.column_stack((offset @ self.right, -(offset @ self.up)))
        return self.center + self.focal_length * plane / depth[:, None], depth


class Frame:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.tone = np.zeros((height, width), dtype=np.float32)
        self.ink = np.full((height, width), GRAPE, dtype=np.uint8)
        self.depth = np.zeros((height, width), dtype=np.float32)
        self.warmth = np.zeros((height, width), dtype=np.float32)

    def copy(self):
        result = Frame(self.width, self.height)
        result.tone[:] = self.tone
        result.ink[:] = self.ink
        result.depth[:] = self.depth
        result.warmth[:] = self.warmth
        return result

    def disk(self, center, radius, ink, tone):
        x, y = center
        left, right = max(0, int(x - radius)), min(self.width, int(x + radius) + 1)
        top, bottom = max(0, int(y - radius)), min(self.height, int(y + radius) + 1)
        if left >= right or top >= bottom:
            return
        yy, xx = np.ogrid[top:bottom, left:right]
        mask = (xx - x) ** 2 + (yy - y) ** 2 <= radius ** 2
        self.tone[top:bottom, left:right][mask] = tone
        self.ink[top:bottom, left:right][mask] = ink
        self.warmth[top:bottom, left:right][mask] = 0

    def add_lamplight(self, camera, position, radius):
        # Undo perspective using the depth buffer, then measure the lamp's distance from each surface.
        surface = self.depth > 0
        depth = np.divide(1, self.depth, out=np.zeros_like(self.depth), where=surface)
        yy, xx = np.ogrid[:self.height, :self.width]
        x = (xx + 0.5 - camera.center[0]) * depth / camera.focal_length
        y = (camera.center[1] - yy - 0.5) * depth / camera.focal_length
        lamp = np.asarray(position) - camera.eye
        dx, dy, dz = x - lamp @ camera.right, y - lamp @ camera.up, depth - lamp @ camera.forward
        distance_squared = dx ** 2 + dy ** 2 + dz ** 2
        light = np.maximum(0, 1 - distance_squared / radius ** 2) ** 2
        self.warmth[surface] = light[surface]
        self.tone[surface] += 0.60 * light[surface] * (1 - self.tone[surface])

    def draw_mesh(self, mesh, camera):
        projected, depth = camera.project(mesh.vertices)
        light = unit(np.array((-0.74, -0.43, 0.92)))
        for face in mesh.faces:
            indices = list(face)
            a, b, c = mesh.vertices[indices]
            normal = np.cross(b - a, c - a)
            if np.linalg.norm(normal) < 1e-9:
                continue
            diffuse = unit(normal) @ light
            diffuse = abs(diffuse) if mesh.two_sided else max(0, diffuse)
            tone = mesh.brightness * (0.32 + 0.68 * diffuse)
            self.draw_triangle(projected[indices], depth[indices], mesh.ink, tone)

    def draw_triangle(self, points, depth, ink, tone):
        left, top = np.maximum(np.floor(points.min(axis=0)).astype(int), 0)
        right, bottom = np.minimum(np.ceil(points.max(axis=0)).astype(int) + 1,
                                   (self.width, self.height))
        if left >= right or top >= bottom:
            return

        a, b, c = points
        ab, ac = b - a, c - a
        area = ab[0] * ac[1] - ab[1] * ac[0]
        if abs(area) < 1e-9:
            return

        yy, xx = np.ogrid[top:bottom, left:right]
        x, y = xx + 0.5 - a[0], yy + 0.5 - a[1]
        wb = (x * ac[1] - y * ac[0]) / area
        wc = (ab[0] * y - ab[1] * x) / area
        wa = 1 - wb - wc
        inverse_depth = wa / depth[0] + wb / depth[1] + wc / depth[2]
        region = np.s_[top:bottom, left:right]
        mask = (wa >= 0) & (wb >= 0) & (wc >= 0) & (inverse_depth > self.depth[region])
        self.depth[region][mask] = inverse_depth[mask]
        self.tone[region][mask] = tone
        self.ink[region][mask] = ink
        self.warmth[region][mask] = 0


def ring_basis(axis):
    guide = (1, 0, 0) if abs(axis[0]) < 0.9 else (0, 1, 0)
    tangent = unit(np.cross(axis, guide))
    return tangent, np.cross(axis, tangent)


def ring(center, tangent, bitangent, radius, segments):
    return [center + radius * (cos(angle) * tangent + sin(angle) * bitangent)
            for angle in (2 * pi * index / segments for index in range(segments))]


def band_faces(rings, segments):
    faces = []
    for layer in range(rings - 1):
        for index in range(segments):
            a = layer * segments + index
            b = layer * segments + (index + 1) % segments
            faces.extend(((a, b, a + segments), (b, b + segments, a + segments)))
    return faces


def tube(start, end, radius, ink, brightness=1.0, segments=8, tip_radius=None):
    start, end = np.asarray(start), np.asarray(end)
    tangent, bitangent = ring_basis(unit(end - start))
    if tip_radius is None:
        tip_radius = radius
    vertices = ring(start, tangent, bitangent, radius, segments)
    vertices += ring(end, tangent, bitangent, tip_radius, segments)
    return Mesh(np.asarray(vertices), band_faces(2, segments), ink, brightness)


def rectangular_block(center, bottom, top, footprint, brightness, top_footprint=None, ink=SLATE):
    if top_footprint is None:
        top_footprint = footprint
    x, y = center
    vertices = []
    for height, (width, depth) in ((bottom, footprint), (top, top_footprint)):
        vertices.extend((x + dx * width / 2, y + dy * depth / 2, height)
                        for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)))
    faces = band_faces(2, 4) + [(4, 5, 6), (4, 6, 7)]
    return Mesh(np.asarray(vertices), faces, ink, brightness)


def station_mount(center):
    x, y = center
    deck_height = 1.36
    meshes = [
        rectangular_block(center, 0, 0.22, (4.74, 3.68), 0.62, (4.60, 3.57)),
        rectangular_block(center, 0.22, 1.18, (4.33, 3.34), 0.84),
        rectangular_block(center, 1.18, deck_height, (4.41, 3.42), 0.99),
        rectangular_block(center, deck_height, 2.89, (2.13, 1.81), 0.72, (1.62, 1.54)),
        rectangular_block(center, 2.89, 3.07, (1.86, 1.68), 0.93),
        rectangular_block(center, 3.07, PIVOT_HEIGHT, (1.69, 1.57), 0.73, (1.24, 1.42)),
        rectangular_block((x + 0.22, y - 0.87), 1.39, 2.50, (0.63, 0.18), 0.31),
    ]
    for side in (-1, 1):
        foot = (x + side * 1.47, y - 1.17, deck_height)
        shoulder = (x + side * 0.73, y - 0.71, 3.00)
        meshes.append(tube(foot, shoulder, 0.10, SLATE, 0.94, segments=4))

    angle = radians(11)
    rotation = np.array(((cos(angle), -sin(angle), 0), (sin(angle), cos(angle), 0), (0, 0, 1)))
    origin = np.array((*center, 0))
    return [Mesh((mesh.vertices - origin) @ rotation.T + origin, mesh.faces, mesh.ink, mesh.brightness)
            for mesh in meshes]


def reflector_braces(location, axis, tangent, bitangent, radius, depth):
    def surface_point(x, y):
        lift = depth * (x ** 2 + y ** 2) / radius ** 2 + 0.09
        return location + x * tangent + y * bitangent + lift * axis

    # Long ribs and shorter cross members follow the reflector's curved surface.
    paths = []
    for angle, offset in ((-0.25, -0.43), (-0.25, 0.0), (-0.25, 0.43),
                          (1.02, -0.40), (1.02, 0.0), (1.02, 0.40)):
        limit = 0.974 * radius * (1 - offset ** 2) ** 0.5
        shift = offset * radius
        points = [surface_point(distance * cos(angle) - shift * sin(angle),
                                distance * sin(angle) + shift * cos(angle))
                  for distance in np.linspace(-limit, limit, 10)]
        paths.extend(tube(start, end, 0.085, PERIWINKLE, 1.0, segments=6)
                     for start, end in zip(points, points[1:]))
    return paths


def dish(location, axis):
    segments = 32
    radius, depth = 2.55, 0.91
    tangent, bitangent = ring_basis(axis)
    rim = ring(location + depth * axis, tangent, bitangent, radius, segments)
    shell = []
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        center = location + (depth * fraction ** 2) * axis
        shell.extend(ring(center, tangent, bitangent, radius * fraction, segments))

    meshes = [Mesh(np.asarray(shell), band_faces(5, segments), SLATE, 0.56, two_sided=True)]
    meshes.extend(reflector_braces(location, axis, tangent, bitangent, radius, depth))
    for index, vertex in enumerate(rim):
        meshes.append(tube(vertex, rim[(index + 1) % segments], 0.072, PERIWINKLE, 0.91))

    feed = location + 3.05 * axis
    for index, beam_radius in ((1, 0.15), (12, 0.088), (23, 0.088)):
        meshes.append(tube(rim[index], feed, beam_radius, PERIWINKLE, 0.99, segments=6))
    return meshes, feed


def pine(x, y, height, spread, angle, ink, brightness):
    segments = 6
    tangent = np.array((cos(angle), sin(angle), 0))
    bitangent = np.array((-sin(angle), cos(angle), 0))
    vertices, faces = [], []
    for start, end, scale in ((0.11, 0.55, 1.00), (0.33, 0.71, 0.82),
                              (0.53, 0.86, 0.62), (0.70, 1.00, 0.40)):
        offset = len(vertices)
        vertices.extend(ring(np.array((x, y, start * height)), tangent, bitangent,
                             scale * spread, segments))
        vertices.extend(ring(np.array((x, y, (start + 0.09) * height)), tangent, bitangent,
                             scale * spread * 0.86, segments))
        vertices.append(np.array((x, y, end * height)))
        faces.extend(tuple(offset + index for index in face) for face in band_faces(2, segments))
        for index in range(segments):
            faces.append((offset + segments + index, offset + segments + (index + 1) % segments,
                          offset + 2 * segments))
    return Mesh(np.asarray(vertices), faces, ink, brightness)


def draw_forest(frame, camera):
    random = np.random.default_rng(44)
    layers = (
        (np.arange(-33, 34, 1.20), 21.0, (3.6, 6.6), GRAPE, (0.32, 0.48)),
        (np.arange(-24, 25, 1.03), 13.0, (2.9, 5.4), EVERGREEN, (0.58, 0.88)),
        (np.arange(-19, 20, 1.28), 7.5, (2.6, 4.9), GREEN, (0.30, 0.50)),
    )
    for positions, distance, heights, ink, tones in layers:
        for position in positions:
            x = position + random.uniform(-0.39, 0.39)
            y = distance + random.uniform(-1.22, 1.22)
            height = random.uniform(*heights)
            tree = pine(x, y, height, height * random.uniform(0.16, 0.24),
                        random.uniform(0, 2 * pi), ink, random.uniform(*tones))
            frame.draw_mesh(tree, camera)

    for x, y, height in ((-7.7, -0.4, 4.4), (-6.8, 1.2, 3.35), (9.3, 1.0, 4.1)):
        frame.draw_mesh(pine(x, y, height, height * 0.26, 0.4, EVERGREEN, 0.94), camera)


@lru_cache(maxsize=1)
def sky_stars(width, height):
    random = np.random.default_rng(6)
    centers = zip(random.uniform(22, width - 22, 50), random.uniform(20, height * 0.62, 50))
    return tuple((x, y, random.uniform(1.6, 4.0)) for x, y in centers)


def moon_geometry(frame):
    return (frame.width * 0.23, frame.height * 0.246), frame.height * 0.096


def draw_sky(frame):
    width, height = frame.width, frame.height
    frame.tone[:] = np.linspace(0.025, 0.106, height)[:, None]
    for x, y, radius in sky_stars(width, height):
        frame.disk((x, y), radius, PERIWINKLE, 0.69)

    moon, radius = moon_geometry(frame)
    frame.disk(moon, 1.16 * radius, GRAPE, 0.20)
    frame.disk(moon, radius, PERIWINKLE, 0.89)
    for x, y, size, tone in ((-0.37, 0.18, 0.30, 0.55), (0.24, -0.35, 0.24, 0.56),
                             (0.46, 0.28, 0.22, 0.65), (-0.29, -0.48, 0.16, 0.67),
                             (0.09, 0.44, 0.13, 0.70)):
        frame.disk((moon[0] + x * radius, moon[1] + y * radius), size * radius, PERIWINKLE, tone)


def draw_fence(frame, camera, start, end, posts, height):
    for center in np.linspace(start, end, posts):
        post = rectangular_block(center, 0, height, (0.17, 0.17), 0.93, ink=WOOD)
        frame.draw_mesh(post, camera)
    for rail_height in (0.36 * height, 0.74 * height):
        rail = tube((*start, rail_height), (*end, rail_height), 0.10, WOOD, 0.89, segments=4)
        frame.draw_mesh(rail, camera)


def draw_lamp_post(frame, camera):
    frame.add_lamplight(camera, LAMP_BULB, radius=3.55)
    x, y, z = LAMP_BULB
    meshes = (
        rectangular_block(LAMP_FOOT[:2], 0, LAMP_TOP[2], (0.19, 0.18), 0.99, (0.15, 0.15), ink=WOOD),
        tube(LAMP_TOP, (x, y, z + 0.15), 0.070, WOOD, 0.95, segments=4),
        rectangular_block((x, y), z + 0.09, z + 0.20, (0.31, 0.30), 0.94, ink=WOOD),
    )
    for mesh in meshes:
        frame.draw_mesh(mesh, camera)


def distant_beacon(frame, strength=1.0):
    center = (frame.width * 0.382, frame.height * 0.657)
    frame.disk(center, 12, PINK, 0.32 * strength)
    frame.disk(center, 6, PINK, 0.79 * strength)


@lru_cache(maxsize=1)
def clearing():
    columns, rows = GRID_SIZE
    sample_width, sample_height = SAMPLES_PER_CELL
    width, height = columns * sample_width, rows * sample_height
    frame = Frame(width, height)
    camera = Camera((0, -13.2, 2.48), (0.70, 1.8, 3.0), width, height, 35)
    draw_sky(frame)

    ground = Mesh(np.array(((-90, -8, 0), (90, -8, 0), (90, 70, 0), (-90, 70, 0))),
                  [(0, 1, 2), (0, 2, 3)], EVERGREEN, 0.22)
    frame.draw_mesh(ground, camera)
    draw_forest(frame, camera)
    distant_beacon(frame)
    for mesh in station_mount(STATION_CENTER):
        frame.draw_mesh(mesh, camera)
    draw_fence(frame, camera, (-5.55, -1.25), (-1.65, -0.90), posts=5, height=0.78)
    draw_fence(frame, camera, (0.84, -2.82), (4.98, -3.35), posts=5, height=0.67)
    draw_lamp_post(frame, camera)
    return frame, camera


def pulse(phase, cycles, offset=0):
    return 0.5 + 0.5 * cos(2 * pi * (cycles * phase + offset))


def twinkle_stars(frame, phase):
    for index, (x, y, radius) in enumerate(sky_stars(frame.width, frame.height)):
        if index % 4:
            continue
        sample_x, sample_y = round(x), round(y)
        if frame.depth[sample_y, sample_x] or not np.isclose(frame.tone[sample_y, sample_x], 0.69):
            continue
        brightness = 0.36 + 0.55 * pulse(phase, 2 + index % 3, index * 0.143)
        frame.disk((x, y), radius, PERIWINKLE, brightness)


def shade_moon(frame, phase):
    (x, y), radius = moon_geometry(frame)
    halo = 1.16 * radius
    left, right = int(x - halo), int(x + halo) + 1
    top, bottom = int(y - halo), int(y + halo) + 1
    yy, xx = np.ogrid[top:bottom, left:right]
    region = np.s_[top:bottom, left:right]
    lunar_disk = (xx - x) ** 2 + (yy - y) ** 2 <= halo ** 2
    visible = lunar_disk & (frame.depth[region] == 0)
    side_light = sin(2 * pi * phase) * (xx - x) / halo
    strength = 0.925 + 0.09 * pulse(phase, 1, 0.17) + 0.026 * side_light
    frame.tone[region][visible] *= np.broadcast_to(strength, visible.shape)[visible]


def glow_lamp(frame, camera, strength):
    frame.tone += 0.29 * (strength - 1) * frame.warmth
    frame.warmth *= strength
    (pixel,), _ = camera.project([LAMP_BULB])
    frame.disk(pixel, 10 + 3 * strength, AMBER, 0.29 * strength)
    frame.disk(pixel, 7, AMBER, min(1.0, 0.89 * strength + 0.11))


def draw_fireflies(frame, seconds):
    for start, duration, x, y in FIREFLY_FLASHES:
        life = (seconds - start) / duration
        if 0 < life < 1:
            brightness = sin(pi * life) ** 2
            if brightness > 0.30:
                center = (x * frame.width + 15 * life, y * frame.height - 12 * life)
                frame.disk(center, 3.0 + 2.0 * brightness, FIREFLY, 0.91 * brightness)


def render_scene(dish_direction=LOCKED_DIRECTION, phase=None):
    background, camera = clearing()
    frame = background.copy()
    feed_strength = lamp_strength = 1.0
    if phase is not None:
        phase %= 1
        twinkle_stars(frame, phase)
        shade_moon(frame, phase)
        distant_beacon(frame, 0.54 + 0.46 * pulse(phase, 3, 0.38))
        feed_strength = 0.67 + 0.33 * pulse(phase, 4, 0.14)
        lamp_strength = 0.91 + 0.18 * pulse(phase, 2, 0.20)
    glow_lamp(frame, camera, lamp_strength)
    location = np.array((*STATION_CENTER, PIVOT_HEIGHT))
    meshes, feed = dish(location, unit(np.asarray(dish_direction)))
    for mesh in meshes:
        frame.draw_mesh(mesh, camera)
    (feed_pixel,), _ = camera.project([feed])
    frame.disk(feed_pixel, 13, PINK, 0.28 * feed_strength)
    frame.disk(feed_pixel, 8, PINK, feed_strength)
    if phase is not None:
        draw_fireflies(frame, phase * LOOP_SECONDS)
    return frame


def choose_glyph(tone, ink_tile, ink, density):
    level = min(round(density * (len(GLYPHS) - 1)), len(GLYPHS) - 1)
    if ink == FIREFLY:
        return "*" if tone[ink_tile == ink].max() > 0.68 else "."
    if ink in (SLATE, PERIWINKLE, WOOD) and 0.12 < density < 0.62:
        mask = (ink_tile == ink) & (tone >= 0.76 * tone.max())
        y, x = np.nonzero(mask)
        if 5 <= x.size <= mask.size * 0.55:
            horizontal, vertical = x.std(), y.std()
            if horizontal > 2.3 * vertical:
                return "-"
            if vertical > 2.3 * horizontal:
                return "|"
            if horizontal and vertical:
                correlation = np.mean((x - x.mean()) * (y - y.mean())) / (horizontal * vertical)
                if abs(correlation) >= 0.67:
                    return "\\" if correlation > 0 else "/"
    return GLYPHS[level]


def ascii_image(frame, font_name):
    columns, rows = GRID_SIZE
    dw, dh = CELL_SIZE
    sw, sh = SAMPLES_PER_CELL
    font = ImageFont.truetype(font_name, 16)
    image = Image.new("RGB", (columns * dw, rows * dh), BACKGROUND)
    draw = ImageDraw.Draw(image)
    palette = np.array([(ImageColor.getrgb(shadow), ImageColor.getrgb(highlight))
                        for shadow, highlight, _ in INK_SHADES])
    shine = np.array([threshold for _, _, threshold in INK_SHADES])
    base = np.array(ImageColor.getrgb(BACKGROUND))
    haze = (palette[GRAPE, 1] - base) * 0.16
    for y in range(image.height):
        weight = max(0, 1 - abs(y / image.height - 0.51) * 2.0)
        color = tuple(np.rint(base + weight * haze).astype(int))
        draw.line((0, y, image.width - 1, y), fill=color)

    for row in range(rows):
        for column in range(columns):
            tile = np.s_[row * sh:(row + 1) * sh, column * sw:(column + 1) * sw]
            tone = frame.tone[tile]
            ink_tile = frame.ink[tile]
            ink_weights = np.bincount(ink_tile.ravel(), weights=tone.ravel(),
                                      minlength=len(INK_SHADES))
            ink = int(ink_weights.argmax())
            density = float(0.80 * tone.mean() + 0.20 * tone.max())
            if ink == GRAPE and density < 0.15:
                continue
            character = choose_glyph(tone, ink_tile, ink, density)
            material = ink_tile == ink
            shade = int(tone[material].mean() >= shine[ink])
            warmth = frame.warmth[tile][material].mean() * 0.79
            color = palette[ink, shade]
            fill = tuple(np.rint(color + warmth * (palette[AMBER, 1] - color)).astype(int))
            draw.text((column * dw, row * dh + dh - 2), character,
                      font=font, fill=fill, anchor="ls")
    return image


def sweep_direction(seconds):
    time = seconds % LOOP_SECONDS
    for previous, following in zip(SWEEP_KEYS, SWEEP_KEYS[1:]):
        start, start_yaw, start_pitch = previous
        end, end_yaw, end_pitch = following
        if time < end:
            progress = (time - start) / (end - start)
            ease = progress ** 2 * (3 - 2 * progress)
            yaw_offset = start_yaw + ease * (end_yaw - start_yaw)
            pitch_offset = start_pitch + ease * (end_pitch - start_pitch)
            x, y, z = LOCKED_DIRECTION
            yaw = atan2(y, x) + radians(yaw_offset)
            pitch = atan2(z, hypot(x, y)) + radians(pitch_offset)
            return cos(pitch) * cos(yaw), cos(pitch) * sin(yaw), sin(pitch)
    raise ValueError("The dish keyframes must cover the full loop.")


def animation_frame(seconds, font_name):
    scene = render_scene(sweep_direction(seconds), phase=seconds / LOOP_SECONDS)
    return ascii_image(scene, font_name)


def gif_palette(font_name):
    reference_times = (0, 3.9, 7.0, 9.0, 16.6)
    width, height = (cells * size for cells, size in zip(GRID_SIZE, CELL_SIZE))
    samples = Image.new("RGB", (width, height * len(reference_times)))
    for index, seconds in enumerate(reference_times):
        samples.paste(animation_frame(seconds, font_name), (0, index * height))

    # Keep the source swatches exact and use the remaining entries for antialiasing and lamplight.
    swatches = [ImageColor.getrgb(color) for pair in INK_SHADES for color in pair[:2]]
    swatches.append(ImageColor.getrgb(BACKGROUND))
    available = 255 - len(swatches)
    sampled = samples.quantize(colors=available, method=Image.Quantize.MEDIANCUT)
    palette = Image.new("P", (1, 1))
    palette.putpalette([channel for color in swatches for channel in color]
                       + sampled.getpalette()[:available * 3])
    return palette


def save_animation(path, font_name):
    palette = gif_palette(font_name)
    output_palette = bytes(palette.getpalette()) + bytes((0, 255, 255))
    total_frames = LOOP_SECONDS * FRAMES_PER_SECOND
    frames = (
        animation_frame(index / FRAMES_PER_SECOND, font_name).quantize(
            palette=palette, dither=Image.Dither.NONE,
        )
        for index in range(total_frames)
    )
    first = next(frames)
    first.save(path, save_all=True, append_images=frames, loop=0, disposal=1,
               duration=1000 // FRAMES_PER_SECOND, palette=output_palette,
               transparency=255, optimize=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Destination .png or .gif")
    parser.add_argument("--font", default="DejaVuSansMono.ttf", help="Monospace TTF name or path")
    args = parser.parse_args()
    suffix = args.output.suffix.lower()
    if suffix not in (".png", ".gif"):
        parser.error("The output filename must end in .png or .gif.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".gif":
        save_animation(args.output, args.font)
    else:
        ascii_image(render_scene(), args.font).save(args.output, optimize=True)


if __name__ == "__main__":
    main()
