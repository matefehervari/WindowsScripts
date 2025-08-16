# from pynput.mouse import Listener, Button
#
#
# points = []
#
# # Function called on a mouse click
# def on_click(x, y, button, pressed):
#     # Check if the left button was pressed
#     if pressed and button == Button.left:
#         # Print the click coordinates
#         points.append((x, y))
#
#     if len(points) == 2:
#         return False
#
#
# # Initialize the Listener to monitor mouse clicks
# with Listener(on_click=on_click) as listener:
#     listener.join()
#
# print(points)

import ctypes
import tkinter as tk

# ------------------------------------------------------------------
# 1.  Query the virtual-desktop bounding box (Windows only)
# ------------------------------------------------------------------
# Tell Windows not to scale the numbers it gives us
ctypes.windll.user32.SetProcessDPIAware()

SM_XVIRTUALSCREEN = 76   # left-most pixel of any monitor
SM_YVIRTUALSCREEN = 77   # top-most pixel of any monitor
SM_CXVIRTUALSCREEN = 78  # total width  (virtual desktop)
SM_CYVIRTUALSCREEN = 79  # total height (virtual desktop)

user32 = ctypes.windll.user32
v_left   = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
v_top    = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
v_width  = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
v_height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

# ------------------------------------------------------------------
# 2.  Globals
# ------------------------------------------------------------------
CAPTURE_LIMIT = 2
points        = []

# ------------------------------------------------------------------
# 3.  Event callbacks
# ------------------------------------------------------------------
def on_click(event):
    points.append((event.x_root, event.y_root))
    print(f"Click {len(points)}/{CAPTURE_LIMIT}:  x={event.x_root}, y={event.y_root}")
    if len(points) >= CAPTURE_LIMIT:
        shutdown()

def on_escape(event=None):
    print("Capture cancelled (Esc).")
    points.clear()
    shutdown()

def shutdown():
    root.destroy()              # exits mainloop()

# ------------------------------------------------------------------
# 4.  Build a single border-less window covering **all** screens
# ------------------------------------------------------------------
root = tk.Tk()
root.withdraw()                 # hide while configuring

root.geometry(f"{v_width}x{v_height}+{v_left}+{v_top}")
root.configure(bg="gray")       # overlay colour – tweak to taste
root.overrideredirect(True)     # no borders or title-bar
root.attributes("-topmost", True)
root.attributes("-alpha", 0.35) # 0=transparent … 1=opaque
# root.configure(cursor="none") # uncomment to hide the cursor

root.bind("<Button-1>", on_click)   # left mouse button
root.bind("<Escape>",   on_escape)  # fail-safe key

root.deiconify()                # show the overlay
root.mainloop()                 # blocks until shutdown()

# ------------------------------------------------------------------
# 5.  Continue with the rest of your program
# ------------------------------------------------------------------
if not points:
    print("No points captured.")
    exit(0)

print("Captured coordinates:", points)

(p1x, p1y), (p2x, p2y) = points
p_dx, p_dy = abs(p1x - p2x), abs(p1y - p2y)
if p_dx < p_dy:
    start, end = (p1y, p2y) if p1y < p2y else (p2y, p1y)
    print("Vertical diff")

    p_start = (start - v_top) * 100 / v_height
    p_end = (end - v_top) * 100 / v_height
else:
    start, end = (p1x, p2x) if p1x < p2x else (p2x, p1x)
    print("Horizontal diff")

    p_start = (start - v_left) * 100 / v_width
    p_end = (end - v_left) * 100 / v_width

print(f"Proportion of virtual: {p_start:.2f} {p_end:.2f}")
