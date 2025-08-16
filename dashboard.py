import os
import io
import sys
import time
import threading
import subprocess
import socket
import json
import argparse
import traceback
import tkinter as tk
from time import sleep
from tkinter.scrolledtext import ScrolledText
from typing import Any, Dict, List, Callable

import win32clipboard as clp
import win32con as con
import ctypes

from remote_control import RemoteControlThread

# Ensure required modules are available.
try:
    import wmi
except ImportError:
    raise ImportError("The 'wmi' module is required. Please install it using 'pip install wmi'.")

try:
    import psutil
except ImportError:
    raise ImportError("The 'psutil' module is required. Please install it using 'pip install psutil'.")

try:
    import pystray
except ImportError:
    raise ImportError("The 'pystray' module is required. Please install it using 'pip install pystray'.")

try:
    from PIL import Image, ImageTk
except ImportError:
    raise ImportError("The 'Pillow' package is required. Please install it using 'pip install Pillow'.")

try:
    import pythoncom
except ImportError:
    raise ImportError("The 'pythoncom' module (pywin32) is required. Please install it using 'pip install pywin32'.")

# ===============
# CLIPBOARD UTILS
# ===============
CLP_FORMATS = {val: name for name, val in vars(clp).items() if name.startswith('CF_')}

def format_name(fmt):
    if fmt in CLP_FORMATS:
        return CLP_FORMATS[fmt]
    try:
        return clp.GetClipboardFormatName(fmt)
    except:
        return "unknown"

def get_available_formats():
    clp.OpenClipboard()
    
    formats = []
    fmt = 0
    while True:
        fmt = clp.EnumClipboardFormats(fmt)
        if fmt == 0: break
        formats.append(format_name(fmt))

    clp.CloseClipboard()
    return formats

def png_to_bmp_dib(png_bytes, keep_alpha=False):
    """Convert raw PNG bytes → DIB byte string (header + pixels)."""
    img = Image.open(io.BytesIO(png_bytes))
    mode = "RGBA" if keep_alpha else "RGB"
    with io.BytesIO() as tmp:
        img.convert(mode).save(tmp, format="BMP")
        bmp = tmp.getvalue()
    return bmp[14:]

def promote_png_to_dib():
    png_fmt = clp.RegisterClipboardFormat("PNG")      # same call Barrier used
    clp.OpenClipboard()
    try:
        if not clp.IsClipboardFormatAvailable(png_fmt):
            raise RuntimeError("PNG format not on clipboard")
        png_bytes = clp.GetClipboardData(png_fmt)     # <class 'bytes'>
    finally:
        clp.CloseClipboard()

    dib_bytes = png_to_bmp_dib(png_bytes, keep_alpha=False)

    clp.OpenClipboard()
    try:
        clp.EmptyClipboard()                          # optional – keeps things tidy
        clp.SetClipboardData(con.CF_DIB, dib_bytes)   # pywin32 will alloc HGLOBAL
        # If you need alpha, use con.CF_DIBV5 instead and keep_alpha=True
    finally:
        clp.CloseClipboard()

# ========================
# Configuration parameters
# ========================
HOST = "192.168.2.1"
# HOST = "192.168.1.10"
REMOTE_PORT = 1234
HOME = os.environ.get("USERPROFILE", "")
CONFIG_FILE_NAME = "config.json"
CONFIG_FILE = os.path.join(os.path.dirname(__file__), CONFIG_FILE_NAME)
BARRIER_HOME = os.path.join(HOME, "barrier")
BARRIER_EXE = r"c:\program files\barrier\barriers.exe"
ICON = "barrier_manager.png"

if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "w") as f:
        f.write("[\n]")

# ============
# Config utils
# ============
def read_config() -> List[Dict[str, Any]]:
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)

    return config

def write_config(config: List[Dict[str, Any]]):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def get_barrier_configs():
    sgc_files = [f for f in os.listdir(BARRIER_HOME) if f.lower().endswith(".sgc")]
    return sgc_files

# ================================
# Barrier prcess management and UI
# ================================
class BarrierManager:
    def __init__(self, log_func: Callable[..., None], status_func: Callable[[str], None]):
        self.log = log_func
        self.update_status = status_func
        self.load_config()
        self.update()
        self.monitor_running_lock = threading.Lock()
        self.monitor_running = False
        self.monitor_thread = None

        self.barr_proc_lock = threading.Lock()
        self.barr_proc = None

        self.log_thread_lock = threading.Lock()
        self.log_thread_running = True
        self.barrier_log_thread = threading.Thread(target=self.process_barrier_output, daemon=True).start()
        
    def load_config(self):
        self._config = read_config()
        self._monitor_map = self._get_monitor_map()

    def update(self):
        self.monitors = self._get_monitors()
        self.status = self._monitor_map.get(self.monitors, None)

        status_name = self.status["name"] if self.status is not None else "Unkown"
        self.update_status(status_name)

    def _get_monitor_map(self):
        return {tuple(sorted(map["monitors"])): map for map in self._config}

    def _get_monitors(self) -> tuple[str, ...]:
        """Return a canonical tuple of monitor instance names using WMI."""
        monitors = ()
        try:
            pythoncom.CoInitialize()  # Initialize COM for this thread.
            c = wmi.WMI(namespace="root\\wmi")
            monitors = tuple(sorted(m.InstanceName for m in c.WmiMonitorBasicDisplayParams()))
        except Exception as e:
            print("WMI query failed:", e)
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
        return monitors

    def start_barrier(self, config_file:str | None = None):
        if self.status is None:
            self.log("Monitor configuration unrecognized; no Barrier started.")
            return
        self.log("Starting Barrier...")

        if config_file is None:
            config_file = self.status["barr_config"]

        cmd = [BARRIER_EXE, "-a", HOST, "-c", config_file, "-n", "endoxide-pc", "--disable-crypto", "--no-tray"]
        self.log(f"Running: {' '.join(cmd)}")
        barr_proc = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return barr_proc

    def kill_barrier(self, threaded=False, report=False):
        """Log the currently running Barrier processes."""
        if threaded:
            threading.Thread(target=self._kill_barrier, args=(report,), daemon=True).start()
        else:
            self._kill_barrier(report=report)

    def _kill_barrier(self, report=False):
        """Kill all running Barrier processes."""
        self.log("Killing barrier processes...")
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] and proc.info['name'].lower() == "barriers.exe":
                try:
                    proc.kill()
                except Exception as e:
                    self.log("Failed to kill process:", e)
        self.log("Killed barrier processes")
        if report:
            self.report_barrier_process_info()

    def process_barrier_output(self):
            running = True
            while running:
                sleep(0.5)
                try:
                    if self.barr_proc:
                        for line in self.barr_proc.stdout or []: # blocking until EOF received
                            line_str = line.decode().strip()
                            self.log(line_str, target=BarrierApp.LG_BARRIER)
                            if all(i in line_str for i in ("updated clipboard 0", "mLaptop")):
                                self.try_fix_clipboard()

                        for line in self.barr_proc.stderr or []: # blocking until EOF received
                            line_str = line.decode().strip()
                            self.log("[Error] ", line_str, target=BarrierApp.LG_BARRIER)

                    # graceful handling to stop thread
                    with self.log_thread_lock:
                        running = self.log_thread_running
                except Exception as e:
                    self.log("[Error] Barrier log thread error caught: ", traceback.format_exception(type(e), e, e.__traceback__))

    def try_fix_clipboard(self):
        if os.name == "nt" and "win32clipboard" in sys.modules:
            avail_fmts = get_available_formats()
            try:
                clp.OpenClipboard()
                if "CF_TEXT" in avail_fmts:
                    self.log("Fixing clipboard for CF_TEXT...")
                    data = clp.GetClipboardData(clp.CF_TEXT)
                    clp.EmptyClipboard()
                    clp.SetClipboardText(data, clp.CF_TEXT)
                elif "CF_UNICODETEXT" in avail_fmts:
                    self.log("Fixing clipboard for CF_UNICODETEXT...")
                    data = clp.GetClipboardData(clp.CF_UNICODETEXT)
                    clp.EmptyClipboard()
                    clp.SetClipboardText(data, clp.CF_UNICODETEXT)
            except Exception as e:
                self.log(e.with_traceback(None))
            finally:
                clp.CloseClipboard()

    def address_available(self):
        """Check if any local interface has the specified IP address."""
        for _, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and addr.address == HOST:
                    return True
        return False

    def get_barrier_process_info(self):
        """Return a list of command line strings for running Barrier processes."""
        info = None
        for proc in psutil.process_iter(['name', 'cmdline']):
            if proc.info['name'] and proc.info['name'].lower() == "barriers.exe":
                if info is None:
                    info = []

                if proc.info["cmdline"]:
                    info.append(f"{proc.pid} " + " ".join(proc.info['cmdline']))
                else:
                    info.append(f"{proc.pid} {proc.info['name']}")
        return info

    def report_barrier_process_info(self, threaded=False):
        """Log the currently running Barrier processes."""
        if threaded:
            threading.Thread(target=self._report_barrier_process_info, daemon=True).start()
        else:
            return self._report_barrier_process_info()

    def _report_barrier_process_info(self):
        barrier_processes = self.get_barrier_process_info()
        process_counter = 1
        if barrier_processes is not None:
            message = "Current barrier processes:"
            for line in barrier_processes:
                message += f"\n\n  {process_counter}. {line}"
                process_counter += 1
            message += "\n"
            self.log(message)
            return True # Barrier processes running
        else:
            self.log("No Barrier processes are running")
            return False # No Barrier process running

    def apply_barrier_change(self, force=False):
        """Kill any running Barrier process and restart it based on auto-detected monitor configuration."""
        if not force \
            and self.status is not None \
            and self.monitors == self.status["monitors"]:
            self.log("No action required")
            return

        # only kill barrier if processes are running 
        if self.report_barrier_process_info(): 
            self.log("Restarting Barrier...")
            self.kill_barrier()
            sleep(1)
            self.report_barrier_process_info()

        # Choose configuration based on monitors.
        self.update() # update status and monitors
        with self.barr_proc_lock:
            self.barr_proc = self.start_barrier() # start required barrier config based on status
        self.report_barrier_process_info() # report new process started

    # ==========================
    # Monitoring Loop (runs in a background thread)
    # ==========================
    def start_monitor_loop(self):
        with self.monitor_running_lock:
            if self.monitor_running:
                self.log("Failed to start monitor loop: Already running")
            else:
                self.log("Starting monitoring thread...")
                self.monitor_running = True
                self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
                print("got here")
                self.monitor_thread.start()


    def _monitor_loop(self):
        try:
            address_available = self.address_available()
            if address_available:
                self.apply_barrier_change()
            else:
                self.log("Cannot bind to address")
            running = True
            while running:
                time.sleep(1)

                new_address_available = self.address_available()
                if not new_address_available and address_available:
                    self.log("Cannot bind to address")
                    address_available = new_address_available
                    continue
                new_monitors = self._get_monitors()
                if new_address_available and self.monitors != new_monitors:
                    self.log("Monitor configuration changed.")
                    self.monitors = new_monitors
                    self.apply_barrier_change()

                with self.monitor_running_lock:
                    if not self.monitor_running:
                        running = False
        except Exception as e:
            self.log("[Error] Monitor loop thread crashed with esception: ", traceback.format_exception(type(e), e, e.__traceback__))

    def stop_monitor_loop(self):
        self.log("Cleaning up monitoring thread...")
        with self.monitor_running_lock:
            self.monitor_running = False
            join_thread = bool(self.monitor_thread)

        join_thread and self.monitor_thread.join() # type: ignore

    def stop_log_thread(self):
        self.log("Cleaning up log thread...")
        with self.log_thread_lock:
            self.log_thread_running = False
            join_thread = bool(self.barrier_log_thread)

        join_thread and self.barrier_log_thread.join() # type: ignore

    def cleanup(self):
        self.kill_barrier()
        self.stop_monitor_loop()
        self.stop_log_thread()

    def config_path(self, config):
        return os.path.join(BARRIER_HOME, config)

    def try_add_monitor_config_mapping(self, name: str, barr_config):
        """Attempts to add a config entry with the given name and Barrier config file name.

        Params:
        name - the name of the mapping
        barr_config - the Barrier configuration file to load for the current monitor configuration
        """
        # create new mapping
        monitors = self._get_monitors()

        mapping = {"name": name, "monitors": monitors, "barr_config": self.config_path(barr_config)}

        # update current config and monitor mappings
        if monitors in self._monitor_map: # monitors already mapped: overwrite
            new_config = [m for m in self._monitor_map.values() if m != monitors]
        else:
            new_config = self._config # new monitor configuration

        new_config.append(mapping)
        write_config(new_config)
        self._config = new_config
        self._monitor_map[monitors] = mapping
        self.log(f"Saved current monitor configuration mapping '{name}': '{barr_config}'")
        self.update() # load current mapping and monitors
        self.apply_barrier_change(force=True) # apply change

# ==========================
# UI and System Tray Integration
# ==========================
class BarrierApp:
    LG_MANAGER = "manager"
    LG_BARRIER = "barrier"
    LG_REMOTE = "remote control"
    LOG_WINDOWS = (LG_MANAGER, LG_BARRIER, LG_REMOTE)

    def __init__(self, root, show=False):
        self.root = root
        self.root.title("Barrier Monitor")
        self.icon_path = os.path.join(os.path.dirname(__file__), ICON)

        icon = self.create_image()
        photo = ImageTk.PhotoImage(icon)
        print("Setting protocols...")
        self.root.wm_iconphoto(False, photo)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Unmap>", lambda _: self.hide_window())

        set_status_name = self.create_ui(root)

        print("Creating barrier manager...")
        self.barrier_manager = BarrierManager(self.log, set_status_name)

        print("Starting monitor loop...")
        # Start the background threads
        root.after(1, self.barrier_manager.start_monitor_loop)

        print("Starting remote control...")
        self.remote_control = RemoteControlThread(host=HOST, port=REMOTE_PORT, log=lambda *args: self.log(*args, target=self.LG_REMOTE))
        root.after(1, self.remote_control.start)

        print("Setting tray icon...")
        # Setup system tray icon.
        self.icon = None
        self.setup_tray_icon()

        if not show:
            self.hide_window()

    def create_ui(self, root):
        root.minsize(1080, 80)
        main_frame = tk.Frame(root)
        main_frame.pack(fill="both", expand=True)

        # Left panel: configuration/status and control buttons.
        config_frame = tk.Frame(main_frame)
        config_frame.pack(side="left", fill="y", padx=5, pady=5)

        # Label for Barrier configuration status.
        config_label = tk.Label(config_frame, font=("Arial", 12))
        config_label.pack(pady=10)

        def set_status_name(name: str):
            config_label.config(text=f"Current Barrier Configuration: {name}")

        set_status_name("Unkown")

        # Buttons to force restart.
        btn_restart_detected = tk.Button(config_frame, text="Restart (Detected)", width=20, command=self.restart_detected)
        btn_restart_detected.pack(pady=5)

        btn_processes = tk.Button(config_frame, text="Log Processes", width=20, command=lambda: self.barrier_manager.report_barrier_process_info(threaded=True))
        btn_processes.pack(pady=5)
        btn_stop_processes = tk.Button(config_frame, text="Stop Processes", width=20, command=lambda: self.barrier_manager.kill_barrier(threaded=True, report=True))
        btn_stop_processes.pack(pady=5)
        btn_monitors = tk.Button(config_frame, text="Log Monitors", width=20, command=lambda: self.log("\n".join(self.barrier_manager.monitors)))
        btn_monitors.pack(pady=5)
        btn_clear = tk.Button(config_frame, text="Clear", width=20, command=self.clear_log)
        btn_clear.pack(pady=5)
        btn_edit = tk.Button(config_frame, text="Edit Script", width=20, command=self.on_edit_script)
        btn_edit.pack(pady=5)
        btn_restart = tk.Button(config_frame, text="Restart", width=20, command=self.on_restart)
        btn_restart.pack(pady=5)
        btn_stop = tk.Button(config_frame, text="Stop", width=20, command=self.on_quit)
        btn_stop.pack(pady=5)
        self.create_mapping_ui(config_frame)

        # Right panel: log pane.
        self.current_log = BarrierApp.LOG_WINDOWS[0]

        log_frame = tk.Frame(main_frame)
        log_frame.pack(side="right", fill="both", expand=True, padx=5, pady=5)

        self.log_label = tk.Label(log_frame, text=f"Showing: {self.current_log}")
        self.log_label.pack(pady=5)

        log_text_frame = tk.Frame(log_frame)
        log_text_frame.pack(fill="both", expand=True, padx=5, pady=5)

        btn_bar = tk.Frame(log_frame)
        btn_bar.grid_columnconfigure(0, weight=1)
        btn_bar.grid_columnconfigure(len(BarrierApp.LOG_WINDOWS)+1, weight=1)
        btn_bar.pack(side="bottom", fill="x", pady=(0, 5))

        self._logs = {} # name -> ScrolledText
        self._log_frames = {} # name -> outer Frame

        for i, name in enumerate(BarrierApp.LOG_WINDOWS, start=1):
            frame = tk.Frame(log_text_frame)
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)

            text = ScrolledText(frame, state="disabled", width=80, height=80)
            text.pack(fill="both", expand=True)
            self._logs[name] = text
            self._log_frames[name] = frame

            btn = tk.Button(btn_bar, text=name, command=lambda name=name: self.show_log(name))
            btn.grid(row=0, column=i, padx=2)

        self._log_frames[self.current_log].tkraise()

        return set_status_name


    def create_mapping_ui(self, root):
        frame = tk.Frame(root)
        frame.pack(pady=10, padx=10)

        frame_grid = tk.Frame(frame)
        frame_grid.pack(padx=0, pady=0)
        
        # Label and text entry for monitor-barrier mapping.
        tk.Label(frame_grid, text="Monitor-Barrier Mapping:").grid(row=0, column=0, sticky="w")
        mapping_name = tk.Entry(frame_grid, width=30)
        mapping_name.grid(row=0, column=1)
        
        # Label for the dropdown.
        tk.Label(frame_grid, text="Barrier Config:").grid(row=1, column=0, sticky="w", padx=(0, 0))

        config_frame = tk.Frame(frame_grid)
        config_frame.grid(row=1, column=1, padx=5, pady=5)
        
        # Dropdown for available barrier configs.
        available_configs = get_barrier_configs()
        selected_config = tk.StringVar()
        if available_configs:
            selected_config.set(available_configs[0])  # Set default value.
        dropdown = tk.OptionMenu(config_frame, selected_config, *available_configs)
        dropdown.grid(row=1, column=1, padx=5, pady=5)

        def open_config_explorer():
            config_path = os.path.join(BARRIER_HOME, selected_config.get())
            subprocess.Popen(f"explorer /select,\"{config_path}\"")

        def edit_config():
            config_path = os.path.join(BARRIER_HOME, selected_config.get())
            subprocess.Popen(f"wt new-tab nvim {config_path}")

        tk.Button(config_frame, text="Open Explorer", command=open_config_explorer).grid(row=1, column=2, padx=5, pady=5)
        tk.Button(config_frame, text="Edit", command=edit_config).grid(row=1, column=3, padx=5, pady=5)
        
        # Save button that calls save_config with the mapping and selected config.
        def _on_save():
            name = mapping_name.get()
            config = selected_config.get()
            self.barrier_manager.try_add_monitor_config_mapping(name, config)

        def on_save():
            threading.Thread(target=_on_save, daemon=True).start()
        
        tk.Button(frame, text="Save", command=on_save).pack(padx=5, pady=0)

    def show_log(self, name: str):
        self.current_log = name
        self._log_frames[name].tkraise()
        self.log_label.config(text=f"Showing: {self.current_log}")

    def log(self, *args, target: str | None = None):
        """Append message to the log pane."""
        if target is None:
            target = BarrierApp.LOG_WINDOWS[0]

        text = self._logs[target]
        message = ' '.join(map(str, args))

        def do_log():
            text.configure(state="normal")
            text.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
            text.configure(state="disabled")
            text.see(tk.END)

        text.after(0, do_log)

    def clear_log(self, target: str | None = None):
        if target is None:
            target = self.current_log

        text = self._logs[target]

        text.configure(state="normal")
        text.delete("1.0", tk.END)
        text.configure(state="disabled")

    def hide_window(self):
        self.root.withdraw()

    def show_window(self):
        self.root.deiconify()

    def on_close(self):
        self.hide_window()

    def on_quit(self):
        self.barrier_manager.cleanup()
        self.remote_control.shutdown()
        if self.icon:
            print("destroying icon")
            self.icon.stop()
        print("root quit")
        self.root.quit()

    def on_restart(self):
        self.log(f"Restarting {__file__}...")
        print(__file__)
        subprocess.Popen(["pythonw", __file__, "--show"])
        self.on_quit()

    def on_edit_script(self):
        file = __file__
        path = os.path.dirname(file)
        basename = os.path.basename(file)
        name, _ = os.path.splitext(basename)
        script = os.path.join(path, f"{name}.py")
        self.log(f"Opening {script}...")
        subprocess.Popen(f"wt new-tab nvim {script}")

    def setup_tray_icon(self):
        image = self.create_image()
        menu = pystray.Menu(
            pystray.MenuItem("Show", self.show_window, default=True),
            pystray.MenuItem("Restart Barrier", self.restart_detected),
            pystray.MenuItem("Restart", self.on_restart),
            pystray.MenuItem("Quit", self.on_quit)
        )
        # Pass the on_click callback to handle left-click events.
        self.icon = pystray.Icon("barrier_app", image, "Barrier Monitor", menu)
        threading.Thread(target=self.icon.run, daemon=True).start()

    def create_image(self):
        image = Image.open(self.icon_path)

        return image


    def restart_detected(self):
        """Force a restart using auto-detected monitor configuration in a separate thread."""
        threading.Thread(target=self.barrier_manager.apply_barrier_change, args=(True,), daemon=True).start()

# ==========================
# Main
# ==========================
def main(show=False):
    myappid = "endoxide.barrier_manager"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    root = tk.Tk()
    BarrierApp(root, show=show)
    root.mainloop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Screen autodetect")
    parser.add_argument("-s", "--show", action="store_true", help="Show window on start")
    args, _ = parser.parse_known_args()
    main(args.show)
