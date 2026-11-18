"""Геометрия, свечение, сетка, фиш-ай, буфер обмена."""
import math
import sys
import pygame


def shape(pts, ang, pos, s):
    c, sn = math.cos(ang), math.sin(ang)
    return [(pos[0] + (x * c - y * sn) * s, pos[1] + (x * sn + y * c) * s) for x, y in pts]


def dim(c, k):
    k = max(0.0, min(1.0, k))
    return (int(c[0] * k), int(c[1] * k), int(c[2] * k))


def make_overlay(W, H):
    small = pygame.Surface((64, 36), pygame.SRCALPHA)
    for x in range(64):
        for y in range(36):
            d = min(1.6, math.hypot((x - 31.5) / 32, (y - 17.5) / 18))
            small.set_at((x, y), (0, 0, 0, int(min(255, 200 * (d / 1.3) ** 2.6))))
    ov = pygame.transform.smoothscale(small, (W, H)).convert_alpha()
    for y in range(0, H, 3):
        ov.fill((0, 0, 0, 24), pygame.Rect(0, y, W, 1), pygame.BLEND_RGBA_ADD)
    return ov


def bloom(src, W, H, strength=0.16):
    """Soft CRT bloom: bright pixels glow while silhouettes stay readable."""
    if strength <= 0:
        return
    small_size = (max(1, W // 6), max(1, H // 6))
    glow = pygame.transform.smoothscale(src, small_size)
    glow = pygame.transform.smoothscale(glow, (W, H))
    glow.set_alpha(max(1, min(255, int(255 * strength))))
    src.blit(glow, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

def fisheye(src, strength=0.35):
    """Радиальное искажение через сетку 40x24 — быстрый псевдо-fisheye."""
    if strength <= 0.01:
        return src
    W, H = src.get_size()
    out = pygame.Surface((W, H))
    nx, ny = 40, 24
    cxp, cyp = W / 2, H / 2
    maxr = math.hypot(cxp, cyp)
    # вершины UV-сетки в исходной поверхности
    uv = []
    for j in range(ny + 1):
        row = []
        for i in range(nx + 1):
            sx = i / nx * W
            sy = j / ny * H
            dx, dy = sx - cxp, sy - cyp
            r = math.hypot(dx, dy) / maxr
            k = 1 - strength * (r ** 2)
            ux = max(0, min(W - 1, cxp + dx * k))
            uy = max(0, min(H - 1, cyp + dy * k))
            row.append((ux, uy))
        uv.append(row)
    for j in range(ny):
        for i in range(nx):
            x0 = int(i / nx * W)
            x1 = int((i + 1) / nx * W)
            y0 = int(j / ny * H)
            y1 = int((j + 1) / ny * H)
            ux0 = int(uv[j][i][0])
            uy0 = int(uv[j][i][1])
            ux1 = int(uv[j][i + 1][0])
            uy1 = int(uv[j + 1][i][1])
            uw = max(2, ux1 - ux0)
            uh = max(2, uy1 - uy0)
            if uw <= 0 or uh <= 0 or x1 <= x0 or y1 <= y0:
                continue
            try:
                piece = src.subsurface(pygame.Rect(ux0, uy0, uw, uh)).copy()
                piece = pygame.transform.scale(piece, (x1 - x0, y1 - y0))
                out.blit(piece, (x0, y0))
            except Exception:
                pass
    return out


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
