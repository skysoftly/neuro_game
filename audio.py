"""Процедурный звук и музыкальные темы игры."""
import array
import logging
import math
import random

import pygame

log = logging.getLogger("neuro_game")


class Audio:
    def __init__(self):
        self.s = {}
        self.ok = False
        if not pygame.mixer.get_init():
            return
        try:
            # Softer, more varied synth tones; avoid harsh square-wave blasts.
            self.s = {
                "shoot": [
                    self.make(760, 520, 0.055, 0.035, "tri", 0.0),
                    self.make(820, 560, 0.050, 0.030, "sin", 0.0),
                    self.make(690, 470, 0.060, 0.032, "tri", 0.0),
                ],
                "hit": [
                    self.make(260, 170, 0.075, 0.055, "sin", 0.08),
                    self.make(310, 190, 0.065, 0.045, "tri", 0.04),
                ],
                "boom": [
                    self.make(115, 42, 0.24, 0.10, "sin", 0.12),
                    self.make(95, 35, 0.28, 0.085, "sin", 0.08),
                    self.make(135, 48, 0.20, 0.09, "tri", 0.06),
                ],
                "dash": [
                    self.make(260, 920, 0.19, 0.065, "sin", 0.0),
                    self.make(310, 1080, 0.16, 0.055, "tri", 0.0),
                ],
                "pickup": [
                    self.make(520, 1040, 0.16, 0.055, "tri", 0.0),
                    self.make(620, 1240, 0.14, 0.050, "sin", 0.0),
                ],
                "pulse": self.make(520, 90, 0.42, 0.12, "sin", 0.04),
                "hurt": self.make(220, 85, 0.20, 0.10, "tri", 0.05),
                "ui_click": self.make(520, 390, 0.045, 0.025, "sin", 0.0),
                "ui_hover": self.make(620, 700, 0.035, 0.008, "sin", 0.0),
                "ready": self.make(440, 990, 0.24, 0.06, "sin", 0.0),
                "boss_spawn": self.make(92, 38, 0.95, 0.15, "sin", 0.08),
                "boss_hit": [self.make(190, 82, 0.12, 0.075, "tri", 0.04),
                             self.make(145, 62, 0.16, 0.085, "sin", 0.06)],
                "enemy_shot": self.make(440, 260, 0.09, 0.028, "tri", 0.0),
                "boss_death": self.make(180, 28, 0.85, 0.13, "sin", 0.10),
                "heal": self.make(420, 1120, 0.34, 0.10, "sin", 0.0),
                "wave_start": self.make(180, 760, 0.72, 0.11, "tri", 0.03),
                "wave_clear": self.make(620, 980, 0.46, 0.075, "sin", 0.0),
                "scene": self.make(330, 660, 0.20, 0.045, "sin", 0.0),
                "shield_block": self.make(760, 420, 0.12, 0.075, "sin", 0.0),
                "armor_block": self.make(330, 720, 0.16, 0.07, "tri", 0.0),
                "player_death": self.make(210, 42, 0.72, 0.13, "sin", 0.10),
            }
            self.ok = True
            self.sfx_volume = 0.75
            self.music_volume = 0.12
            self.music_tracks = {
                "menu": self.make_music("menu"),
                "game": self.make_music("game"),
                "dead": self.make_music("dead"),
            }
            self.music_channel = pygame.mixer.Channel(7)
            self.music_mode = None
            self.music_channel.set_volume(self.music_volume)
            self.set_scene("menu")
        except Exception:
            self.ok = False
            log.exception("Не удалось инициализировать аудио")

    @staticmethod
    def make_music(mode="game"):
        """Generate three distinct, loopable original chiptune themes."""
        rate = 44100
        patterns = {
            "menu": ((392, 0, 494, 587, 659, 0, 587, 494, 440, 0, 392, 494, 587, 0, 494, 392,
                      330, 392, 494, 0, 440, 494, 587, 659, 784, 0, 659, 587, 494, 440, 392, 0),
                     (98, 98, 82.4, 82.4, 73.4, 73.4, 87.3, 87.3), 0.30, False),
            "game": ((523, 0, 440, 523, 659, 0, 523, 440,
                     494, 0, 392, 494, 587, 0, 494, 392,
                     440, 523, 659, 0, 698, 659, 523, 440,
                     392, 0, 440, 523, 494, 440, 392, 0),
                    (73.4, 73.4, 98, 98, 65.4, 65.4, 82.4, 82.4), 0.18, False),
            "dead": ((392, 349, 330, 294, 262, 0, 220, 196,
                     174, 0, 147, 131, 110, 0, 98, 82),
                    (65.4, 58.3, 55.0, 49.0), 0.30, False),
        }
        melody, bass, beat, drums = patterns.get(mode, patterns["game"])
        count = int(rate * beat)
        buf = array.array("h")
        for step, note in enumerate(melody):
            lead_phase = bass_phase = 0.0
            for i in range(count):
                t = i / count
                bass_phase += bass[(step // 4) % len(bass)] / rate
                env = min(1.0, i / 900) * min(1.0, (count - i) / 2600)
                low = math.sin(bass_phase * math.tau) * env * (0.045 if mode == "menu" else 0.06)
                lead = 0.0
                if note:
                    lead_phase += note / rate
                    tri = 1.0 - 4.0 * abs(round(lead_phase) - lead_phase)
                    lead_env = min(1.0, i / 700) * min(1.0, (count - i) / 2100)
                    lead = tri * lead_env * (0.032 if mode == "dead" else 0.045)
                kick = snare = hat = 0.0
                if drums:
                    kick = math.sin((72 - 42 * t) * math.tau * i / rate) * math.exp(-t * 18) * 0.13 if step % 4 == 0 else 0.0
                    snare = random.uniform(-1, 1) * math.exp(-t * 24) * 0.04 if step % 8 == 4 else 0.0
                    hat = random.uniform(-1, 1) * math.exp(-t * 38) * 0.016 if step % 2 else 0.0
                sample = max(-0.9, min(0.9, lead + low + kick + snare + hat))
                buf.append(int(sample * 32767))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def set_volumes(self, music=None, sfx=None):
        if music is not None:
            self.music_volume = max(0.0, min(1.0, float(music)))
            if self.ok:
                self.music_channel.set_volume(self.music_volume)
        if sfx is not None:
            self.sfx_volume = max(0.0, min(1.0, float(sfx)))

    def set_scene(self, scene):
        if not self.ok:
            return
        mode = "dead" if scene == "dead" else "game" if scene == "play" else "menu"
        if mode == self.music_mode:
            return
        self.music_mode = mode
        self.music_channel.stop()
        self.music_channel.set_volume(self.music_volume * (0.34 if mode == "game" else 1.0))
        self.music_channel.play(self.music_tracks[mode], loops=0 if mode == "dead" else -1)

    @staticmethod
    def make(f0, f1, dur, vol, wave, noise):
        rate = 44100
        n = max(1, int(rate * dur))
        buf = array.array("h")
        phase = 0.0
        for i in range(n):
            t = i / n
            phase += (f0 + (f1 - f0) * t) / rate
            if wave == "sq":
                sample = 1.0 if phase % 1.0 < 0.5 else -1.0
            elif wave == "tri":
                sample = 1.0 - 4.0 * abs(round(phase) - phase)
            else:
                sample = math.sin(phase * math.tau)
            sample = sample * (1 - noise) + random.uniform(-1, 1) * noise
            envelope = min(1.0, i / max(1, int(rate * 0.008))) * (1 - t) ** 1.6
            buf.append(int(sample * envelope * vol * 32767))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def play(self, name):
        if self.ok and name in self.s:
            sound = self.s[name]
            if isinstance(sound, list):
                sound = random.choice(sound)
            sound.set_volume(self.sfx_volume)
            sound.play()
