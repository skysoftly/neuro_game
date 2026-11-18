"""Шрифты с поддержкой кириллицы + текст с обводкой."""
import os
import pygame

_FONT_CACHE = {}


def _find_font():
    for name in ("dejavusans", "liberationsans", "freesans", "notosans",
                 "arialunicodems", "arial", "verdana", "tahoma", "segoeui"):
        try:
            p = pygame.font.match_font(name)
        except Exception:
            p = None
        if p and os.path.exists(p):
            return p
    return None


def font(size, bold=True):
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    path = _find_font()
    if path:
        f = pygame.font.Font(path, size)
        try:
            f.set_bold(bold)
        except Exception:
            pass
    else:
        f = pygame.font.SysFont(None, size, bold=bold)
    _FONT_CACHE[key] = f
    return f


def text(surf, s, f, col, pos, anchor="center", outline=1):
    base = f.render(s, True, col)
    rect = base.get_rect(**{anchor: (int(pos[0]), int(pos[1]))})
    if outline > 0:
        out = f.render(s, True, (0, 0, 0))
        for dx, dy in ((-outline, 0), (outline, 0), (0, -outline), (0, outline)):
            surf.blit(out, rect.move(dx, dy))
    surf.blit(base, rect)