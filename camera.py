"""Камера: следует за игроком, клампится к границам мира."""
import math


class Camera:
    def __init__(self, vw, vh, ww, wh):
        self.vw, self.vh = vw, vh
        self.ww, self.wh = ww, wh
        self.x = 0.0
        self.y = 0.0

    def follow(self, tx, ty, dt, snap=False):
        target_x = tx - self.vw / 2
        target_y = ty - self.vh / 2
        target_x = max(0, min(self.ww - self.vw, target_x))
        target_y = max(0, min(self.wh - self.vh, target_y))
        if snap:
            self.x, self.y = target_x, target_y
            return
        alpha = 1 - math.exp(-10 * dt)
        self.x += (target_x - self.x) * alpha
        self.y += (target_y - self.y) * alpha

    def to_screen(self, wx, wy):
        return wx - self.x, wy - self.y

    def to_world(self, sx, sy):
        return sx + self.x, sy + self.y