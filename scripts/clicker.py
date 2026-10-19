import random
import time
from datetime import datetime, timedelta

import pyautogui

# Emergency stop: moving mouse to any corner of the screen aborts the script
pyautogui.FAILSAFE = True

# --- Duration Configuration ---
WORK_HOURS = 0
WORK_MINUTES = 20
MAX_DURATION_SECONDS = WORK_HOURS * 3600 + WORK_MINUTES * 60

print("=== AUTO CLICKER ===")
print(
    f"Target runtime: {WORK_HOURS}h {WORK_MINUTES}m ({MAX_DURATION_SECONDS}s)"
)
print("1. Switch to your browser window.")
print("2. Hover the cursor over the target button.")
print("Capturing base position in 5 seconds...")

for i in range(5, 0, -1):
    print(f"{i}...")
    time.sleep(1)

base_x, base_y = pyautogui.position()
start_time = time.time()
finish_time = datetime.now() + timedelta(seconds=MAX_DURATION_SECONDS)

print(f"\nBase position locked: X={base_x}, Y={base_y}")
print(f"Scheduled finish at: {finish_time.strftime('%H:%M:%S')}")
print("Auto-clicker active. Press Ctrl+C or move mouse to screen corner to stop.\n")

counter = 1

try:
    while True:
        elapsed = time.time() - start_time
        if elapsed >= MAX_DURATION_SECONDS:
            print(
                f"\n[✓] Runtime completed ({WORK_HOURS}h {WORK_MINUTES}m). Total clicks: {counter - 1}."
            )
            break

        # Randomized offset within button bounds (±14px X, ±7px Y)
        target_x = base_x + random.randint(-14, 14)
        target_y = base_y + random.randint(-7, 7)

        # Smooth cursor travel with natural easing
        move_time = random.uniform(0.25, 0.45)
        pyautogui.moveTo(
            target_x, target_y, duration=move_time, tween=pyautogui.easeInOutQuad
        )

        pyautogui.mouseDown()
        # Micro-jitter simulation during press
        if random.random() > 0.5:
            pyautogui.moveRel(
                random.choice([-1, 0, 1]), random.choice([-1, 0, 1]), duration=0.03
            )
        time.sleep(random.uniform(0.08, 0.13))
        pyautogui.mouseUp()

        delay = random.uniform(3.0, 5.0)
        remaining_seconds = max(0, MAX_DURATION_SECONDS - (time.time() - start_time))
        rem_h = int(remaining_seconds // 3600)
        rem_m = int((remaining_seconds % 3600) // 60)
        rem_s = int(remaining_seconds % 60)

        print(
            f"[{counter}] Click at ({target_x}, {target_y}) | Remaining: {rem_h:02d}:{rem_m:02d}:{rem_s:02d} | Delay: {delay:.2f}s"
        )
        counter += 1

        time.sleep(delay)

        if time.time() - start_time >= MAX_DURATION_SECONDS:
            print(
                f"\n[✓] Runtime completed ({WORK_HOURS}h {WORK_MINUTES}m). Total clicks: {counter - 1}."
            )
            break

except KeyboardInterrupt:
    print(f"\n[!] Stopped by user. Total clicks: {counter - 1}.")
