"""Cached additive glow helpers for the crisp neon/retro renderer."""
from functools import lru_cache

import pygame


@lru_cache(maxsize=96)
def _glow_image(color, radius, strength):
    radius = max(4, int(radius))
    strength = max(0, min(100, int(strength)))
    size = radius * 2
    image = pygame.Surface((size, size), pygame.SRCALPHA)
    cx = cy = radius - 0.5
    max_dist = float(radius)
    r, g, b = color
    for y in range(size):
        dy = (y - cy) / max_dist
        for x in range(size):
            dx = (x - cx) / max_dist
            d2 = dx * dx + dy * dy
            if d2 >= 1.0:
                continue
            falloff = (1.0 - d2) ** 2.2
            image.set_at((x, y), (
                int(r * falloff * strength / 100),
                int(g * falloff * strength / 100),
                int(b * falloff * strength / 100),
                255,
            ))
    return image


def draw_glow(target, position, color, radius=32, strength=35):
    """Draw a cached, soft additive halo without blurring the sprite itself."""
    radius = max(4, int(radius))
    key_color = tuple(max(0, min(255, int(c))) for c in color[:3])
    image = _glow_image(key_color, radius, int(strength))
    target.blit(
        image,
        (int(position[0] - radius), int(position[1] - radius)),
        special_flags=pygame.BLEND_RGB_ADD,
    )
