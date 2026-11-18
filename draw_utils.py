"""Геометрия, свечение, сетка, фиш-ай, буфер обмена."""
import math
import random
import sys
import pygame


def shape(pts, ang, pos, s):
    c, sn = math.cos(ang), math.sin(ang)
    return [(pos[0] + (x * c - y * sn) * s, pos[1] + (x * sn + y * c) * s) for x, y in pts]


def dim(c, k):
    k = max(0.0, min(1.0, k))
    return (int(c[0] * k), int(c[1] * k), int(c[2] * k))


def make_overlay(W, H):
    """Subtle CRT glass: vignette, fine scanlines and sparse dust."""
    small = pygame.Surface((64, 36), pygame.SRCALPHA)
    for x in range(64):
        for y in range(36):
            d = min(1.6, math.hypot((x - 31.5) / 32, (y - 17.5) / 18))
            alpha = int(min(255, 150 * (d / 1.3) ** 2.4))
            small.set_at((x, y), (0, 0, 0, alpha))
    ov = pygame.transform.smoothscale(small, (W, H)).convert_alpha()
    for y in range(0, H, 3):
        ov.fill((0, 0, 0, 18), pygame.Rect(0, y, W, 1))
    for _ in range((W * H) // 18000):
        x, y = random.randrange(W), random.randrange(H)
        alpha = random.randrange(5, 15)
        ov.set_at((x, y), (120, 150, 190, alpha))
    for _ in range(8):
        x, y = random.randrange(W), random.randrange(H)
        pygame.draw.line(ov, (120, 150, 180, 12), (x, y), (x + 18, y + 1), 1)
    return ov

def bloom(src, W, H, strength=0.22):
    """Bloom only bright pixels, leaving text and silhouettes mostly crisp."""
    if strength <= 0:
        return
    sw, sh = max(1, W // 6), max(1, H // 6)
    glow = pygame.transform.smoothscale(src, (sw, sh))
    for y in range(sh):
        for x in range(sw):
            r, g, b, *_ = glow.get_at((x, y))
            peak = max(r, g, b)
            if peak < 82:
                glow.set_at((x, y), (0, 0, 0, 255))
            else:
                scale = min(1.0, (peak - 55) / 150.0)
                glow.set_at((x, y), (int(r * scale), int(g * scale), int(b * scale), 255))
    glow = pygame.transform.smoothscale(glow, (W, H))
    glow.set_alpha(max(1, min(255, int(255 * strength))))
    src.blit(glow, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

def fisheye(src, strength=0.075):
    """Very mild lens curvature, processed at half resolution."""
    if strength <= 0.001:
        return src
    W, H = src.get_size()
    ww, wh = max(2, W // 2), max(2, H // 2)
    work = pygame.transform.smoothscale(src, (ww, wh))
    out = pygame.Surface((ww, wh))
    nx, ny = 24, 14
    cx, cy = ww / 2, wh / 2
    maxr = math.hypot(cx, cy)
    uv = []
    for j in range(ny + 1):
        row = []
        for i in range(nx + 1):
            px, py = i / nx * ww, j / ny * wh
            dx, dy = px - cx, py - cy
            r = math.hypot(dx, dy) / maxr
            k = 1 - strength * r * r
            row.append((max(0, min(ww - 1, cx + dx * k)),
                        max(0, min(wh - 1, cy + dy * k))))
        uv.append(row)
    for j in range(ny):
        for i in range(nx):
            x0, x1 = int(i / nx * ww), int((i + 1) / nx * ww)
            y0, y1 = int(j / ny * wh), int((j + 1) / ny * wh)
            ux0, uy0 = map(int, uv[j][i])
            ux1, uy1 = int(uv[j][i + 1][0]), int(uv[j + 1][i][1])
            sw, sh = min(max(1, ux1 - ux0), ww - ux0), min(max(1, uy1 - uy0), wh - uy0)
            if x1 > x0 and y1 > y0 and sw > 0 and sh > 0:
                tile = work.subsurface((ux0, uy0, sw, sh))
                out.blit(pygame.transform.scale(tile, (x1 - x0, y1 - y0)), (x0, y0))
    return pygame.transform.smoothscale(out, (W, H))

def read_clipboard():
    """Read Unicode text from the Windows clipboard, with a tkinter fallback."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            user32.OpenClipboard.argtypes = [wintypes.HWND]
            user32.OpenClipboard.restype = wintypes.BOOL
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = wintypes.BOOL
            user32.GetClipboardData.argtypes = [wintypes.UINT]
            user32.GetClipboardData.restype = wintypes.HANDLE
            kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalLock.restype = wintypes.LPVOID
            kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalUnlock.restype = wintypes.BOOL

            if user32.OpenClipboard(None):
                try:
                    handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
                    if handle:
                        pointer = kernel32.GlobalLock(handle)
                        if pointer:
                            try:
                                return ctypes.wstring_at(pointer).strip()
                            finally:
                                kernel32.GlobalUnlock(handle)
                finally:
                    user32.CloseClipboard()
        except Exception:
            pass

    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        try:
            value = root.clipboard_get()
            return value.strip() if value else ""
        finally:
            root.destroy()
    except Exception:
        return ""
