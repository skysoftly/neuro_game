# NEON VOID

NEON VOID is a fast top-down co-op arena shooter for 1-4 players. Host a session, invite friends by IP, survive increasingly dangerous waves, defeat bosses and build your loadout between rounds.

## Features

- LAN multiplayer over TCP
- Nine regular enemy archetypes with different movement and attack patterns
- Five boss encounters with distinct attack patterns
- Enemy health and pressure scale with wave number and party size
- One upgrade choice after each wave
- Boss rewards are generated separately for every living player
- Player-local damage feedback and score notifications
- Shared pause controlled by the host
- Animated CRT-inspired presentation, custom UI, sound effects and original chiptune soundtrack

## Run from source

Requires Python 3.10+ and Windows, Linux or macOS with a working Pygame display/audio environment.

```bash
python -m pip install -r requirements.txt
python main.py
```

## Build a Windows EXE

The easiest way is to double-click `build.bat` from the project folder.

It installs the build dependencies, creates the application icon and packages a standalone executable with PyInstaller. The result is:

```
dist/NEON VOID.exe
```

You can also run the commands manually:

```powershell
python -m pip install -r requirements.txt
python -m pip install pyinstaller pillow
python make_icon.py
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "NEON VOID" --icon "icon.ico" --add-data "icon.ico;." main.py
```

## Play with friends

1. All players should be on the same local network.
2. One player selects **Create lobby**.
3. The host shares the IP shown in the lobby.
4. Other players select **Connect by IP** and enter the host IP.
5. The host starts the game after everyone has joined.

The game uses TCP port **5555**. The host may need to allow the game through the operating system firewall. The port is fixed and does not need to be entered by players.

## Controls

| Action | Control |
|---|---|
| Move | WASD / Arrow keys |
| Aim | Mouse |
| Shoot | Left mouse button |
| Dash | Space / Left Shift |
| Shield | Right mouse button / E |
| Pause / resume | P / Escape (host) |
| Fullscreen | F11 |
| Debug overlay | F3 |

During the intermission, click one upgrade card. The next wave starts after all living players have chosen.

## Project layout

- `main.py` - application entry point
- `game.py` - game loop, simulation, rendering and lobby
- `entities.py` - player, enemy, projectile and effect entities
- `network.py` - TCP host/client transport
- `config.py` - arena dimensions, colors and enemy stats
- `upgrades.py` - upgrade definitions and stat recalculation
- `draw_utils.py`, `visuals.py`, `fonts.py` - rendering helpers
- `tests/` - automated gameplay and rendering tests

## Tests

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

Multiplayer should still be tested manually with two separate computers. Automated tests do not replace a real LAN session test.
