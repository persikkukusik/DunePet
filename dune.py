import os
import sys
import tkinter as tk
import time
import random
from PIL import Image, ImageTk, ImageSequence

# 1. Setup paths for all 8 GIFs
script_dir = os.path.dirname(os.path.abspath(__file__))
emotes_dir = os.path.join(script_dir, "emotes")

gif_paths = {
    "idle": os.path.join(emotes_dir, "DunePlead.gif"),
    "blink": os.path.join(emotes_dir, "DuneBlink.gif"),
    "annoyed": os.path.join(emotes_dir, "DuneAnnoyed.gif"),
    "confused": os.path.join(emotes_dir, "DuneConfused.gif"),
    "happy": os.path.join(emotes_dir, "DuneHappy.gif"),
    "blush": os.path.join(emotes_dir, "DuneBlush.gif"),
    "scared": os.path.join(emotes_dir, "DuneScared.gif"),
    "angry": os.path.join(emotes_dir, "DuneAngry.gif"),
    "crying": os.path.join(emotes_dir, "DuneCrying.gif")
}

# 2. Initialize Window
root = tk.Tk()
root.title("GIF Viewer")
root.geometry("111x89")
root.resizable(False, False)
root.overrideredirect(True)
root.attributes("-topmost", True)

TARGET_WIDTH = 111
TARGET_HEIGHT = 89

def load_gif_frames(path):
    frames = []
    try:
        with Image.open(path) as img:
            for frame in ImageSequence.Iterator(img):
                frame_rgba = frame.convert("RGBA")
                resized_frame = frame_rgba.resize((TARGET_WIDTH, TARGET_HEIGHT), Image.Resampling.LANCZOS)
                frames.append(ImageTk.PhotoImage(resized_frame))
    except Exception as e:
        print(f"Error loading {os.path.basename(path)}: {e}")
    return frames

# Load images into memory
all_emotes = {state: load_gif_frames(path) for state, path in gif_paths.items()}

# Absolute fallback cascade
if not all_emotes["idle"]:
    print("Error: Could not load the baseline idle GIF (DunePlead.gif). Exiting.")
    sys.exit()
for state in all_emotes:
    if not all_emotes[state]:
        all_emotes[state] = all_emotes["idle"]

# --- CORE STATE MACHINE & METERS ---
current_state = "idle"
pre_blink_state = "idle"   # Remembers what mood Dune was in before he blinked
frame_index = 0

hype_meter = 0
inactivity_timer_id = None
rare_idle_timer_id = None
rare_expiry_timer_id = None

# Mood Locks
is_angry = False
is_crying = False
is_scared_right_now = False
is_blinking_right_now = False # Independent lock for the passive reflex blink

# Shaking thresholds
shake_accumulator = 0
last_x, last_y = 0, 0
last_time = 0

SCARED_THRESHOLD = 1200
CRYING_THRESHOLD = 3500

x_offset = 0
y_offset = 0

# 3. GUI Layout
label = tk.Label(root, image=all_emotes["idle"][0], bg="black", bd=0, highlightthickness=0)
label.pack(fill="both", expand=True)
label.config(cursor="hand2")

# 4. Rare Idle Routine Coordinator (Now just handles Annoyed & Confused)
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
    # Don't start a long idle animation if he's busy or already blinking
    if hype_meter > 0 or is_angry or is_crying or is_scared_right_now or is_blinking_right_now:
        schedule_next_rare_idle(initial_cooldown=True)
        return

    # Randomly select between just Annoyed and Confused for the long flavor states
    current_state = random.choice(["annoyed", "confused"])
    duration_ms = random.randint(5000, 10000)
    rare_expiry_timer_id = root.after(duration_ms, end_rare_idle)

def end_rare_idle():
    global current_state
    # If he happens to be in the middle of a passive reflex blink when the timer ends,
    # update the memory so he reverts to baseline idle *after* the blink finishes.
    if is_blinking_right_now:
        global pre_blink_state
        pre_blink_state = "idle"
    else:
        current_state = "idle"
    schedule_next_rare_idle(initial_cooldown=False)

# 5. Passive Reflex Blink Checker
def check_passive_blink():
    """Runs at the end of every GIF loop cycle to see if Dune should do a natural reflex blink."""
    global current_state, pre_blink_state, is_blinking_right_now, frame_index

    # Gated Conditions: Only allow a passive blink reflex if he is in an inactive idle state
    # (pleading, annoyed, or confused) and isn't ALREADY blinking.
    allowed_states = ["idle", "annoyed", "confused"]

    if current_state in allowed_states and not is_blinking_right_now:
        # 20% chance to blink naturally when a frame loop finishes
        if random.random() < 0.20:
            pre_blink_state = current_state  # Save the mood he was just in
            current_state = "blink"
            is_blinking_right_now = True
            frame_index = 0                  # Start DuneBlink.gif from frame 0

# 6. State Management Functions
def refresh_inactivity_timer():
    global inactivity_timer_id
    if inactivity_timer_id:
        root.after_cancel(inactivity_timer_id)
    inactivity_timer_id = root.after(1000, cut_off_hype)

def cut_off_hype():
    global hype_meter, current_state, inactivity_timer_id, is_blinking_right_now
    inactivity_timer_id = None
    hype_meter = 0

    if not is_angry and not is_crying and not is_scared_right_now:
        current_state = "idle"
        is_blinking_right_now = False
        schedule_next_rare_idle(initial_cooldown=True)

def eval_hype_state():
    global current_state, is_blinking_right_now
    if not is_angry and not is_crying and not is_scared_right_now:
        is_blinking_right_now = False # Interrupt active blink if petted/clicked
        if hype_meter > 4:
            current_state = "blush"
        elif hype_meter > 0:
            current_state = "happy"

# 7. Drag & Interaction Logic
def start_drag(event):
    global x_offset, y_offset, current_state, hype_meter
    global is_angry, is_crying, is_scared_right_now, shake_accumulator
    global last_x, last_y, last_time

    clear_all_idle_timers()

    x_offset = event.x
    y_offset = event.y
    label.config(cursor="fleur")

    last_x, last_y = root.winfo_x(), root.winfo_y()
    last_time = time.time()

    if is_angry or is_crying:
        is_angry = False
        is_crying = False
        is_scared_right_now = False
        shake_accumulator = 0
        hype_meter = 1
        current_state = "happy"
        refresh_inactivity_timer()
    else:
        hype_meter += 1
        eval_hype_state()
        refresh_inactivity_timer()

def drag_window(event):
    global last_x, last_y, last_time, shake_accumulator
    global current_state, is_angry, is_crying, is_scared_right_now, is_blinking_right_now

    new_x = root.winfo_x() + (event.x - x_offset)
    new_y = root.winfo_y() + (event.y - y_offset)
    root.geometry(f"+{new_x}+{new_y}")

    current_time = time.time()
    dt = current_time - last_time

    if dt > 0:
        dx = new_x - last_x
        dy = new_y - last_y
        velocity = (dx**2 + dy**2)**0.5 / dt

        if velocity > 2200:
            shake_accumulator += velocity * dt
            is_blinking_right_now = False # Stop blinking if shaken

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

def stop_drag(event):
    global is_scared_right_now, current_state, is_angry, shake_accumulator
    label.config(cursor="hand2")

    if is_scared_right_now and not is_crying:
        is_scared_right_now = False
        is_angry = True
        current_state = "angry"
    else:
        is_scared_right_now = False
        if hype_meter == 0 and not is_angry and not is_crying:
            schedule_next_rare_idle(initial_cooldown=True)

    shake_accumulator = 0

# Bind interactions
label.bind("<Button-1>", start_drag)
label.bind("<B1-Motion>", drag_window)
label.bind("<ButtonRelease-1>", stop_drag)
label.bind("<Button-3>", lambda e: root.destroy())

# 8. Animation Engine Loop
def update_gif():
    global frame_index, current_state, is_blinking_right_now

    active_frames = all_emotes[current_state]
    frame_index = frame_index % len(active_frames)

    label.config(image=active_frames[frame_index])

    next_frame_index = (frame_index + 1) % len(active_frames)

    # LOOP HOOK: This triggers every time a GIF hits its final frame and wraps around
    if next_frame_index == 0:
        if current_state == "blink":
            # The reflex blink animation just finished!
            # Turn off the blink flag and immediately return to the mood we stored earlier.
            is_blinking_right_now = False
            current_state = pre_blink_state
        else:
            # If he is not currently blinking, check the reflex dice to see if he should blink now
            check_passive_blink()

        # Re-evaluate interactive hype meters if applicable
        if hype_meter > 0:
            eval_hype_state()

    frame_index = next_frame_index
    root.after(50, update_gif)

# Initialize the long idle coordinator upon bootup
schedule_next_rare_idle(initial_cooldown=True)

# Execute window lifecycle
root.after(0, update_gif)
root.mainloop()
