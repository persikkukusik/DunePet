import os
import sys
import json
import atexit
import datetime
import tkinter as tk
import time
import random
from PIL import Image, ImageTk, ImageSequence

# 1. Setup paths for all GIFs
script_dir = os.path.dirname(os.path.abspath(__file__))
emotes_dir = os.path.join(script_dir, "emotes")

gif_paths = {
    "idle": os.path.join(emotes_dir, "DunePlead.gif"),
    "tired": os.path.join(emotes_dir, "DuneTired.gif"),
    "blink": os.path.join(emotes_dir, "DuneBlink.gif"),
    "annoyed": os.path.join(emotes_dir, "DuneAnnoyed.gif"),
    "confused": os.path.join(emotes_dir, "DuneConfused.gif"),
    "happy": os.path.join(emotes_dir, "DuneHappy.gif"),
    "blush": os.path.join(emotes_dir, "DuneBlush.gif"),
    "scared": os.path.join(emotes_dir, "DuneScared.gif"),
    "angry": os.path.join(emotes_dir, "DuneAngry.gif"),
    "crying": os.path.join(emotes_dir, "DuneCrying.gif"),
    # --- New OPTIONAL emotes ---
    "sleeping": os.path.join(emotes_dir, "DuneSleeping.gif"),
    "yawn": os.path.join(emotes_dir, "DuneYawn.gif"),
    "curious": os.path.join(emotes_dir, "DuneCurious.gif"),
    "loved": os.path.join(emotes_dir, "DuneLoved.gif"),
}

# --- FEATURE TOGGLES ---
ENABLE_BREATHING = False        # subtle 1px idle "breathing" bob
ENABLE_SLEEP = True             # falls asleep when left alone too long
ENABLE_CURIOUS_HOVER = True     # occasionally reacts when the mouse passes over it
ENABLE_BOND_MEMORY = True       # remembers affection/total pets across runs (dune_save.json)
SLEEP_DELAY_DAY_MS = 180_000     # falls asleep after 3 min of being ignored (daytime)
SLEEP_DELAY_NIGHT_MS = 45_000    # falls asleep after 45s late at night (23:00-07:00)

# Helper to dynamically pick the default state based on time
def get_current_baseline():
    hour = datetime.datetime.now().hour
    if hour >= 23 or hour < 7:
        return "tired"
    return "idle"

# 2. Initialize Window
root = tk.Tk()
root.title("GIF Viewer")
root.geometry("111x89")
root.resizable(False, False)
root.overrideredirect(True)
root.attributes("-topmost", True)

TARGET_WIDTH = 111
TARGET_HEIGHT = 89

REQUIRED_STATES = {
    "idle", "tired", "blink", "annoyed", "confused", "happy",
    "blush", "scared", "angry", "crying",
}
OPTIONAL_FALLBACKS = {
    "sleeping": "idle",
    "yawn": "confused",
    "curious": "confused",
    "loved": "blush",
}


def load_gif_frames(path, quiet=False):
    frames = []
    try:
        with Image.open(path) as img:
            for frame in ImageSequence.Iterator(img):
                frame_rgba = frame.convert("RGBA")
                resized_frame = frame_rgba.resize((TARGET_WIDTH, TARGET_HEIGHT), Image.Resampling.LANCZOS)
                frames.append(ImageTk.PhotoImage(resized_frame))
    except Exception as e:
        if not quiet:
            print(f"Error loading {os.path.basename(path)}: {e}")
    return frames


# Load images into memory
all_emotes = {
    state: load_gif_frames(path, quiet=(state not in REQUIRED_STATES))
    for state, path in gif_paths.items()
}

# Absolute fallback cascade
if not all_emotes["idle"]:
    print("Error: Could not load the baseline idle GIF (DunePlead.gif). Exiting.")
    sys.exit()

for state in REQUIRED_STATES:
    if not all_emotes.get(state):
        all_emotes[state] = all_emotes["idle"]

for state, fallback in OPTIONAL_FALLBACKS.items():
    if not all_emotes.get(state):
        all_emotes[state] = all_emotes[fallback]

# --- CORE STATE MACHINE & METERS ---
current_state = get_current_baseline()
pre_blink_state = get_current_baseline()
frame_index = 0

hype_meter = 0
inactivity_timer_id = None
rare_idle_timer_id = None
rare_expiry_timer_id = None

# Mood Locks
is_angry = False
is_crying = False
is_scared_right_now = False
is_blinking_right_now = False  # Independent lock for the passive reflex blink
is_sleeping = False
is_curious_right_now = False
is_dragging = False
is_settling = False

# Shaking thresholds
shake_accumulator = 0
last_x, last_y = 0, 0
last_time = 0

SCARED_THRESHOLD = 1200
CRYING_THRESHOLD = 3500

x_offset = 0
y_offset = 0

# Breathing / settle physics
rest_y = None
bob_up = False

# Hover curiosity cooldown
last_curious_time = 0.0

# Interaction timing (used by the sleep system)
last_interaction_time = time.time()

# --- PERSISTENT BOND ---
SAVE_FILE = os.path.join(script_dir, "dune_save.json")


def load_save():
    default = {"affection": 0.0, "total_pets": 0, "last_seen": time.time()}
    if not ENABLE_BOND_MEMORY:
        return default
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r") as f:
                data = json.load(f)
            default.update(data)
        except Exception:
            pass
    return default


def persist_save():
    if not ENABLE_BOND_MEMORY:
        return
    try:
        with open(SAVE_FILE, "w") as f:
            json.dump({
                "affection": affection,
                "total_pets": total_pets,
                "last_seen": time.time(),
            }, f)
    except Exception as e:
        print(f"Could not save Dune's bond data: {e}")


_save_data = load_save()
_days_away = max(0.0, (time.time() - _save_data.get("last_seen", time.time())) / 86400.0)
affection = max(0.0, _save_data.get("affection", 0.0) - _days_away * 0.5)
total_pets = _save_data.get("total_pets", 0)

atexit.register(persist_save)


def get_bond_tier():
    if affection >= 50:
        return "Best Friend"
    if affection >= 20:
        return "Close Buddy"
    if affection >= 5:
        return "Getting Friendly"
    return "New Friend"


# 3. GUI Layout
label = tk.Label(root, image=all_emotes[current_state][0], bg="black", bd=0, highlightthickness=0)
label.pack(fill="both", expand=True)
label.config(cursor="hand2")


# 4. Rare Idle Routine Coordinator
def clear_all_idle_timers():
    global rare_idle_timer_id, rare_expiry_timer_id
    if rare_idle_timer_id:
        root.after_cancel(rare_idle_timer_id)
        rare_idle_timer_id = None
    if rare_expiry_timer_id:
        root.after_cancel(rare_expiry_timer_id)
        rare_expiry_timer_id = None


def schedule_next_rare_idle(initial_cooldown=False):
    global rare_idle_timer_id
    clear_all_idle_timers()
    delay_ms = 60000 if initial_cooldown else random.randint(30000, 120000)
    rare_idle_timer_id = root.after(delay_ms, trigger_rare_idle)


def trigger_rare_idle():
    global current_state, rare_expiry_timer_id
    if (hype_meter > 0 or is_angry or is_crying or is_scared_right_now
            or is_blinking_right_now or is_sleeping or is_curious_right_now):
        schedule_next_rare_idle(initial_cooldown=True)
        return

    pool = ["annoyed", "confused"]
    if affection >= 20:
        pool.append("loved")

    current_state = random.choice(pool)
    duration_ms = random.randint(3000, 6000) if current_state == "loved" else random.randint(5000, 10000)
    rare_expiry_timer_id = root.after(duration_ms, end_rare_idle)


def end_rare_idle():
    global current_state, pre_blink_state
    if is_blinking_right_now:
        pre_blink_state = get_current_baseline()
    else:
        current_state = get_current_baseline()
    schedule_next_rare_idle(initial_cooldown=False)


# 5. Passive Reflex Blink Checker
def check_passive_blink():
    global current_state, pre_blink_state, is_blinking_right_now, frame_index

    allowed_states = ["idle", "tired", "annoyed", "confused"]

    if current_state in allowed_states and not is_blinking_right_now:
        if random.random() < 0.20:
            pre_blink_state = current_state
            current_state = "blink"
            is_blinking_right_now = True
            frame_index = 0


# 6. State Management Functions
def refresh_inactivity_timer():
    global inactivity_timer_id
    if inactivity_timer_id:
        root.after_cancel(inactivity_timer_id)
    inactivity_timer_id = root.after(2500, cut_off_hype)


def cut_off_hype():
    global hype_meter, current_state, inactivity_timer_id, is_blinking_right_now
    inactivity_timer_id = None
    hype_meter = 0

    if not is_angry and not is_crying and not is_scared_right_now and not is_sleeping:
        current_state = get_current_baseline()
        is_blinking_right_now = False
        schedule_next_rare_idle(initial_cooldown=True)


def eval_hype_state():
    global current_state, is_blinking_right_now
    if not is_angry and not is_crying and not is_scared_right_now and not is_sleeping:
        is_blinking_right_now = False
        if hype_meter > 4:
            current_state = "blush"
        elif hype_meter > 0:
            current_state = "happy"


# 7. Sleep System
def get_sleep_delay_seconds():
    hour = datetime.datetime.now().hour
    if hour >= 23 or hour < 7:
        return SLEEP_DELAY_NIGHT_MS / 1000.0
    return SLEEP_DELAY_DAY_MS / 1000.0


def begin_sleep():
    global current_state, is_sleeping, frame_index
    clear_all_idle_timers()
    is_sleeping = True
    current_state = "yawn"
    frame_index = 0


def enter_deep_sleep():
    global current_state, frame_index
    if is_sleeping:
        current_state = "sleeping"
        frame_index = 0


def force_sleep():
    if not is_sleeping and not is_angry and not is_crying and not is_scared_right_now:
        begin_sleep()


def wake_up_pet():
    global is_sleeping, current_state
    if is_sleeping:
        is_sleeping = False
        current_state = "happy"
        schedule_next_rare_idle(initial_cooldown=True)


def check_sleep():
    calm_states = ("idle", "tired", "annoyed", "confused")
    elapsed = time.time() - last_interaction_time
    if (not is_sleeping and not is_angry and not is_crying and not is_scared_right_now
            and not is_curious_right_now and hype_meter == 0
            and current_state in calm_states and elapsed > get_sleep_delay_seconds()):
        begin_sleep()
    root.after(5000, check_sleep)


def end_welcome_back():
    global current_state
    if current_state == "happy":
        current_state = get_current_baseline()


# 8. Drag & Interaction Logic
def start_drag(event):
    global x_offset, y_offset, current_state, hype_meter, affection
    global is_angry, is_crying, is_scared_right_now, is_sleeping, shake_accumulator
    global last_x, last_y, last_time, last_interaction_time, is_dragging

    clear_all_idle_timers()
    last_interaction_time = time.time()
    is_dragging = True

    x_offset = event.x
    y_offset = event.y
    label.config(cursor="fleur")

    last_x, last_y = root.winfo_x(), root.winfo_y()
    last_time = time.time()

    if is_sleeping:
        is_sleeping = False
        affection = min(100.0, affection + 0.3)
        hype_meter = 1
        current_state = "happy"
        refresh_inactivity_timer()
    elif is_angry or is_crying:
        is_angry = False
        is_crying = False
        is_scared_right_now = False
        shake_accumulator = 0
        hype_meter = 1
        current_state = "happy"
        refresh_inactivity_timer()
    else:
        hype_meter += 1
        affection = min(100.0, affection + 0.2)
        eval_hype_state()
        refresh_inactivity_timer()


def drag_window(event):
    global last_x, last_y, last_time, shake_accumulator
    global current_state, is_angry, is_crying, is_scared_right_now, is_blinking_right_now, rest_y

    new_x = root.winfo_x() + (event.x - x_offset)
    new_y = root.winfo_y() + (event.y - y_offset)
    root.geometry(f"+{new_x}+{new_y}")
    rest_y = new_y

    current_time = time.time()
    dt = current_time - last_time

    if dt > 0:
        dx = new_x - last_x
        dy = new_y - last_y
        velocity = (dx**2 + dy**2)**0.5 / dt

        if velocity > 2200:
            shake_accumulator += velocity * dt
            is_blinking_right_now = False

            if shake_accumulator > CRYING_THRESHOLD:
                is_crying = True
                is_scared_right_now = False
                is_angry = False
                current_state = "crying"
            elif shake_accumulator > SCARED_THRESHOLD and not is_crying:
                is_scared_right_now = True
                current_state = "scared"

    last_x, last_y = new_x, new_y
    last_time = current_time


def do_settle_bounce():
    global is_settling
    is_settling = True
    base_x = root.winfo_x()
    base_y = root.winfo_y()
    offsets = [-2, -1, 0]

    def step(i):
        global is_settling, rest_y
        if i >= len(offsets):
            is_settling = False
            rest_y = base_y
            return
        root.geometry(f"+{base_x}+{base_y + offsets[i]}")
        root.after(40, lambda: step(i + 1))

    step(0)


def stop_drag(event):
    global is_scared_right_now, current_state, is_angry, shake_accumulator, is_dragging
    label.config(cursor="hand2")
    is_dragging = False

    if is_scared_right_now and not is_crying:
        is_scared_right_now = False
        is_angry = True
        current_state = "angry"
    else:
        is_scared_right_now = False
        if hype_meter == 0 and not is_angry and not is_crying:
            schedule_next_rare_idle(initial_cooldown=True)

    do_settle_bounce()
    shake_accumulator = 0


def on_double_click(event):
    global current_state, hype_meter, affection, total_pets, last_interaction_time

    last_interaction_time = time.time()
    total_pets += 1
    affection = min(100.0, affection + 1.5)
    hype_meter += 3
    eval_hype_state()

    if affection >= 20 and not is_angry and not is_crying and not is_scared_right_now:
        current_state = "loved"

    refresh_inactivity_timer()


# 9. Hover Curiosity
def on_hover_enter(event):
    global current_state, is_curious_right_now, last_curious_time
    now = time.time()
    if (current_state in ("idle", "tired") and not is_curious_right_now and not is_sleeping
            and not is_angry and not is_crying and not is_scared_right_now
            and now - last_curious_time > 8):
        if random.random() < 0.4:
            is_curious_right_now = True
            last_curious_time = now
            current_state = "curious"


def end_curious():
    global current_state, is_curious_right_now
    is_curious_right_now = False
    if current_state == "curious":
        current_state = get_current_baseline()


# 10. Breathing
def breathing_tick():
    global bob_up, rest_y
    if rest_y is None:
        rest_y = root.winfo_y()

    calm_states = ("idle", "tired", "annoyed", "confused", "sleeping", "curious")
    if not is_dragging and not is_settling and current_state in calm_states:
        bob_up = not bob_up
        rx = root.winfo_x()
        target_y = rest_y - (1 if bob_up else 0)
        root.geometry(f"+{rx}+{target_y}")

    root.after(900, breathing_tick)


# 11. Right-click menu, stats popup, quit
def show_stats():
    win = tk.Toplevel(root)
    win.title("Dune's Stats")
    win.attributes("-topmost", True)
    win.resizable(False, False)
    tk.Label(win, text=f"Bond: {get_bond_tier()}", font=("Segoe UI", 10, "bold")).pack(padx=14, pady=(10, 2))
    tk.Label(win, text=f"Affection: {affection:.1f} / 100").pack(padx=14)
    tk.Label(win, text=f"Total pets: {total_pets}").pack(padx=14, pady=(0, 10))
    tk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 10))
    win.geometry(f"+{root.winfo_x() + TARGET_WIDTH + 10}+{root.winfo_y()}")


def quit_app():
    persist_save()
    root.destroy()


context_menu = tk.Menu(root, tearoff=0)
context_menu.add_command(label="💤 Sleep Now", command=force_sleep)
context_menu.add_command(label="📊 Stats", command=show_stats)
context_menu.add_separator()
context_menu.add_command(label="❌ Quit", command=quit_app)


def show_context_menu(event):
    if is_sleeping:
        context_menu.entryconfigure(0, label="☀️ Wake Up", command=wake_up_pet)
    else:
        context_menu.entryconfigure(0, label="💤 Sleep Now", command=force_sleep)
    try:
        context_menu.tk_popup(event.x_root, event.y_root)
    finally:
        context_menu.grab_release()


label.bind("<Button-1>", start_drag)
label.bind("<B1-Motion>", drag_window)
label.bind("<ButtonRelease-1>", stop_drag)
label.bind("<Double-Button-1>", on_double_click)
label.bind("<Button-3>", show_context_menu)
root.protocol("WM_DELETE_WINDOW", quit_app)

if ENABLE_CURIOUS_HOVER:
    label.bind("<Enter>", on_hover_enter)

# 12. Animation Engine Loop
FPS = 12
DEFAULT_INTERVAL_MS = round(1000 / FPS)  # ~83ms

ONE_SHOT_TRANSITIONS = {
    "yawn": enter_deep_sleep,
    "curious": end_curious,
}


def update_gif():
    global frame_index, current_state, is_blinking_right_now

    active_frames = all_emotes[current_state]
    frame_index = frame_index % len(active_frames)

    label.config(image=active_frames[frame_index])

    next_frame_index = (frame_index + 1) % len(active_frames)

    if next_frame_index == 0:
        if current_state == "blink":
            is_blinking_right_now = False
            current_state = pre_blink_state
        elif current_state in ONE_SHOT_TRANSITIONS:
            ONE_SHOT_TRANSITIONS[current_state]()
        else:
            check_passive_blink()

        if hype_meter > 0:
            eval_hype_state()

    frame_index = next_frame_index

    # Check if we are yawning -- if so, slow frame pacing to 3 FPS (~333ms delay), else stay normal speed.
    current_interval = DEFAULT_INTERVAL_MS * 2 if current_state == "yawn" else DEFAULT_INTERVAL_MS
    root.after(current_interval, update_gif)


# 13. Boot sequence
schedule_next_rare_idle(initial_cooldown=True)

if ENABLE_BOND_MEMORY and _days_away > 0.4:
    current_state = "happy"
    affection = min(100.0, affection + 0.5)
    root.after(4000, end_welcome_back)

root.after(0, update_gif)

if ENABLE_SLEEP:
    root.after(5000, check_sleep)

if ENABLE_BREATHING:
    root.after(900, breathing_tick)

root.mainloop()
