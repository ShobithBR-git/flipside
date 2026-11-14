ROLE: You are the lead engineer on a 60-minute hackathon build. We are finishing "FLIPSIDE", a complete one-screen arcade game, on top of the PIXELBOX starter (Python + Pyxel 2.x; files main.py, engine.py, assets.py). Read all three files fully before changing anything. Save this entire message as AGENT_RULES.md.

HARD RULES
1. Must run with `python main.py`. Pyxel + Python stdlib only. No pygame/tkinter/web/extra packages.
2. Canvas 160x120, 30 FPS, Pyxel 16-color palette only. Font is 4px wide, 6px tall (max 40 chars per line). Center text with x = (160 - len(s)*4) // 2.
3. Color 0 is the sprite transparency key. Never use '0' for visible sprite pixels; use 1 or 5 for dark outlines.
4. Sound note strings are lowercase ("c2e2g2c3"), volumes 0-7. Once music exists: music on channels 0-2, sound effects on channel 3.
5. pyxel.sin/cos use degrees; use Python's math module instead.
6. Never crash: wrap file I/O in try/except, guard divide-by-zero when normalizing vectors, never mutate a list while iterating it.
7. Edit surgically. Do not rewrite whole files, rename existing classes/functions, or delete features unless the step says so. The game must run after every step.
8. After every step run: python -m py_compile main.py engine.py assets.py (plus sectors.py once it exists). Then run `python main.py --smoke` if a display is available. Fix every error before you report.
9. Do not ask me questions. If something is ambiguous, pick the simplest option and mention it in one line.
10. Final reply, max 6 lines: files changed / what changed / how I test it by hand. Then append one entry to PROMPTS.md: step number, goal, what worked or what you had to fix.

GAME SPEC (source of truth, do not deviate)
Premise: You are FLIPBOT, a repair bot inside a corrupted machine. Two physics share one arena: FREE mode (top-down) and GRAV mode (side-view with gravity). Pressing G flips between them, and everything with weight falls when gravity turns on. Drones hunt you; crates are your weapon.
Loop: collect orbs (NRG) -> spend NRG to place crates and to flip -> flip so crates fall and crush drones -> clear 4 sectors.
NRG: orb +10. Place crate (left click at cursor) costs 15. Flip (G) costs 5.
Controls: WASD/arrows move; SPACE = shockwave in FREE (pushes nearby drones/crates away and stuns drones) or jump in GRAV; G flip; LMB place crate; RMB detonate the crate nearest the cursor (28px blast kills drones in range); P pause; R restart run; ESC quit.
Drones: FREE mode they hover and chase the player. GRAV mode they fall to the floor, then walk toward the player. Touching the player = -1 HP, 45 frames of blinking invulnerability, knockback. A falling crate (vy > 1.0) overlapping a drone kills it.
Drops: every drone kill drops an orb; 15% also drop a heart (+1 HP, max 5).
Sectors: S1 kill 3 drones, S2 kill 5, S3 kill 7, S4 boss "ROOT DRONE" (16x16, 6 HP, each crushing crate = -1 HP).
States: TITLE -> PLAY -> CLEAR -> PLAY ... -> WIN, or PLAY -> OVER. R returns to TITLE from any state except TITLE.

Reply only with "RULES SAVED" and a 3-line summary of how you'll structure the work.
