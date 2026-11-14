"""
PIXELBOX // Seed Sandbox (PromptCraft Final Round Starter)
==========================================================
Run with:
    python main.py
    (or: pyxel run main.py)

Controls currently wired up in this starter seed:
  - Arrow Keys / WASD : Move the bot around the arena
  - SPACE             : Dash / Emit shockwave pulse
  - Left Mouse Click  : Spawn a mystery crate or energy orb at cursor
  - Right Mouse Click : Detonate nearby crates into particles
  - G                 : Toggle Gravity Mode (Top-Down vs. Side-Scroller Physics!)
  - TAB               : Toggle Live Telemetry & 16-Color Palette Inspector
  - R                 : Reset sandbox state
  - ESC               : Quit

WHAT IS MISSING? (Your 90-Minute Challenge!)
--------------------------------------------
This codebase is an unfinished engine with physics, particles, procedural sprites,
and 8-bit audio—but NO game loop, NO win/loss condition, NO progression, and NO domain theme.
Prompt your way to turn this seed into a complete, polished project!
"""

from __future__ import annotations

import json
import math
import random
import sys

import pyxel

from assets import draw_sprite, init_assets, play_sfx
from engine import Camera, Entity, FloatingTextManager, ParticleSystem
from sectors import SECTORS

SCREEN_W = 160
SCREEN_H = 120
FLOOR_Y = 104

# --- FLIPSIDE tunables (Step 2) ---
DRONE_MAX_ALIVE = 3          # max drones at once (pending spawns count)
DRONE_SPAWN_INTERVAL = 60    # frames between spawn attempts
DRONE_SPAWN_WARN = 30        # frames the blinking "!" marker shows before a drone appears
DRONE_FREE_SPEED = 0.5       # chase speed in FREE (top-down) mode
DRONE_GRAV_WALK = 0.4        # walk speed once landed in GRAV mode
DRONE_GRAV_FALL = 0.25       # gravity accel for drones in GRAV mode
DRONE_GRAV_FALL_MAX = 3.5    # terminal fall speed for drones
PLAYER_INVULN_FRAMES = 45    # blinking invulnerability after a hit
KNOCKBACK_FRAMES = 10        # frames input is overridden after a hit
KNOCKBACK_SPEED = 3.0        # knockback impulse strength
ORB_RESPAWN_INTERVAL = 120   # frames between orb-respawn ticks
ORB_MIN_COUNT = 4            # respawn an orb when fewer than this exist

# --- FLIPSIDE tunables (Step 3) ---
CRATE_COST = 15              # NRG to place a crate (LMB)
FLIP_COST = 5                # NRG to flip gravity mode (G)
START_NRG = 20               # NRG at run start
MAX_CRATES = 6               # max crates in play; oldest is recycled
PLAYER_MAX_HP = 5            # heart pickup cap
SHOCK_RADIUS = 44            # shockwave push/stun radius
BLAST_RADIUS = 28            # detonation trigger + kill radius
STUN_FRAMES = 45             # shockwave stun duration
COMBO_WINDOW = 45            # frames between kills to keep the combo alive
COMBO_BONUS = 50             # bonus per extra kill in a combo
KILL_SCORE = 100             # score per drone kill
HEART_DROP_CHANCE = 0.15     # chance a kill also drops a heart


class PixelBoxSandbox:
    def __init__(self) -> None:
        # CLI flags: --smoke (auto-start PLAY, quit after 150 frames), --sector N (1-4, used later)
        args = sys.argv[1:]
        self.smoke = "--smoke" in args
        self.smoke_frames = 0
        self.start_sector = 1
        if "--sector" in args:
            idx = args.index("--sector")
            if idx + 1 < len(args):
                try:
                    self.start_sector = max(1, min(4, int(args[idx + 1])))
                except ValueError:
                    self.start_sector = 1

        # Hi-score persistence (loaded once per app launch)
        self.hiscore = 0
        try:
            with open("highscore.json") as f:
                self.hiscore = int(json.load(f).get("hiscore", 0))
        except (OSError, ValueError, AttributeError):
            self.hiscore = 0
        self.new_hi = False

        pyxel.init(SCREEN_W, SCREEN_H, title="PIXELBOX // SEED ENGINE", fps=30)
        init_assets()
        pyxel.mouse(False)  # We draw our own custom pixel crosshair cursor
        self.state = "TITLE"  # TITLE / PLAY / CLEAR / WIN / OVER
        self.reset()
        if self.smoke:
            self.start_run()
        pyxel.run(self.update, self.draw)

    def reset(self) -> None:
        """Reset sandbox actors and systems."""
        self.camera = Camera()
        self.particles = ParticleSystem()
        self.popups = FloatingTextManager()

        self.gravity_mode = False  # False = Top-Down Arena, True = Side-Scroller Gravity
        self.show_debug = False
        self.energy = START_NRG
        self.pulse_radius = 0.0

        # Drone system (Step 2)
        self.drones: list[Entity] = []
        self.pending_spawns: list[dict] = []  # {"x","y","timer"} blinking "!" markers
        self.drone_spawn_timer = DRONE_SPAWN_INTERVAL
        self.player_invuln = 0
        self.knockback_frames = 0
        self.score = 0
        self.orb_timer = ORB_RESPAWN_INTERVAL
        self.combo = 0
        self.combo_timer = 0

        self.player = Entity(
            x=SCREEN_W // 2 - 4,
            y=SCREEN_H // 2 - 4,
            sprite="bot_idle",
            tag="player",
            hp=3,
        )

        # Seed a few interactive objects in the arena so the screen feels alive on first boot
        self.items: list[Entity] = []
        for _ in range(5):
            self.spawn_orb(
                random.randint(16, SCREEN_W - 24),
                random.randint(20, FLOOR_Y - 12),
            )
        for i in range(3):
            self.spawn_crate(36 + i * 36, FLOOR_Y - 8)

        # Sector progression (P1)
        self.sector_index = max(0, min(len(SECTORS) - 1, self.start_sector - 1))
        self.kills = 0
        self.sector_banner = 60
        self.clear_timer = 0
        self.hitstop = 0
        self.flip_ring = 0

    def cur_sector(self) -> dict:
        return SECTORS[min(self.sector_index, len(SECTORS) - 1)]

    def _finish_run(self) -> None:
        """Record hi-score to highscore.json at run end."""
        self.new_hi = self.score > self.hiscore
        if self.new_hi:
            self.hiscore = self.score
        try:
            with open("highscore.json", "w") as f:
                json.dump({"hiscore": self.hiscore}, f)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Spawners (Extend or replace these with enemies, tools, towers, etc.)
    # ------------------------------------------------------------------
    def spawn_orb(self, x: float, y: float) -> None:
        self.items.append(Entity(x=x, y=y, sprite="orb", tag="orb"))

    def spawn_crate(self, x: float, y: float) -> None:
        self.items.append(Entity(x=x, y=y, sprite="crate", tag="crate", hp=2))

    def spawn_drone(self) -> None:
        """Schedule a drone at a random arena edge; a blinking "!" marks the spot."""
        edge = random.choice(("top", "bottom", "left", "right"))
        if edge == "top":
            x, y = random.randint(4, SCREEN_W - 12), 14
        elif edge == "bottom":
            x, y = random.randint(4, SCREEN_W - 12), FLOOR_Y - 8
        elif edge == "left":
            x, y = 4, random.randint(14, FLOOR_Y - 8)
        else:
            x, y = SCREEN_W - 12, random.randint(14, FLOOR_Y - 8)
        self.pending_spawns.append({"x": float(x), "y": float(y), "timer": DRONE_SPAWN_WARN})

    def spawn_heart(self, x: float, y: float) -> None:
        self.items.append(Entity(x=x, y=y, sprite="heart", tag="heart", hp=1))

    def kill_drone(self, drone: Entity) -> None:
        """Drone kill rewards: score, combo, burst, drops, shake, sfx."""
        kx, ky = drone.center()
        self.particles.burst(kx, ky, count=12, colors=[8, 9, 7])
        self.popups.spawn("+100", kx - 8, ky - 6, color=10)
        self.score += KILL_SCORE
        self.kills += 1
        self.hitstop = 3
        # Combo: kills within COMBO_WINDOW frames of each other chain up
        if self.combo_timer > 0:
            self.combo += 1
        else:
            self.combo = 1
        self.combo_timer = COMBO_WINDOW
        if self.combo >= 2:
            self.score += COMBO_BONUS
            self.popups.spawn(f"COMBO x{self.combo}", kx - 16, ky - 12, color=10)
        # Drops: every kill drops an orb; 15% also a heart
        self.spawn_orb(kx, ky)
        if random.random() < HEART_DROP_CHANCE:
            self.spawn_heart(kx, ky)
        self.camera.shake(6, 2)
        play_sfx("crush")

    def start_run(self) -> None:
        """Begin a fresh run and enter PLAY."""
        self.reset()
        self.state = "PLAY"
        play_sfx("blip")

    # ------------------------------------------------------------------
    # Frame Update Loop (30 FPS) — dispatches to _update_<state>
    # ------------------------------------------------------------------
    def update(self) -> None:
        if self.smoke:
            self.smoke_frames += 1
            if self.smoke_frames >= 150:
                pyxel.quit()
                return
        # ESC quits from any state
        if pyxel.btnp(pyxel.KEY_ESCAPE):
            pyxel.quit()
            return
        # R returns to TITLE from any non-TITLE state
        if self.state != "TITLE" and pyxel.btnp(pyxel.KEY_R):
            self.state = "TITLE"
            play_sfx("blip")
            return
        getattr(self, f"_update_{self.state.lower()}")()

    def _update_title(self) -> None:
        if (
            pyxel.btnp(pyxel.KEY_SPACE)
            or pyxel.btnp(pyxel.KEY_RETURN)
            or pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT)
        ):
            self.start_run()

    def _update_clear(self) -> None:
        self.particles.update(gravity=0.08)
        self.popups.update()
        self.camera.update()
        self.clear_timer -= 1
        if self.clear_timer <= 0:
            if self.sector_index >= len(SECTORS) - 1:
                self.state = "WIN"
                self._finish_run()
                play_sfx("win")
            else:
                self.sector_index += 1
                self.kills = 0
                self.sector_banner = 60
                self.state = "PLAY"

    def _update_win(self) -> None:
        if pyxel.btnp(pyxel.KEY_SPACE):
            self.state = "TITLE"
            play_sfx("blip")

    def _update_over(self) -> None:
        self.particles.update(gravity=0.08)
        self.popups.update()
        if pyxel.btnp(pyxel.KEY_SPACE):
            self.state = "TITLE"
            play_sfx("blip")

    # ------------------------------------------------------------------
    # PLAY state (moved sandbox loop, body unchanged)
    # ------------------------------------------------------------------
    def _update_play(self) -> None:
        if self.hitstop > 0:
            self.hitstop -= 1
            return
        if self.sector_banner > 0:
            self.sector_banner -= 1
        if pyxel.btnp(pyxel.KEY_TAB):
            self.show_debug = not self.show_debug
            play_sfx("blip")

        if pyxel.btnp(pyxel.KEY_R):
            self.reset()
            self.popups.spawn("RESET!", SCREEN_W // 2 - 12, 24, color=11)
            play_sfx("blip")
            return

        if pyxel.btnp(pyxel.KEY_G):
            if self.energy >= FLIP_COST:
                self.energy -= FLIP_COST
                self.gravity_mode = not self.gravity_mode
                self.flip_ring = 8
                mode_label = "GRAVITY: ON" if self.gravity_mode else "TOP-DOWN MODE"
                self.popups.spawn(mode_label, self.player.x - 16, self.player.y - 10, color=12)
                play_sfx("flip")
            else:
                self.popups.spawn("NEED NRG", self.player.x - 16, self.player.y - 10, color=8)
                play_sfx("blip")

        self._update_player_input()
        self._update_mouse_sandbox()
        self._update_entities()
        self._update_drones()

        # Combo window countdown
        if self.combo_timer > 0:
            self.combo_timer -= 1

        # Sector progression: enough kills -> CLEAR (90f), then next sector banner
        sec = self.cur_sector()
        if self.kills >= sec["kills_needed"]:
            self.state = "CLEAR"
            self.clear_timer = 90
            self.camera.flash(3, 7)
            for d in self.drones:
                kx, ky = d.center()
                self.particles.burst(kx, ky, count=10, colors=[8, 9, 7])
            self.drones = []
            self.pending_spawns = []
            self.popups.spawn("SECTOR CLEAR", (SCREEN_W - 12 * 4) // 2, 46, color=11)
            self.score += 100 * max(0, self.player.hp)
            play_sfx("clear")
            return

        # Flip ring lifetime
        if self.flip_ring > 0:
            self.flip_ring -= 1

        # Keep the arena stocked with orbs
        self.orb_timer -= 1
        if self.orb_timer <= 0:
            self.orb_timer = ORB_RESPAWN_INTERVAL
            if sum(1 for item in self.items if item.tag == "orb") < ORB_MIN_COUNT:
                self.spawn_orb(random.randint(16, SCREEN_W - 24), random.randint(20, FLOOR_Y - 12))

        # Death: out of HP -> OVER
        if self.player.hp <= 0:
            px, py = self.player.center()
            self.particles.burst(px, py, count=24, colors=[8, 9, 10, 7], speed=3.0)
            self.camera.shake(20, 4)
            play_sfx("boom")
            self._finish_run()
            play_sfx("lose")
            self.state = "OVER"
            return

        if self.pulse_radius > 0:
            self.pulse_radius += 4.5
            if self.pulse_radius > 42:
                self.pulse_radius = 0.0

        self.particles.update(gravity=0.08 if self.gravity_mode else 0.0)
        self.popups.update()
        self.camera.update()

    def _update_player_input(self) -> None:
        if self.knockback_frames > 0:
            # Knockback: physics-only motion, input resumes when it expires
            self.knockback_frames -= 1
            self.player.vx *= 0.90
            if self.gravity_mode:
                self.player.vy = min(self.player.vy + 0.35, 4.0)
            else:
                self.player.vy *= 0.90
            self.player.update()
            self.player.x = max(4.0, min(float(SCREEN_W - 12), self.player.x))
            self.player.y = max(14.0, min(float(FLOOR_Y - self.player.h), self.player.y))
            return

        speed = 2.0
        dx = 0.0
        dy = 0.0

        if pyxel.btn(pyxel.KEY_LEFT) or pyxel.btn(pyxel.KEY_A) or pyxel.btn(pyxel.GAMEPAD1_BUTTON_DPAD_LEFT):
            dx -= 1.0
            self.player.flip_x = True
        if pyxel.btn(pyxel.KEY_RIGHT) or pyxel.btn(pyxel.KEY_D) or pyxel.btn(pyxel.GAMEPAD1_BUTTON_DPAD_RIGHT):
            dx += 1.0
            self.player.flip_x = False

        if self.gravity_mode:
            # Side-scroller platformer physics
            self.player.vx = dx * speed
            self.player.vy = min(self.player.vy + 0.35, 4.0)
            on_ground = self.player.y >= FLOOR_Y - self.player.h
            if (
                pyxel.btnp(pyxel.KEY_UP)
                or pyxel.btnp(pyxel.KEY_W)
                or pyxel.btnp(pyxel.KEY_SPACE)
            ) and on_ground:
                self.player.vy = -4.2
                self.particles.burst(self.player.x + 4, self.player.y + 8, count=6, colors=[6, 7, 12])
                play_sfx("jump")
        else:
            # Top-down 8-way movement
            if pyxel.btn(pyxel.KEY_UP) or pyxel.btn(pyxel.KEY_W) or pyxel.btn(pyxel.GAMEPAD1_BUTTON_DPAD_UP):
                dy -= 1.0
            if pyxel.btn(pyxel.KEY_DOWN) or pyxel.btn(pyxel.KEY_S) or pyxel.btn(pyxel.GAMEPAD1_BUTTON_DPAD_DOWN):
                dy += 1.0
            if dx != 0.0 and dy != 0.0:
                dx *= 0.7071
                dy *= 0.7071
            self.player.vx = dx * speed
            self.player.vy = dy * speed

            # SPACE triggers a radial shockwave in top-down mode
            if pyxel.btnp(pyxel.KEY_SPACE):
                self.pulse_radius = 4.0
                self.camera.shake(frames=5, intensity=1.5)
                play_sfx("jump")
                px, py = self.player.center()
                for item in self.items:
                    ix, iy = item.center()
                    dist = math.hypot(ix - px, iy - py)
                    if 0 < dist < SHOCK_RADIUS:
                        item.vx = ((ix - px) / dist) * 3.0
                        item.vy = ((iy - py) / dist) * 3.0
                # Stun + push nearby drones
                for drone in self.drones:
                    dcx, dcy = drone.center()
                    dist = math.hypot(dcx - px, dcy - py)
                    if 0 < dist < SHOCK_RADIUS:
                        drone.data["stun"] = STUN_FRAMES
                        drone.vx = ((dcx - px) / dist) * 3.0
                        drone.vy = ((dcy - py) / dist) * 3.0

        self.player.update()

        # Keep player inside arena bounds
        self.player.x = max(4.0, min(float(SCREEN_W - 12), self.player.x))
        self.player.y = max(14.0, min(float(FLOOR_Y - self.player.h), self.player.y))

        # Animate player sprite when moving
        moving = abs(self.player.vx) > 0.1 or abs(self.player.vy) > 0.1
        self.player.sprite = "bot_run" if (moving and (pyxel.frame_count // 4) % 2 == 0) else "bot_idle"

    def _update_mouse_sandbox(self) -> None:
        mx, my = pyxel.mouse_x, pyxel.mouse_y

        # Left Click: place a crate at cursor (costs CRATE_COST NRG)
        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT):
            if self.energy >= CRATE_COST:
                self.energy -= CRATE_COST
                # Crate cap: recycle the oldest crate with a small puff
                crates = [it for it in self.items if it.tag == "crate"]
                if len(crates) >= MAX_CRATES:
                    oldest = crates[0]
                    ox, oy = oldest.center()
                    oldest.alive = False
                    self.particles.burst(ox, oy, count=6, colors=[6, 5, 7], speed=1.0)
                self.spawn_crate(mx - 4, my - 4)
                self.popups.spawn("CRATE", mx - 10, my - 6, color=9)
                self.particles.burst(mx, my, count=8, colors=[7, 10, 12], speed=1.2)
                play_sfx("blip")
            else:
                self.popups.spawn("NEED NRG", mx - 12, my - 6, color=8)
                play_sfx("blip")

        # Right Click: detonate the crate nearest the cursor (within BLAST_RADIUS)
        if pyxel.btnp(pyxel.MOUSE_BUTTON_RIGHT):
            target = None
            best = float(BLAST_RADIUS)
            for item in self.items:
                if item.tag == "crate":
                    ix, iy = item.center()
                    d = math.hypot(ix - mx, iy - my)
                    if d < best:
                        best = d
                        target = item
            if target is not None:
                bx, by = target.center()
                target.alive = False
                self.popups.spawn("BOOM!", bx - 8, by - 4, color=8)
                self.camera.shake(frames=8, intensity=2.5)
                self.particles.burst(bx, by, count=18, colors=[8, 9, 10, 7], speed=2.4)
                play_sfx("boom")
                for drone in self.drones:
                    dcx, dcy = drone.center()
                    if math.hypot(dcx - bx, dcy - by) < BLAST_RADIUS:
                        drone.alive = False
                        self.kill_drone(drone)

    def _update_entities(self) -> None:
        remaining: list[Entity] = []
        for item in self.items:
            if self.gravity_mode and item.tag == "crate":
                item.vy = min(item.vy + 0.25, 3.5)

            item.update()
            # Apply gentle friction
            item.vx *= 0.85
            if not self.gravity_mode:
                item.vy *= 0.85

            # Keep inside arena walls
            if item.x < 4 or item.x > SCREEN_W - 12:
                item.vx *= -1
                item.x = max(4.0, min(float(SCREEN_W - 12), item.x))
            if item.y < 14 or item.y > FLOOR_Y - item.h:
                if self.gravity_mode and item.y >= FLOOR_Y - item.h:
                    item.vy = 0.0
                else:
                    item.vy *= -1
                item.y = max(14.0, min(float(FLOOR_Y - item.h), item.y))

            # Check player collision with orbs
            if item.tag == "orb" and self.player.intersects(item):
                item.alive = False
                self.energy += 10
                self.particles.burst(item.x + 4, item.y + 4, count=10, colors=[10, 9, 7])
                self.popups.spawn("+10 NRG", item.x - 8, item.y - 4, color=10)
                play_sfx("pickup")

            # Check player collision with hearts (+1 HP, max 5)
            if item.tag == "heart" and self.player.intersects(item):
                item.alive = False
                self.player.hp = min(self.player.hp + 1, PLAYER_MAX_HP)
                self.particles.burst(item.x + 4, item.y + 4, count=10, colors=[8, 9, 7])
                self.popups.spawn("+1 HP", item.x - 8, item.y - 4, color=8)
                play_sfx("pickup")

            if item.alive:
                remaining.append(item)

        self.items = remaining

    def _update_drones(self) -> None:
        """Drone AI + pending spawn markers + player contact damage."""
        # Expire pending spawn markers and materialize drones
        still_pending: list[dict] = []
        for pend in self.pending_spawns:
            pend["timer"] -= 1
            if pend["timer"] <= 0:
                self.drones.append(
                    Entity(x=pend["x"], y=pend["y"], sprite="drone", tag="drone", hp=1)
                )
            else:
                still_pending.append(pend)
        self.pending_spawns = still_pending

        # Spawn scheduler (pending markers count toward sector max_alive; paused during banner)
        sec = self.cur_sector()
        self.drone_spawn_timer -= 1
        if self.drone_spawn_timer <= 0:
            self.drone_spawn_timer = sec["spawn_interval"]
            if self.sector_banner <= 0 and len(self.drones) + len(self.pending_spawns) < sec["max_alive"]:
                self.spawn_drone()

        spd = sec["drone_speed"]
        walk = DRONE_GRAV_WALK * spd / DRONE_FREE_SPEED
        pcx, pcy = self.player.center()
        alive_drones: list[Entity] = []
        for drone in self.drones:
            stun = drone.data.get("stun", 0)
            if stun > 0:
                # Stunned: no steering; shockwave impulse decays with friction
                drone.data["stun"] = stun - 1
                drone.vx *= 0.85
                drone.vy *= 0.85
            elif self.gravity_mode:
                drone.vy = min(drone.vy + DRONE_GRAV_FALL, DRONE_GRAV_FALL_MAX)
                if drone.y >= FLOOR_Y - drone.h:
                    # Landed: walk toward the player
                    dx = pcx - (drone.x + drone.w / 2)
                    drone.vx = walk if dx > 0 else (-walk if dx < 0 else 0.0)
                else:
                    drone.vx = 0.0
            else:
                # Hover-chase
                dx = pcx - (drone.x + drone.w / 2)
                dy = pcy - (drone.y + drone.h / 2)
                dist = math.hypot(dx, dy)
                if dist > 0.0001:  # zero-length guard
                    drone.vx = (dx / dist) * spd
                    drone.vy = (dy / dist) * spd
                else:
                    drone.vx = 0.0
                    drone.vy = 0.0
            drone.update()

            # Keep inside arena bounds
            drone.x = max(4.0, min(float(SCREEN_W - 12), drone.x))
            drone.y = max(14.0, min(float(FLOOR_Y - drone.h), drone.y))
            if self.gravity_mode and drone.y >= FLOOR_Y - drone.h:
                drone.vy = 0.0

            # A falling crate (vy > 1.0) overlapping a drone crushes it
            if drone.alive:
                for crate in self.items:
                    if crate.tag == "crate" and crate.vy > 1.0 and crate.intersects(drone):
                        drone.alive = False
                        self.kill_drone(drone)
                        break

            if drone.alive:
                alive_drones.append(drone)
        self.drones = alive_drones

        # Player contact damage (blinking invulnerability + knockback)
        if self.player_invuln > 0:
            self.player_invuln -= 1
        else:
            for drone in self.drones:
                if self.player.intersects(drone):
                    self.player.hp -= 1
                    self.player_invuln = PLAYER_INVULN_FRAMES
                    self.knockback_frames = KNOCKBACK_FRAMES
                    self.hitstop = 3
                    px, py = self.player.center()
                    dcx, dcy = drone.center()
                    kdx, kdy = px - dcx, py - dcy
                    kdist = math.hypot(kdx, kdy)
                    if kdist < 0.0001:  # zero-length guard: push straight up
                        kdx, kdy, kdist = 0.0, -1.0, 1.0
                    self.player.vx = (kdx / kdist) * KNOCKBACK_SPEED
                    self.player.vy = (kdy / kdist) * KNOCKBACK_SPEED
                    self.camera.shake(8, 3)
                    self.camera.flash(2, 8)
                    self.popups.spawn("-1", self.player.x - 4, self.player.y - 8, color=8)
                    play_sfx("hurt")
                    break

    # ------------------------------------------------------------------
    # Frame Render Loop — dispatches to _draw_<state>
    # ------------------------------------------------------------------
    def draw(self) -> None:
        getattr(self, f"_draw_{self.state.lower()}")()

    def _draw_title(self) -> None:
        pyxel.cls(1)
        title = "FLIPSIDE"
        tx = (SCREEN_W - len(title) * 4) // 2
        pyxel.text(tx + 1, 37 + 1, title, 0)  # 1px shadow: draw twice
        pyxel.text(tx, 37, title, 12)
        subtitle = "REPAIR BOT // CORRUPTED MACHINE"
        sx = (SCREEN_W - len(subtitle) * 4) // 2
        pyxel.text(sx, 54, subtitle, 6)
        if (pyxel.frame_count // 20) % 2 == 0:
            prompt = "PRESS SPACE"
            px = (SCREEN_W - len(prompt) * 4) // 2
            pyxel.text(px, 82, prompt, 10)

    def _draw_clear(self) -> None:
        pyxel.cls(1)
        self.particles.draw()
        self.popups.draw()
        s = "SECTOR CLEAR"
        sx = (SCREEN_W - len(s) * 4) // 2
        pyxel.text(sx + 1, 40 + 1, s, 0)
        pyxel.text(sx, 40, s, 11)
        sc = f"SCORE {self.score}"
        pyxel.text((SCREEN_W - len(sc) * 4) // 2, 56, sc, 10)

    def _draw_win(self) -> None:
        pyxel.cls(1)
        s = "SYSTEM RESTORED"
        sx = (SCREEN_W - len(s) * 4) // 2
        pyxel.text(sx + 1, 34 + 1, s, 0)
        pyxel.text(sx, 34, s, 11)
        sc = f"SCORE {self.score}"
        pyxel.text((SCREEN_W - len(sc) * 4) // 2, 52, sc, 10)
        hi = f"HI {self.hiscore}"
        pyxel.text((SCREEN_W - len(hi) * 4) // 2, 62, hi, 9)
        if self.new_hi and (pyxel.frame_count // 10) % 2 == 0:
            ns = "NEW HI-SCORE!"
            pyxel.text((SCREEN_W - len(ns) * 4) // 2, 74, ns, 9)
        if (pyxel.frame_count // 20) % 2 == 0:
            p = "PRESS SPACE"
            pyxel.text((SCREEN_W - len(p) * 4) // 2, 90, p, 7)

    def _draw_over(self) -> None:
        pyxel.cls(1)
        self.particles.draw()
        self.popups.draw()
        s = "SYSTEM FAILURE"
        sx = (SCREEN_W - len(s) * 4) // 2
        pyxel.text(sx + 1, 37 + 1, s, 0)  # 1px shadow
        pyxel.text(sx, 37, s, 8)
        score_s = f"SCORE {self.score}  HI {self.hiscore}"
        pyxel.text((SCREEN_W - len(score_s) * 4) // 2, 56, score_s, 10)
        if self.new_hi and (pyxel.frame_count // 10) % 2 == 0:
            ns = "NEW HI-SCORE!"
            pyxel.text((SCREEN_W - len(ns) * 4) // 2, 66, ns, 9)
        if (pyxel.frame_count // 20) % 2 == 0:
            p = "PRESS SPACE"
            pyxel.text((SCREEN_W - len(p) * 4) // 2, 78, p, 7)

    # ------------------------------------------------------------------
    # PLAY state (moved sandbox render, body unchanged)
    # ------------------------------------------------------------------
    def _draw_play(self) -> None:
        if self.camera.flash_frames > 0:
            pyxel.cls(self.camera.flash_color)
            return

        pyxel.cls(1)  # Deep navy background
        cam_x, cam_y = self.camera.get_offset()

        # Draw subtle background grid
        for gx in range(0, SCREEN_W, 16):
            pyxel.line(int(gx - cam_x), 12, int(gx - cam_x), FLOOR_Y, 5 if gx % 32 == 0 else 1)
        for gy in range(16, FLOOR_Y + 1, 16):
            pyxel.line(0, int(gy - cam_y), SCREEN_W, int(gy - cam_y), 5 if gy % 32 == 0 else 1)

        # Arena border & floor line
        pyxel.rectb(2, 12, SCREEN_W - 4, FLOOR_Y - 10, 12)
        if self.gravity_mode:
            pyxel.rect(2, FLOOR_Y, SCREEN_W - 4, 4, 3)

        # Draw shockwave ring if active
        if self.pulse_radius > 0:
            px, py = self.player.center()
            pyxel.circb(int(px - cam_x), int(py - cam_y), int(self.pulse_radius), 12)

        # Expanding ring on flip (8 frames)
        if self.flip_ring > 0:
            fcx, fcy = self.player.center()
            pyxel.circb(int(fcx - cam_x), int(fcy - cam_y), (8 - self.flip_ring) * 4 + 4, 12)

        # Draw items (with gentle bobbing on orbs)
        for item in self.items:
            if item.tag == "orb":
                bob = math.sin((pyxel.frame_count + item.x) * 0.15) * 1.5
                draw_sprite(item.sprite, item.x - cam_x, item.y + bob - cam_y)
            else:
                item.draw(cam_x, cam_y)

        # Pending drone spawn markers (blinking "!")
        for pend in self.pending_spawns:
            if (pyxel.frame_count // 4) % 2 == 0:
                pyxel.text(int(pend["x"]) + 2, int(pend["y"]), "!", 8)

        # Draw drones (stunned drones flash white on alternate frames)
        for drone in self.drones:
            if drone.data.get("stun", 0) > 0 and (pyxel.frame_count // 2) % 2 == 0:
                pyxel.pal(8, 7)
                pyxel.pal(0xE, 7)
            drone.draw(cam_x, cam_y)
            pyxel.pal()  # reset palette remap

        # Draw player (blinks while invulnerable after a hit)
        if self.player_invuln <= 0 or (pyxel.frame_count // 2) % 2 == 0:
            self.player.draw(cam_x, cam_y)

        # Draw particles & floating labels
        self.particles.draw(cam_x, cam_y)
        self.popups.draw(cam_x, cam_y)

        # Top HUD Bar
        pyxel.rect(0, 0, SCREEN_W, 11, 0)
        for i in range(self.player.hp):
            draw_sprite("heart", 4 + i * 9, 2)
        pyxel.text(36, 3, f"NRG:{self.energy:03d}", 10)
        mode_tag = "GRAV" if self.gravity_mode else "FREE"
        pyxel.text(78, 3, f"[{mode_tag}]", 12)
        pyxel.text(114, 3, f"SCORE:{self.score}", 6)

        # Bottom bar: sector progress + controls
        pyxel.rect(0, SCREEN_H - 11, SCREEN_W, 11, 0)
        sec = self.cur_sector()
        pyxel.text(4, SCREEN_H - 8, f"S{self.sector_index + 1}/{len(SECTORS)} KILL {self.kills}/{sec['kills_needed']}", 6)
        pyxel.text(64, SCREEN_H - 8, "L:CRATE R:BOOM G:FLIP", 6)

        # Sector banner (spawning paused while visible)
        if self.sector_banner > 0:
            banner = f"SECTOR {self.sector_index + 1}: {self.cur_sector()['name']}"
            bx = (SCREEN_W - len(banner) * 4) // 2
            pyxel.text(bx + 1, 41, banner, 0)
            pyxel.text(bx, 40, banner, 12)

        # Optional Debug & Palette Inspector Overlay (Toggle with TAB)
        if self.show_debug:
            self._draw_debug_overlay()

        # Ghost crate preview at cursor while affordable
        if self.energy >= CRATE_COST:
            pyxel.dither(0.5)
            draw_sprite("crate", pyxel.mouse_x - 4, pyxel.mouse_y - 4)
            pyxel.dither(1.0)

        # Custom pixel cursor on top of everything
        draw_sprite("cursor", pyxel.mouse_x - 4, pyxel.mouse_y - 4)

    def _draw_debug_overlay(self) -> None:
        pyxel.rect(10, 18, SCREEN_W - 20, 76, 0)
        pyxel.rectb(10, 18, SCREEN_W - 20, 76, 7)
        pyxel.text(16, 23, "SEED TELEMETRY & PALETTE", 11)
        pyxel.text(16, 33, f"ENTITIES: {len(self.items)}  PARTICLES: {len(self.particles.particles)}", 7)
        pyxel.text(16, 41, f"PLAYER: ({int(self.player.x)}, {int(self.player.y)})", 7)
        pyxel.text(16, 49, f"MOUSE : ({pyxel.mouse_x}, {pyxel.mouse_y})", 7)
        pyxel.text(16, 59, "PYXEL COLORS (0-F):", 6)
        for col in range(16):
            cx = 16 + col * 8
            pyxel.rect(cx, 67, 7, 10, col)
            pyxel.text(cx + 2, 79, f"{col:x}", 7 if col != 7 else 1)


if __name__ == "__main__":
    PixelBoxSandbox()
