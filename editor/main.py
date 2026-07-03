import os
import sys
import ctypes
import re

# FORCE DPI AWARENESS BEFORE ANY TKINTER IMPORTS
try:
    if os.name == 'nt':
        # Per Monitor DPI Awareness (Value 2)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception as e:
    print(f"[DEBUG] Could not set DPI awareness: {e}")

import customtkinter as ctk
import json
import random
import time
import shutil
import socket
import ssl
import subprocess
import threading
import zipfile
import urllib.request
import tkinter as tk
from tkinter import simpledialog, filedialog, messagebox
from PIL import Image, ImageTk
from pynput import keyboard

def get_resource_path(relative_path):
    """ Get absolute path to resource, prioritizing live folder for server data """
    if getattr(sys, 'frozen', False):
        # We are running as an EXE
        exe_dir = os.path.dirname(sys.executable)
        bundle_dir = getattr(sys, '_MEIPASS', exe_dir)

        # If we are in _internal (one-dir mode), the live files are one level up
        if os.path.basename(exe_dir).lower() == "_internal":
            exe_dir = os.path.dirname(exe_dir)
        
        # Check if the file exists in the live folder next to the EXE
        if relative_path.startswith("server"):
            live_path = os.path.join(exe_dir, relative_path)
            # If it exists live, or if we are trying to WRITE to it (it's a known user-data path)
            # We check if it's one of the files we want to keep external
            user_files = ["layout.json", "actions.json", "editor_settings.json", "assets", "layouts", "Bug_fixes.txt", "Bug_fixes_joke.txt", "joke_index.txt", "about.txt", "update_locations.txt"]
            is_user_data = any(u in relative_path for u in user_files) or relative_path.endswith("_default_keys.json")
            
            if os.path.exists(live_path) or is_user_data:
                return live_path
            
        # Fallback to internal bundled files
        return os.path.join(bundle_dir, relative_path)
    else:
        # Dev mode - absolute path from CWD
        return os.path.abspath(relative_path)

# Safe print for windowed mode
def print(*args, **kwargs):
    if sys.stdout is None:
        return
    try:
        import builtins
        builtins.print(*args, **kwargs)
    except:
        pass

class MacroRecorder:
    def __init__(self):
        self.events = []
        self.start_time = None
        self.last_event_time = None
        self.listener = None
        self.is_recording = False
        self.pressed_keys = set()

    def on_press(self, key):
        if not self.is_recording: return
        try:
            key_name = key.char if hasattr(key, 'char') and key.char else str(key).replace("Key.", "")
        except:
            key_name = str(key).replace("Key.", "")
        
        # Deduplicate OS-level repeat events
        if key_name in self.pressed_keys:
            return
        
        self.pressed_keys.add(key_name)
        self._record_event("down", key_name)

    def on_release(self, key):
        if not self.is_recording: return
        try:
            key_name = key.char if hasattr(key, 'char') and key.char else str(key).replace("Key.", "")
        except:
            key_name = str(key).replace("Key.", "")
            
        if key_name in self.pressed_keys:
            self.pressed_keys.remove(key_name)
            
        self._record_event("up", key_name)

    def _record_event(self, type, key_name):
        now = time.time()
        if self.start_time is None:
            self.start_time = now
            delay = 0
        else:
            delay = int((now - self.last_event_time) * 1000)
        
        self.last_event_time = now
        
        # If there's a significant gap, insert a dedicated delay event
        if delay > 5: # 5ms threshold to avoid tiny jitter events
            self.events.append({"type": "delay", "key": "WAIT", "delay": delay})
            
        self.events.append({"type": type, "key": key_name, "delay": 0})

    def start(self):
        self.events = []
        self.start_time = None
        self.last_event_time = None
        self.pressed_keys.clear()
        self.is_recording = True
        self.listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        self.listener.start()

    def stop(self):
        self.is_recording = False
        if self.listener:
            self.listener.stop()
        self.pressed_keys.clear()
        
        cleaned = self._clean_macro_events(self.events)
        return cleaned

    def _clean_macro_events(self, events):
        if not events: return []
        
        # 1. Merge adjacent delay events
        step1 = []
        current_delay = 0
        for ev in events:
            if ev["type"] == "delay":
                current_delay += ev["delay"]
            else:
                if current_delay > 0:
                    step1.append({"type": "delay", "key": "WAIT", "delay": current_delay})
                    current_delay = 0
                step1.append(ev)
        if current_delay > 0:
            step1.append({"type": "delay", "key": "WAIT", "delay": current_delay})
            
        # 2. Group simultaneous presses/releases
        # If multiple Downs or Ups happen with very small delays between them (< 50ms),
        # move the delay to the end of the cluster to create: [Down, Down], [Wait], [Up, Up]
        final_events = []
        i = 0
        while i < len(step1):
            ev = step1[i]
            
            if ev["type"] != "delay":
                # Start a cluster of same-type events (non-delay)
                cluster = [ev]
                cluster_type = ev["type"]
                j = i + 1
                total_cluster_delay = 0
                
                while j < len(step1):
                    next_ev = step1[j]
                    if next_ev["type"] == "delay" and next_ev["delay"] < 50:
                        total_cluster_delay += next_ev["delay"]
                        j += 1
                        if j < len(step1) and step1[j]["type"] != "delay":
                            cluster.append(step1[j])
                            j += 1
                        else: break
                    else: break
                
                # Add all keys in cluster first
                for c_ev in cluster:
                    final_events.append(c_ev)
                
                # Add combined delay if any
                if total_cluster_delay > 0:
                    final_events.append({"type": "delay", "key": "WAIT", "delay": total_cluster_delay})
                
                i = j
            else:
                final_events.append(ev)
                i += 1

        # 3. Final pass: ensure all key events have 0 delay field
        for ev in final_events:
            if ev["type"] != "delay":
                ev["delay"] = 0
                
        return final_events

class EditorApp(ctk.CTk):
    def __init__(self):
        # Set AppUserModelID to show taskbar icon correctly on Windows
        try:
            myappid = 'zencoder.tacticalcommanddeck.editor.v1'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception as e:
            print(f"[DEBUG] Could not set AppUserModelID: {e}")

        super().__init__()

        # Star Citizen HUD Colors
        self.sc_teal = "#00f5ff"
        self.sc_dark_teal = "#005f6b"
        self.sc_amber = "#ffb400"
        self.sc_bg = "#0a141a"
        self.sc_frame_bg = "#0f1f26"
        self.sc_header_bg = "#162a33"
        self.sc_border = "#2a4d5e"  # Slightly lighter for better visibility
        self.VERSION = "1.2"
        self.latest_download_url = None

        ctk.set_appearance_mode("dark")
        self.title(f"Tactical Command Deck - Editor v{self.VERSION}")
        self.geometry("1400x900")
        self.configure(fg_color=self.sc_bg)

        # Set App Icon
        icon_path = get_resource_path(os.path.join("editor", "assets", "tcd.png"))
        ico_path = get_resource_path(os.path.join("editor", "assets", "tcd.ico"))
        
        if os.path.exists(ico_path):
            try:
                self.iconbitmap(ico_path)
            except: pass

        if os.path.exists(icon_path):
            try:
                img = Image.open(icon_path)
                self.app_icon = ImageTk.PhotoImage(img)
                self._apply_icon()
            except Exception as e:
                print(f"[DEBUG] Could not set icon: {e}")

        self.init_logic()

    def _apply_icon(self, count=0):
        if not hasattr(self, 'app_icon'): return
        try:
            self.iconphoto(True, self.app_icon)
        except: pass
        if count < 10:
            self.after(500, lambda: self._apply_icon(count + 1))

    def init_logic(self):
        self.layout_path = get_resource_path("server/layout.json")
        self.layouts_dir = get_resource_path("server/layouts")
        self.assets_dir = get_resource_path("server/assets")
        self.settings_path = get_resource_path("server/editor_settings.json")
        
        if not os.path.exists(self.layouts_dir):
            os.makedirs(self.layouts_dir)
        if not os.path.exists(self.assets_dir):
            os.makedirs(self.assets_dir)
        
        self.layout_data = self.load_json(self.layout_path)
        self.settings_data = self.load_json(self.settings_path)
        
        # Merge actions into layout_data if it's the old format
        if "actions" not in self.layout_data:
            old_actions_path = get_resource_path("server/actions.json")
            self.layout_data["actions"] = self.load_json(old_actions_path)
        
        self.actions_data = self.layout_data.get("actions", {})
        
        # Load Game Control Lists dynamically
        self.game_controls = {}
        server_dir = get_resource_path("server")
        if os.path.exists(server_dir):
            for f in os.listdir(server_dir):
                if f.endswith("_default_keys.json"):
                    game_name = f.replace("_default_keys.json", "").replace("_", " ").title()
                    # Keep "Star Citizen" as is if it matches
                    if "Star Citizen" in game_name: game_name = "Star Citizen"
                    self.game_controls[game_name] = self.load_json(os.path.join(server_dir, f))
        
        if "layout_order" not in self.settings_data:
            self.settings_data["layout_order"] = self.settings_data.pop("template_order", []) if "template_order" in self.settings_data else []
        
        if "config" not in self.layout_data:
            self.layout_data["config"] = {"columns": 8, "rows": 6}
        
        if "pages" not in self.layout_data or not self.layout_data["pages"]:
            self.layout_data["pages"] = [{"name": "Page 1", "buttons": []}]
        
        for i, p in enumerate(self.layout_data["pages"]):
            if "name" not in p: p["name"] = f"Page {i+1}"

        self.selected_button_id = None
        self.current_page_index = 0
        self.base_cell_size = 70
        self.current_cell_size = 70
        self.drag_data = {"btn": None, "start_x": 0, "start_y": 0, "frame": None}
        self.button_widgets = {} # btn_id -> btn_frame
        
        self.resizing_btn_id = None
        self.resizing_widget = None
        self.start_mouse_pos = None
        self.start_btn_size = None
        self.resize_after_id = None
        
        self.recorder = MacroRecorder()
        self.recording_target = None
        self.macro_clipboard = None
        
        self.server_process = None
        self.server_thread = None
        self.last_menu_open_time = 0

        self.setup_ui()
        # Global mousewheel handler to ensure CTkScrollableFrames always scroll
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        
        # Global click handler to unfocus entries
        self.bind("<Button-1>", self.on_root_click)
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.start_server()
        self.check_for_updates()

    def check_for_updates(self):
        def _check():
            try:
                loc_path = get_resource_path("server/update_locations.txt")
                if not os.path.exists(loc_path): return
                
                version_url = None
                with open(loc_path, "r") as f:
                    for line in f:
                        if "VERSION CHECK" in line:
                            version_url = line.split('"')[1]
                            break
                
                if not version_url: return
                
                # Direct export link for Google Docs
                if "docs.google.com/document" in version_url:
                    doc_id = version_url.split("/d/")[1].split("/")[0]
                    version_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
                
                req = urllib.request.Request(version_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    web_data = response.read().decode('utf-8', errors='ignore').strip()
                    # Extract version number (e.g., 1.2)
                    v_match = re.search(r'([\d.]+)', web_data)
                    if v_match:
                        web_version = v_match.group(1)
                        # Extract a URL if one follows (e.g. http://...)
                        u_match = re.search(r'(https?://[^\s\n]+)', web_data)
                        if u_match:
                            self.latest_download_url = u_match.group(1)
                            print(f"[EDITOR] Found remote download URL: {self.latest_download_url}")
                    else:
                        web_version = web_data.splitlines()[0].replace("v", "").strip()
                    
                if web_version != self.VERSION:
                    self.after(0, lambda v=web_version: self.show_update_available(v))
            except Exception as e:
                print(f"[DEBUG] Update check failed: {e}")

        threading.Thread(target=_check, daemon=True).start()

    def show_update_available(self, new_version):
        for widget in self.update_banner.winfo_children():
            widget.destroy()
            
        btn = ctk.CTkButton(self.update_banner, text=f"UPDATE AVAILABLE (v{new_version})", 
                           fg_color="#22aa22", hover_color="#33cc33", text_color="white",
                           font=ctk.CTkFont(weight="bold"), height=30,
                           command=lambda: self.confirm_download(new_version))
        btn.pack(pady=5)

    def confirm_download(self, new_version):
        if messagebox.askyesno("Update", f"New version v{new_version} is available. Download now?"):
            self.download_update()

    def download_update(self):
        def _download():
            try:
                # Use remote URL if found during version check, else fallback to local file
                download_url = self.latest_download_url
                
                if not download_url:
                    loc_path = get_resource_path("server/update_locations.txt")
                    with open(loc_path, "r") as f:
                        for line in f:
                            if 'TCD "' in line:
                                download_url = line.split('"')[1]
                                break
                
                if not download_url:
                    print("[EDITOR] Error: No download URL found.")
                    return

                # Pixeldrain direct link auto-conversion
                if "pixeldrain.com/u/" in download_url:
                    download_url = download_url.replace("/u/", "/api/file/")
                    print(f"[EDITOR] Using Pixeldrain API link: {download_url}")

                # GitHub Release auto-conversion (to direct download)
                if "github.com" in download_url and "/releases/" in download_url:
                    if "/download/" not in download_url:
                        # Convert https://github.com/user/repo/releases/tag/v1.0 
                        # to a best-guess download link if possible, or just log it
                        print(f"[EDITOR] GitHub Release detected. Ensure you use the 'Direct Download' link for the ZIP asset.")

                # Google Drive direct link logic
                if "drive.google.com" in download_url and "confirm=" not in download_url:
                    if "/file/d/" in download_url:
                        doc_id = download_url.split("/file/d/")[1].split("/")[0]
                        download_url = f"https://drive.google.com/uc?export=download&id={doc_id}"
                
                print(f"[EDITOR] Final Download URL: {download_url}")
                
                filename = "TCD_Update.zip"
                # Use the folder where the app is located
                if getattr(sys, 'frozen', False):
                    base_path = os.path.dirname(sys.executable)
                    if os.path.basename(base_path).lower() == "_internal":
                        base_path = os.path.dirname(base_path)
                else:
                    base_path = os.getcwd()
                    
                target_path = os.path.join(base_path, filename)
                print(f"[EDITOR] Target Save Path: {target_path}")
                
                def download_with_gd_check(url, path):
                    print(f"[EDITOR] Requesting URL...")
                    
                    # Create a cookie processor to handle Google's "I've seen the warning" cookie
                    cookie_jar = urllib.request.HTTPCookieProcessor()
                    opener = urllib.request.build_opener(cookie_jar)
                    opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
                    
                    try:
                        with opener.open(url, timeout=30) as response:
                            content_sample = response.read(32768) 
                            sample_text = content_sample.decode('utf-8', errors='ignore')
                            
                            if "confirm=" in sample_text:
                                token = None
                                match = re.search(r'confirm=([a-zA-Z0-9_-]+)', sample_text)
                                if match: token = match.group(1)
                                if not token:
                                    match = re.search(r'name="confirm"\s+value="([a-zA-Z0-9_-]+)"', sample_text)
                                    if match: token = match.group(1)

                                if token:
                                    separator = "&" if "?" in url else "?"
                                    new_url = url + f"{separator}confirm={token}"
                                    print(f"[EDITOR] Bypassing Google Drive warning (Session active)...")
                                    # Use the SAME opener to keep the cookies
                                    with opener.open(new_url, timeout=30) as final_response:
                                        print(f"[EDITOR] Verified ZIP header. Starting stream to disk...")
                                        with open(path, 'wb') as out_file:
                                            # We don't need the sample here because this is the fresh final response
                                            chunk_size = 1024 * 1024
                                            while True:
                                                chunk = final_response.read(chunk_size)
                                                if not chunk: break
                                                out_file.write(chunk)
                                            out_file.flush()
                                            os.fsync(out_file.fileno())
                                    return

                            # If no confirm token, check if the sample we already read is the ZIP
                            if content_sample.startswith(b'PK'):
                                print(f"[EDITOR] Verified ZIP header. Starting stream to disk...")
                                with open(path, 'wb') as out_file:
                                    out_file.write(content_sample)
                                    chunk_size = 1024 * 1024
                                    while True:
                                        chunk = response.read(chunk_size)
                                        if not chunk: break
                                        out_file.write(chunk)
                                    out_file.flush()
                                    os.fsync(out_file.fileno())
                            else:
                                print(f"[EDITOR] Error: Received HTML instead of ZIP.")
                                raise Exception("Google Drive blocked the direct download. Check the link sharing settings.")
                    except Exception as e:
                        raise e

                download_with_gd_check(download_url, target_path)
                
                print(f"[EDITOR] Download complete!")
                self.after(0, lambda: self.prompt_apply_update(target_path))
            except Exception as err:
                # Capture 'err' in lambda to avoid NameError
                print(f"[EDITOR] Download failed: {err}")
                self.after(0, lambda e=err: messagebox.showerror("Error", f"Download failed: {e}"))

        threading.Thread(target=_download, daemon=True).start()

    def prompt_apply_update(self, zip_path):
        if messagebox.askyesno("Success", "Update downloaded successfully. Apply now?\n\n(This will close the application)"):
            self.apply_update(zip_path)
            
    def apply_update(self, zip_path):
        try:
            # 1. Locate updater.exe
            # It should be next to the EXE or in the root
            if getattr(sys, 'frozen', False):
                exe_dir = os.path.dirname(sys.executable)
                # If we are in _internal, go up one level
                if os.path.basename(exe_dir).lower() == "_internal":
                    exe_dir = os.path.dirname(exe_dir)
                
                updater_exe = os.path.join(exe_dir, "updater.exe")
                main_exe_name = os.path.basename(sys.executable)
                target_dir = exe_dir
            else:
                # Dev mode - use python to run updater.py
                updater_exe = sys.executable # python.exe
                script_path = os.path.abspath("updater.py")
                main_exe_name = "main.py" # In dev, we can't really "restart" easily the same way
                target_dir = os.getcwd()
                
                # For dev mode, we adjust arguments to call python updater.py ...
                cmd = [updater_exe, script_path, zip_path, target_dir, main_exe_name]
                subprocess.Popen(cmd, shell=True)
                self.on_closing()
                return

            if not os.path.exists(updater_exe):
                messagebox.showerror("Error", f"Updater not found at: {updater_exe}")
                return

            # 2. Launch updater
            # args: zip_path, target_dir, exe_name
            cmd = [updater_exe, zip_path, target_dir, main_exe_name]
            subprocess.Popen(cmd, shell=True)
            
            # 3. Exit main app
            self.on_closing()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to launch updater: {e}")

    def on_closing(self):
        self.stop_server()
        self.destroy()
        sys.exit(0)

    def record_menu_open(self, event=None):
        self.last_menu_open_time = time.time()

    def check_menu_cooldown(self):
        return (time.time() - self.last_menu_open_time) > 0.2

    def _on_mousewheel(self, event):
        """ Global mousewheel handler to ensure CTkScrollableFrames always scroll """
        widget = event.widget
        # Find the parent scrollable frame if any
        while widget:
            if isinstance(widget, ctk.CTkScrollableFrame):
                # CustomTkinter uses internal canvas for scrolling
                canvas = widget._parent_canvas
                if canvas:
                    canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                return
            try: widget = widget.master
            except: break

    def on_root_click(self, event):
        # If we clicked a widget that isn't an entry or textbox, clear focus
        # This prevents the label box from keeping focus when clicking on the grid
        if not isinstance(event.widget, (ctk.CTkEntry, tk.Entry, ctk.CTkTextbox, tk.Text)):
            self.focus_set()

    def load_json(self, path):
        if os.path.exists(path):
            with open(path, "r") as f:
                try: return json.load(f)
                except: return {}
        return {}

    def save_json(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def save_layout(self):
        self.layout_data["actions"] = self.actions_data
        self.save_json(self.layout_path, self.layout_data)
        
        # Mirror to the active layout file for the server/android app
        active_path = get_resource_path("server/layout.json")
        if os.path.abspath(self.layout_path) != os.path.abspath(active_path):
            self.save_json(active_path, self.layout_data)

    def setup_ui(self):
        # Main Layout Container to allow switching between Editor and Terminal
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True)
        
        self.editor_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.editor_frame.pack(fill="both", expand=True)
        
        self.editor_frame.grid_columnconfigure(0, weight=0, minsize=350)
        self.editor_frame.grid_columnconfigure(1, weight=1)
        self.editor_frame.grid_columnconfigure(2, weight=0, minsize=400)
        self.editor_frame.grid_rowconfigure(0, weight=1)
        # Row 1 removed (was bottom bar)

        page = self.layout_data["pages"][self.current_page_index]
        self.cols_var = ctk.StringVar(value=str(page.get("columns", self.layout_data["config"].get("columns", 8))))
        self.rows_var = ctk.StringVar(value=str(page.get("rows", self.layout_data["config"].get("rows", 6))))

        # --- LEFT PANEL ---
        self.left_panel = ctk.CTkFrame(self.editor_frame, fg_color=self.sc_frame_bg, border_width=1, border_color=self.sc_border)
        self.left_panel.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")
        self.left_panel.bind("<Configure>", lambda e: self.after(50, self.refresh_layouts_list))
        ctk.CTkLabel(self.left_panel, text="Layout Library", text_color=self.sc_teal, font=ctk.CTkFont(size=18, weight="bold")).pack(pady=10)
        
        # New Layout Button
        btn_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        
        ctk.CTkButton(btn_frame, text="+ NEW", fg_color=self.sc_dark_teal, hover_color=self.sc_teal, text_color="white", command=self.create_new_layout, width=150).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame, text="IMPORT", fg_color=self.sc_header_bg, border_width=1, border_color=self.sc_border, hover_color=self.sc_teal, text_color="white", command=self.import_layout, width=150).pack(side="right", padx=2)

        self.layout_scroll = ctk.CTkScrollableFrame(self.left_panel, fg_color=self.sc_bg)
        self.layout_scroll.pack(fill="both", expand=True, padx=5, pady=5)
        self.refresh_layouts_list()

        tool_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        tool_frame.pack(fill="x", side="bottom", pady=10, padx=10)
        ctk.CTkButton(tool_frame, text="SAVE AS LAYOUT", fg_color=self.sc_dark_teal, hover_color=self.sc_teal, text_color="white", command=self.save_as_layout).pack(fill="x", pady=5)

        # --- MIDDLE PANEL ---
        self.middle_panel = ctk.CTkFrame(self.editor_frame, fg_color=self.sc_bg)
        self.middle_panel.grid(row=0, column=1, padx=5, pady=10, sticky="nsew")
        self.middle_panel.bind("<Configure>", self.on_panel_resize)
        
        # Update Banner Frame at top of middle panel
        self.update_banner = ctk.CTkFrame(self.middle_panel, fg_color="transparent", height=40)
        self.update_banner.pack(fill="x", side="top")
        self.update_banner.pack_propagate(False)
        
        self.grid_container = ctk.CTkFrame(self.middle_panel, fg_color="transparent")
        self.grid_container.pack(expand=True)
        self.refresh_visual_grid()

        # --- RIGHT PANEL ---
        self.right_panel = ctk.CTkFrame(self.editor_frame, fg_color=self.sc_frame_bg, border_width=1, border_color=self.sc_border)
        self.right_panel.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")
        
        # Terminal & About Buttons in top right
        top_btn_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        top_btn_frame.pack(anchor="ne", padx=10, pady=10)

        ctk.CTkButton(top_btn_frame, text="ABOUT", width=80, height=25, 
                     fg_color=self.sc_header_bg, border_width=1, border_color=self.sc_border,
                     hover_color=self.sc_teal, font=ctk.CTkFont(size=10, weight="bold"),
                     command=self.show_about).pack(side="right", padx=2)

        self.term_btn = ctk.CTkButton(top_btn_frame, text="TERMINAL", width=80, height=25, 
                                     fg_color=self.sc_header_bg, border_width=1, border_color=self.sc_border,
                                     hover_color=self.sc_teal, font=ctk.CTkFont(size=10, weight="bold"),
                                     command=self.show_terminal)
        self.term_btn.pack(side="right", padx=2)

        self.right_tabs = ctk.CTkTabview(self.right_panel, fg_color="transparent", text_color="white")
        self.right_tabs.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.right_tabs.add("Grid")
        self.right_tabs.add("Button")
        self.right_tabs.add("Pages")
        
        # --- GRID TAB ---
        grid_tab = self.right_tabs.tab("Grid")
        ctk.CTkLabel(grid_tab, text="Grid Configuration", text_color=self.sc_teal, font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)
        ctk.CTkEntry(grid_tab, textvariable=self.cols_var, fg_color=self.sc_bg, border_color=self.sc_border).pack(padx=20, pady=2, fill="x")
        ctk.CTkEntry(grid_tab, textvariable=self.rows_var, fg_color=self.sc_bg, border_color=self.sc_border).pack(padx=20, pady=2, fill="x")
        ctk.CTkButton(grid_tab, text="Update Grid", fg_color=self.sc_dark_teal, hover_color=self.sc_teal, command=self.update_grid_config).pack(padx=20, pady=10)
        
        ctk.CTkLabel(grid_tab, text="Background", text_color=self.sc_teal, font=ctk.CTkFont(size=14)).pack(pady=(10, 0))
        self.bg_btn = ctk.CTkButton(grid_tab, text="Change BG Image", fg_color=self.sc_header_bg, border_width=1, border_color=self.sc_border, command=self.pick_background_image)
        self.bg_btn.pack(padx=20, pady=5, fill="x")
        ctk.CTkButton(grid_tab, text="Clear BG", fg_color="#662222", hover_color="#aa2222", command=self.clear_background_image).pack(padx=20, pady=2, fill="x")

        # --- BUTTON TAB ---
        button_tab = self.right_tabs.tab("Button")
        ctk.CTkLabel(button_tab, text="Button Properties", text_color=self.sc_teal, font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(20, 10))
        self.prop_container = ctk.CTkScrollableFrame(button_tab, fg_color="transparent")
        self.prop_container.pack(fill="both", expand=True)
        self.no_selection_label = ctk.CTkLabel(self.prop_container, text="Select a button to edit")
        self.no_selection_label.pack(pady=50)

        # --- PAGES TAB ---
        pages_tab = self.right_tabs.tab("Pages")
        ctk.CTkButton(pages_tab, text="NEW PAGE", fg_color=self.sc_dark_teal, hover_color=self.sc_teal, command=self.add_new_page).pack(fill="x", pady=10, padx=10)
        self.pages_list_frame = ctk.CTkScrollableFrame(pages_tab, fg_color="transparent")
        self.pages_list_frame.pack(fill="both", expand=True)
        self.refresh_pages_list()

        self.server_status_var = ctk.StringVar(value="Server Offline")
        # Bottom bar UI removed

        self.setup_terminal_view()
        self.setup_about_view()

    def setup_about_view(self):
        self.about_frame = ctk.CTkFrame(self.main_container, fg_color=self.sc_bg)
        
        # Header with Back button
        header = ctk.CTkFrame(self.about_frame, fg_color=self.sc_header_bg, height=50)
        header.pack(fill="x")
        
        ctk.CTkLabel(header, text="ABOUT TCD", text_color=self.sc_teal, font=ctk.CTkFont(size=18, weight="bold")).pack(side="left", padx=20)
        
        ctk.CTkButton(header, text="BACK TO EDITOR", fg_color=self.sc_dark_teal, hover_color=self.sc_teal, 
                      command=self.show_editor).pack(side="right", padx=20, pady=10)

        # About Content
        self.about_text = ctk.CTkTextbox(self.about_frame, fg_color="#050a0d", text_color=self.sc_teal, 
                                        font=ctk.CTkFont(family="Consolas", size=21), border_width=1, border_color=self.sc_border)
        self.about_text.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Load content from about.txt
        about_path = get_resource_path("server/about.txt")
        content = "No about information found."
        if os.path.exists(about_path):
            with open(about_path, "r") as f:
                content = f.read()
        
        # Replace [VERSION] if applicable
        if hasattr(self, 'title'):
            import re
            title = self.title()
            match = re.search(r"v([\d.]+)", title)
            if match:
                content = content.replace("[VERSION]", match.group(1))

        self.about_text.insert("0.0", content)
        self.about_text.configure(state="disabled")

    def setup_terminal_view(self):
        self.terminal_frame = ctk.CTkFrame(self.main_container, fg_color=self.sc_bg)
        
        # Header with Back button
        header = ctk.CTkFrame(self.terminal_frame, fg_color=self.sc_header_bg, height=50)
        header.pack(fill="x")
        
        ctk.CTkLabel(header, text="SYSTEM TERMINAL", text_color=self.sc_teal, font=ctk.CTkFont(size=18, weight="bold")).pack(side="left", padx=20)
        
        ctk.CTkButton(header, text="BACK TO EDITOR", fg_color=self.sc_dark_teal, hover_color=self.sc_teal, 
                      command=self.show_editor).pack(side="right", padx=20, pady=10)

        # Terminal Text Area
        self.terminal_text = ctk.CTkTextbox(self.terminal_frame, fg_color="#050a0d", text_color=self.sc_teal, 
                                           font=ctk.CTkFont(family="Consolas", size=18), border_width=1, border_color=self.sc_border)
        self.terminal_text.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Ensure it's selectable but blocked from typing
        self.terminal_text.configure(state="normal")
        self.terminal_text._textbox.configure(state="normal")
        self.terminal_text.bind("<Key>", lambda e: "break")
        self.terminal_text._textbox.bind("<Key>", lambda e: "break")
        
        # Explicitly set the text cursor to indicate it's selectable
        self.terminal_text._textbox.configure(cursor="ibeam")
        
        # Add right-click copy menu
        self.term_menu = tk.Menu(self, tearoff=0, bg=self.sc_header_bg, fg=self.sc_teal)
        self.term_menu.add_command(label="Copy Selected", command=self.copy_terminal_selection)
        self.term_menu.add_command(label="Copy All", command=self.copy_all_terminal)
        
        self.terminal_text.bind("<Button-3>", self.show_terminal_menu)
        self.terminal_text._textbox.bind("<Button-3>", self.show_terminal_menu)
        
        # Setup tags for gold highlighting (HUD Amber)
        # CTkTextbox is a wrapper around tk.Text
        self.terminal_text._textbox.tag_config("gold", foreground=self.sc_amber)

        # Redirect stdout
        self.old_stdout = sys.stdout
        sys.stdout = self

    def write(self, text):
        self.log_to_terminal(text)
        if self.old_stdout:
            self.old_stdout.write(text)

    def flush(self):
        if self.old_stdout:
            self.old_stdout.flush()

    def show_terminal_menu(self, event):
        self.term_menu.post(event.x_root, event.y_root)

    def copy_terminal_selection(self):
        try:
            text = self.terminal_text.get("sel.first", "sel.last")
            self.clipboard_clear()
            self.clipboard_append(text)
        except: pass

    def copy_all_terminal(self):
        text = self.terminal_text.get("0.0", "end")
        self.clipboard_clear()
        self.clipboard_append(text)

    def log_to_terminal(self, message):
        if hasattr(self, 'terminal_text'):
            # Ensure message ends with exactly one newline
            msg = message.rstrip() + "\n"
            
            # Partial gold patterns (Match Prefix, Value, and Suffix)
            pairing_match = re.search(r'(.*?PAIRING CODE:\s*)(\d+)(.*)', msg)
            ip_match = re.search(r'(.*?Local IP:\s*)(\d+\.\d+\.\d+\.\d+)(.*)', msg)
            
            if pairing_match:
                self.terminal_text.insert("end", pairing_match.group(1))
                self.terminal_text.insert("end", pairing_match.group(2), "gold")
                self.terminal_text.insert("end", pairing_match.group(3))
            elif ip_match:
                self.terminal_text.insert("end", ip_match.group(1))
                self.terminal_text.insert("end", ip_match.group(2), "gold")
                self.terminal_text.insert("end", ip_match.group(3))
            else:
                # Full line gold keywords (for Bug Fixes section and separators)
                is_separator = re.match(r'^-+$', msg.strip())
                if "Bug Fixes" in msg or is_separator:
                    self.terminal_text.insert("end", msg, "gold")
                else:
                    self.terminal_text.insert("end", msg)
            
            self.terminal_text.see("end")

    def show_terminal(self):
        self.editor_frame.pack_forget()
        self.about_frame.pack_forget()
        self.terminal_frame.pack(fill="both", expand=True)

    def show_about(self):
        # Refresh content from file in case it was edited
        about_path = get_resource_path("server/about.txt")
        if os.path.exists(about_path):
            with open(about_path, "r") as f:
                content = f.read()
            
            # Replace [VERSION] if applicable
            title = self.title()
            match = re.search(r"v([\d.]+)", title)
            if match:
                content = content.replace("[VERSION]", match.group(1))

            self.about_text.configure(state="normal")
            self.about_text.delete("0.0", "end")
            self.about_text.insert("0.0", content)
            self.about_text.configure(state="disabled")

        self.editor_frame.pack_forget()
        self.terminal_frame.pack_forget()
        self.about_frame.pack(fill="both", expand=True)

    def show_editor(self):
        self.terminal_frame.pack_forget()
        self.about_frame.pack_forget()
        self.editor_frame.pack(fill="both", expand=True)

    def start_server(self):
        try:
            # First, kill any orphan server running on port 5000
            if os.name == 'nt':
                try:
                    output = subprocess.check_output('netstat -ano | findstr :5000', shell=True).decode()
                    for line in output.splitlines():
                        if "LISTENING" in line:
                            pid = line.strip().split()[-1]
                            if pid != "0":
                                subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
                except: pass

            # Handle frozen (EXE) vs source script
            if getattr(sys, 'frozen', False):
                # When frozen, run the same EXE but with a flag
                server_args = [sys.executable, "--server"]
            else:
                server_args = [sys.executable, "server/main.py"]

            self.server_process = subprocess.Popen(
                server_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            self.server_status_var.set("Starting Server...")
            
            # Start thread to read output
            self.server_thread = threading.Thread(target=self.read_server_output, daemon=True)
            self.server_thread.start()
        except Exception as e:
            self.server_status_var.set(f"Error starting server: {e}")

    def stop_server(self):
        if self.server_process:
            pid = self.server_process.pid
            # Be aggressive on Windows to ensure process tree is killed
            if os.name == 'nt':
                subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, capture_output=True)
            else:
                self.server_process.terminate()
            
            self.server_process = None
            self.server_status_var.set("Server Offline")

    def read_server_output(self):
        if not self.server_process: return
        try:
            for line in iter(self.server_process.stdout.readline, ''):
                # Handle potential multi-line strings
                for subline in line.splitlines():
                    clean_line = subline.strip()
                    if not clean_line: continue
                    
                    # Determine if we should prefix this line
                    server_markers = ["PAIRING CODE", "[SERVER]", "[LISTENING]", "[AUTH]", "Local IP", "[ERROR]", "[WARNING]", "[FATAL ERROR]"]
                    use_prefix = any(m in clean_line for m in server_markers)
                    
                    prefix = "[SERVER LOG] " if use_prefix else ""
                    full_line = f"{prefix}{clean_line}\n"
                    
                    # Capture the pairing code specifically or other important info for status bar
                    if any(k in clean_line for k in ["PAIRING CODE", "Server is ready", "LISTENING", "Local IP"]):
                        self.after(0, lambda l=clean_line: self.server_status_var.set(l))
                        
                    # Log to terminal frame
                    self.after(0, lambda l=full_line: self.log_to_terminal(l))
                    
                    # Also log to real stdout for debugging
                    if self.old_stdout:
                        self.old_stdout.write(full_line)
                        self.old_stdout.flush()
        except Exception as e:
            print(f"[EDITOR] Error reading server output: {e}")
        finally:
            self.after(0, lambda: self.server_status_var.set("Server Offline"))
            self.server_process = None

    def refresh_layouts_list(self):
        if not hasattr(self, 'layout_scroll'): return
        for widget in self.layout_scroll.winfo_children(): widget.destroy()
        
        # Sync layout_order with files on disk
        all_files = [f for f in os.listdir(self.layouts_dir) if f.endswith(".json")]
        current_order = self.settings_data.get("layout_order", [])
        
        # Remove files that no longer exist
        current_order = [f for f in current_order if f in all_files]
        # Add new files
        for f in all_files:
            if f not in current_order:
                current_order.append(f)
        
        self.settings_data["layout_order"] = current_order
        self.save_settings()
        
        # Calculate dynamic width for preview card (max 280)
        avail_w = self.layout_scroll.winfo_width() - 40 # Padding
        preview_w = min(280, max(100, avail_w))
        
        for i, f in enumerate(current_order):
            path = os.path.join(self.layouts_dir, f)
            t_data = self.load_json(path)
            
            card = ctk.CTkFrame(self.layout_scroll, fg_color=self.sc_frame_bg, border_width=1, border_color=self.sc_border)
            card.pack(fill="x", pady=5, padx=5)
            
            header_frame = ctk.CTkFrame(card, fg_color="transparent")
            header_frame.pack(fill="x", pady=(5, 0), padx=5)
            
            ctk.CTkLabel(header_frame, text=f.replace(".json", ""), text_color="white", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
            
            # Reorder Buttons
            reorder_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
            reorder_frame.pack(side="right")
            
            ctk.CTkButton(reorder_frame, text="▲", width=25, height=25, fg_color=self.sc_header_bg, hover_color=self.sc_teal,
                           command=lambda idx=i: self.move_layout_up(idx)).pack(side="left", padx=1)
            ctk.CTkButton(reorder_frame, text="▼", width=25, height=25, fg_color=self.sc_header_bg, hover_color=self.sc_teal,
                           command=lambda idx=i: self.move_layout_down(idx)).pack(side="left", padx=1)
            
            t_cols = t_data.get("config", {}).get("columns", 8)
            t_rows = t_data.get("config", {}).get("rows", 6)
            
            aspect = t_rows / t_cols
            preview_h = int(preview_w * aspect)
            
            preview = ctk.CTkFrame(card, width=preview_w, height=preview_h, fg_color="#0a0a0a", corner_radius=0)
            preview.pack(pady=10, padx=10)
            preview.grid_propagate(False)
            preview.pack_propagate(False)
            
            sc = preview_w / t_cols
            
            # --- Draw Layout BG ---
            page_0 = t_data["pages"][0] if "pages" in t_data and t_data["pages"] else {}
            bg_raw = page_0.get("background_image", t_data.get("config", {}).get("background_image"))
            if bg_raw:
                bg_raw = bg_raw.replace("\\", "/")
                bg_path = None
                if os.path.exists(bg_raw): bg_path = bg_raw
                else:
                    clean_name = os.path.basename(bg_raw)
                    for d in [self.assets_dir, "editor/pngs", "editor/placeholder_buttons"]:
                        p = os.path.join(d, clean_name).replace("\\", "/")
                        if os.path.exists(p): bg_path = p; break
                if bg_path:
                    try:
                        p_bg_img = Image.open(bg_path).convert("RGBA")
                        c_bg_img = ctk.CTkImage(light_image=p_bg_img, dark_image=p_bg_img, size=(preview_w, preview_h))
                        bg_lbl = ctk.CTkLabel(preview, image=c_bg_img, text="", width=preview_w, height=preview_h)
                        bg_lbl.place(x=0, y=0)
                    except: pass

            # --- Draw Layout Buttons ---
            if "pages" in t_data and t_data["pages"]:
                for btn in t_data["pages"][0].get("buttons", []):
                    r, c = btn["position"]; rs, cs = btn["size"]
                    p_btn = ctk.CTkFrame(preview, fg_color=btn.get("color", "#333333"), width=max(1, cs*sc-1), height=max(1, rs*sc-1), corner_radius=1, border_width=0)
                    p_btn.place(x=c*sc, y=r*sc)
                    
                    img_p = btn.get("image")
                    ph_p = os.path.join("editor/placeholder_buttons", f"{rs}x{cs}_placeholder_button.png")
                    final_p = img_p if img_p and os.path.exists(img_p) else (ph_p if os.path.exists(ph_p) else None)
                    if final_p:
                        try:
                            pi = Image.open(final_p)
                            ci = ctk.CTkImage(light_image=pi, dark_image=pi, size=(max(1, cs*sc-2), max(1, rs*sc-2)))
                            ctk.CTkLabel(p_btn, image=ci, text="").place(relx=0.5, rely=0.5, anchor="center")
                        except: pass
            
            # Bindings for the whole card
            def recursive_bind(widget, event, callback):
                if isinstance(widget, ctk.CTkButton): return # Don't override button clicks
                widget.bind(event, callback)
                for child in widget.winfo_children():
                    recursive_bind(child, event, callback)

            recursive_bind(card, "<Button-1>", lambda e, p=path: self.load_layout(p))
            recursive_bind(card, "<Button-3>", lambda e, p=path, n=f.replace(".json", ""): self.show_layout_context_menu(e, p, n))

    def save_settings(self):
        self.save_json(self.settings_path, self.settings_data)

    def move_layout_up(self, index):
        if index > 0:
            order = self.settings_data["layout_order"]
            order[index], order[index-1] = order[index-1], order[index]
            self.save_settings()
            self.refresh_layouts_list()

    def move_layout_down(self, index):
        order = self.settings_data["layout_order"]
        if index < len(order) - 1:
            order[index], order[index+1] = order[index+1], order[index]
            self.save_settings()
            self.refresh_layouts_list()

    def show_layout_context_menu(self, event, path, name):
        menu = tk.Menu(self, tearoff=0, bg=self.sc_header_bg, fg=self.sc_teal, activebackground=self.sc_dark_teal, activeforeground="white", borderwidth=1)
        menu.add_command(label=f"Rename '{name}'", command=lambda: self.rename_layout(path, name))
        menu.add_command(label=f"Export '{name}' (.tcd)", command=lambda: self.export_layout(path, name))
        menu.add_separator()
        menu.add_command(label=f"Delete '{name}'", command=lambda: self.delete_layout_file(path, name))
        menu.post(event.x_root, event.y_root)

    def rename_layout(self, path, old_name):
        from tkinter import simpledialog, messagebox
        new_name = simpledialog.askstring("Rename Layout", "Enter new name:", initialvalue=old_name)
        if new_name and new_name != old_name:
            new_path = os.path.join(self.layouts_dir, f"{new_name}.json")
            if os.path.exists(new_path):
                messagebox.showerror("Error", "A layout with that name already exists.")
                return
            try:
                os.rename(path, new_path)
                self.refresh_layouts_list()
            except Exception as e:
                messagebox.showerror("Error", f"Could not rename layout: {e}")

    def delete_layout_file(self, path, name):
        from tkinter import messagebox
        if messagebox.askyesno("Delete Layout", f"Are you sure you want to delete '{name}'?"):
            try:
                os.remove(path)
                self.refresh_layouts_list()
            except Exception as e:
                messagebox.showerror("Error", f"Could not delete layout: {e}")

    def save_as_layout(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Save As Layout")
        dialog.geometry("400x350")
        dialog.transient(self)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.winfo_y() + (self.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

        ctk.CTkLabel(dialog, text="Save Current Layout", font=ctk.CTkFont(size=16, weight="bold"), text_color=self.sc_teal).pack(pady=20)
        
        # Option to pick existing
        ctk.CTkLabel(dialog, text="Choose layout to overwrite:").pack(pady=(10, 0))
        existing_files = [f.replace(".json", "") for f in os.listdir(self.layouts_dir) if f.endswith(".json")]
        existing_var = ctk.StringVar(value="-- New Layout --")
        
        def on_existing_select(val):
            if val != "-- New Layout --":
                name_entry.delete(0, "end")
                name_entry.insert(0, val)

        dropdown = ScrollableOptionMenu(dialog, values=["-- New Layout --"] + sorted(existing_files), variable=existing_var, command=on_existing_select)
        dropdown.pack(pady=5, padx=20, fill="x")

        ctk.CTkLabel(dialog, text="OR enter new name:").pack(pady=(10, 0))
        name_entry = ctk.CTkEntry(dialog, placeholder_text="Layout Name")
        name_entry.pack(pady=5, padx=20, fill="x")

        def do_save():
            name = name_entry.get().strip()
            if name:
                path = os.path.join(self.layouts_dir, f"{name}.json")
                # Update the layout data before saving
                self.layout_data["actions"] = self.actions_data
                self.save_json(path, self.layout_data)
                self.refresh_layouts_list()
                self.load_layout(path) # Switch to the newly saved layout
                dialog.destroy()
            else:
                from tkinter import messagebox
                messagebox.showwarning("Warning", "Please enter a layout name.")

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=20)
        
        ctk.CTkButton(btn_frame, text="SAVE", fg_color=self.sc_dark_teal, hover_color=self.sc_teal, command=do_save, width=100).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="CANCEL", fg_color="#444444", command=dialog.destroy, width=100).pack(side="left", padx=10)

    def create_new_layout(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("New Layout")
        dialog.geometry("400x200")
        dialog.transient(self)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.winfo_y() + (self.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

        ctk.CTkLabel(dialog, text="Create New Layout", font=ctk.CTkFont(size=16, weight="bold"), text_color=self.sc_teal).pack(pady=10)
        
        ctk.CTkLabel(dialog, text="Enter Layout Name:").pack(pady=(10, 0))
        name_entry = ctk.CTkEntry(dialog, placeholder_text="New Layout Name")
        name_entry.pack(pady=5, padx=20, fill="x")

        def do_create():
            name = name_entry.get().strip()
            if not name:
                from tkinter import messagebox
                messagebox.showwarning("Warning", "Please enter a name for the new layout.")
                return
            
            path = os.path.join(self.layouts_dir, f"{name}.json")
            if os.path.exists(path):
                from tkinter import messagebox
                messagebox.showerror("Error", f"A layout named '{name}' already exists.")
                return
            
            # Create Default Layout Data
            default_layout = {
                "config": {
                    "columns": 8,
                    "rows": 6,
                    "background_image": "Default_bg.png"
                },
                "pages": [
                    {
                        "name": "Page 1",
                        "buttons": [],
                        "background_image": "Default_bg.png"
                    }
                ]
            }
            
            # Ensure Default_bg.png exists in assets or internal folders
            bg_target = os.path.join(self.assets_dir, "Default_bg.png")
            if not os.path.exists(bg_target):
                # Try to find it in internal folders
                found = False
                for d in ["editor/pngs", "editor/placeholder_buttons"]:
                    src = os.path.join(d, "Default_bg.png")
                    if os.path.exists(src):
                        shutil.copy2(src, bg_target)
                        found = True
                        break
            
            self.save_json(path, default_layout)
            self.refresh_layouts_list()
            self.load_layout(path)
            dialog.destroy()

        def do_import():
            dialog.destroy()
            self.import_layout()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=20)
        ctk.CTkButton(btn_frame, text="CREATE", fg_color=self.sc_dark_teal, hover_color=self.sc_teal, command=do_create, width=90).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="IMPORT", fg_color=self.sc_header_bg, border_width=1, border_color=self.sc_border, hover_color=self.sc_teal, text_color="white", command=do_import, width=90).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="CANCEL", fg_color="#444444", command=dialog.destroy, width=90).pack(side="left", padx=5)

    def refresh_pages_list(self):
        for widget in self.pages_list_frame.winfo_children(): widget.destroy()
        if "pages" not in self.layout_data: return
        
        for i, page in enumerate(self.layout_data["pages"]):
            name = page.get("name", f"Page {i+1}")
            is_active = (i == self.current_page_index)
            
            btn_color = self.sc_teal if is_active else self.sc_frame_bg
            txt_color = "black" if is_active else "white"
            
            p_frame = ctk.CTkFrame(self.pages_list_frame, fg_color=btn_color)
            p_frame.pack(fill="x", pady=2, padx=5)
            
            # Use columns for layout to allow for reorder buttons
            p_frame.grid_columnconfigure(0, weight=1)
            
            lbl = ctk.CTkLabel(p_frame, text=name, text_color=txt_color, font=ctk.CTkFont(weight="bold"))
            lbl.grid(row=0, column=0, pady=10, padx=(10, 0), sticky="w")
            
            # Reorder Buttons
            btn_frame = ctk.CTkFrame(p_frame, fg_color="transparent")
            btn_frame.grid(row=0, column=1, padx=5)
            
            up_btn = ctk.CTkButton(btn_frame, text="▲", width=25, height=25, fg_color=self.sc_header_bg, hover_color=self.sc_teal, 
                                   command=lambda idx=i: self.move_page_up(idx))
            up_btn.pack(side="left", padx=1)
            
            down_btn = ctk.CTkButton(btn_frame, text="▼", width=25, height=25, fg_color=self.sc_header_bg, hover_color=self.sc_teal, 
                                     command=lambda idx=i: self.move_page_down(idx))
            down_btn.pack(side="left", padx=1)
            
            # Bindings for switching and context menu
            lbl.bind("<Button-1>", lambda e, idx=i: self.switch_page(idx))
            lbl.bind("<Button-3>", lambda e, idx=i, n=name: self.show_page_context_menu(e, idx, n))
            p_frame.bind("<Button-1>", lambda e, idx=i: self.switch_page(idx))
            p_frame.bind("<Button-3>", lambda e, idx=i, n=name: self.show_page_context_menu(e, idx, n))

    def move_page_up(self, index):
        if index > 0:
            pages = self.layout_data["pages"]
            pages[index], pages[index-1] = pages[index-1], pages[index]
            if self.current_page_index == index:
                self.current_page_index = index - 1
            elif self.current_page_index == index - 1:
                self.current_page_index = index
            self.save_layout()
            self.refresh_pages_list()
            self.refresh_visual_grid()

    def move_page_down(self, index):
        pages = self.layout_data["pages"]
        if index < len(pages) - 1:
            pages[index], pages[index+1] = pages[index+1], pages[index]
            if self.current_page_index == index:
                self.current_page_index = index + 1
            elif self.current_page_index == index + 1:
                self.current_page_index = index
            self.save_layout()
            self.refresh_pages_list()
            self.refresh_visual_grid()

    def switch_page(self, index):
        self.current_page_index = index
        page = self.layout_data["pages"][self.current_page_index]
        self.cols_var.set(str(page.get("columns", self.layout_data["config"].get("columns", 8))))
        self.rows_var.set(str(page.get("rows", self.layout_data["config"].get("rows", 6))))
        self.refresh_visual_grid()
        self.refresh_pages_list()

    def show_page_context_menu(self, event, index, name):
        menu = tk.Menu(self, tearoff=0, bg=self.sc_header_bg, fg=self.sc_teal, activebackground=self.sc_dark_teal, activeforeground="white", borderwidth=1)
        menu.add_command(label=f"Rename '{name}'", command=lambda: self.rename_page(index, name))
        menu.add_command(label=f"Copy '{name}' to new page", command=lambda: self.copy_page(index))
        if len(self.layout_data["pages"]) > 1:
            menu.add_command(label=f"Delete '{name}'", command=lambda: self.delete_page(index, name))
        menu.post(event.x_root, event.y_root)

    def copy_page(self, index):
        from tkinter import simpledialog, messagebox
        new_name = simpledialog.askstring("Copy Page", "Enter new page name:")
        if not new_name: return
        
        # Check if name already exists
        if any(p.get("name") == new_name for p in self.layout_data["pages"]):
            messagebox.showerror("Error", "A page with that name already exists.")
            return

        source_page = self.layout_data["pages"][index]
        import copy
        # Deep copy the page data
        new_page = copy.deepcopy(source_page)
        new_page["name"] = new_name
        # Ensure new IDs for buttons if needed, but since server uses btn IDs globally 
        # and they are just triggered, we should probably generate new IDs to avoid conflicts
        # if the user edits one but not the other.
        for btn in new_page.get("buttons", []):
            old_id = btn["id"]
            new_id = f"BTN_{random.randint(1000, 9999)}"
            btn["id"] = new_id
            # Copy actions too
            if old_id in self.actions_data:
                self.actions_data[new_id] = copy.deepcopy(self.actions_data[old_id])

        self.layout_data["pages"].append(new_page)
        self.current_page_index = len(self.layout_data["pages"]) - 1
        self.save_layout()
        self.switch_page(self.current_page_index)

    def add_new_page(self):
        from tkinter import simpledialog
        name = simpledialog.askstring("New Page", "Enter page name:")
        if name:
            new_page = {
                "name": name,
                "columns": int(self.cols_var.get()),
                "rows": int(self.rows_var.get()),
                "buttons": []
            }
            self.layout_data["pages"].append(new_page)
            self.current_page_index = len(self.layout_data["pages"]) - 1
            self.save_layout()
            self.switch_page(self.current_page_index)

    def rename_page(self, index, old_name):
        from tkinter import simpledialog
        new_name = simpledialog.askstring("Rename Page", "Enter new name:", initialvalue=old_name)
        if new_name and new_name != old_name:
            self.layout_data["pages"][index]["name"] = new_name
            self.save_layout()
            self.refresh_pages_list()

    def delete_page(self, index, name):
        from tkinter import messagebox
        if messagebox.askyesno("Delete Page", f"Are you sure you want to delete page '{name}'? This will delete all its buttons and configuration."):
            self.layout_data["pages"].pop(index)
            if self.current_page_index >= len(self.layout_data["pages"]):
                self.current_page_index = len(self.layout_data["pages"]) - 1
            self.save_layout()
            self.switch_page(self.current_page_index)

    def load_layout(self, path):
        self.layout_path = path
        self.layout_data = self.load_json(path)
        self.actions_data = self.layout_data.get("actions", {})
        self.save_layout()
        self.current_page_index = 0
        if "pages" not in self.layout_data or not self.layout_data["pages"]:
            self.layout_data["pages"] = [{"name": "Page 1", "buttons": []}]
        
        # Ensure pages have names
        for i, p in enumerate(self.layout_data["pages"]):
            if "name" not in p: p["name"] = f"Page {i+1}"
            
        page = self.layout_data["pages"][self.current_page_index]
        self.cols_var.set(str(page.get("columns", self.layout_data["config"].get("columns", 8))))
        self.rows_var.set(str(page.get("rows", self.layout_data["config"].get("rows", 6))))
        self.refresh_visual_grid()
        self.refresh_pages_list()

    def on_panel_resize(self, event):
        if self.resize_after_id:
            self.after_cancel(self.resize_after_id)
        self.resize_after_id = self.after(50, self.refresh_visual_grid)

    def refresh_visual_grid(self):
        for widget in self.grid_container.winfo_children(): widget.destroy()
        cols, rows = int(self.cols_var.get()), int(self.rows_var.get())
        
        # Calculate dynamic cell size to fit window, capped at base_cell_size
        pad = 40
        avail_w = self.middle_panel.winfo_width() - pad
        avail_h = self.middle_panel.winfo_height() - pad
        
        if avail_w > 1 and avail_h > 1:
            self.current_cell_size = min(self.base_cell_size, avail_w // cols, avail_h // rows)
        else:
            self.current_cell_size = self.base_cell_size

        w_total, h_total = cols * self.current_cell_size, rows * self.current_cell_size
        self.grid_container.configure(width=w_total, height=h_total)
        
        # 1. Create Surface for Background and Clicks
        self.bg_surface = ctk.CTkFrame(self.grid_container, width=w_total, height=h_total, fg_color=self.sc_bg, corner_radius=0)
        self.bg_surface.place(x=0, y=0)
        self.bg_surface.bind("<Button-3>", self.on_bg_click)

        # Get background from current page, fallback to global
        page = self.layout_data["pages"][self.current_page_index]
        bg_raw = page.get("background_image", self.layout_data["config"].get("background_image"))
        line_color = "#3a5d6e" # Brighter teal for better visibility
        
        if bg_raw:
            bg_raw = bg_raw.replace("\\", "/")
            bg_path = get_resource_path(bg_raw)
            if not os.path.exists(bg_path):
                # Fallback to searching in known directories if the relative path isn't enough
                clean_name = os.path.basename(bg_raw)
                for d in [self.assets_dir, "editor/pngs", "editor/placeholder_buttons"]:
                    p = os.path.join(d, clean_name).replace("\\", "/")
                    if os.path.exists(p): bg_path = p; break

            if os.path.exists(bg_path):
                try:
                    pil_bg = Image.open(bg_path).convert("RGBA")
                    ctk_bg = ctk.CTkImage(light_image=pil_bg, dark_image=pil_bg, size=(w_total, h_total))
                    bg_img = ctk.CTkLabel(self.bg_surface, image=ctk_bg, text="", width=w_total, height=h_total)
                    bg_img.place(x=0, y=0)
                    bg_img.bind("<Button-3>", self.on_bg_click)
                    line_color = "#888888" # Much lighter lines if BG exists for visibility
                except Exception as e:
                    print(f"[ERROR] Failed to load background: {e}")

        # 2. Draw Grid Lines
        for c in range(cols + 1):
            line = ctk.CTkFrame(self.bg_surface, width=1, height=h_total, fg_color=line_color, corner_radius=0)
            line.place(x=c*self.current_cell_size, y=0)
            line.bind("<Button-3>", self.on_bg_click)
        for r in range(rows + 1):
            line = ctk.CTkFrame(self.bg_surface, height=1, width=w_total, fg_color=line_color, corner_radius=0)
            line.place(x=0, y=r*self.current_cell_size)
            line.bind("<Button-3>", self.on_bg_click)
        
        # 3. Draw Buttons on Top
        self.draw_buttons()

    def get_coords_relative_to(self, event, target):
        """ Robust coordinate calculation relative to a target widget, safer for DPI scaling """
        x, y = event.x, event.y
        w = event.widget
        # Walk up the widget tree until we hit the target
        try:
            while w and w != target:
                # Add current widget's position relative to its master
                x += w.winfo_x()
                y += w.winfo_y()
                w = w.master
                if w is None: break
        except: pass
        return x, y

    def on_bg_click(self, event):
        # Use robust relative coordinates
        gx, gy = self.get_coords_relative_to(event, self.grid_container)
        
        cols, rows = int(self.cols_var.get()), int(self.rows_var.get())
        c = int(gx // self.current_cell_size)
        r = int(gy // self.current_cell_size)
        
        if 0 <= c < cols and 0 <= r < rows:
            self.add_new_button_at(r, c, 1, 1)
        else:
            print(f"[DEBUG] Click out of bounds: {r},{c} (px: {gx},{gy})")

    def draw_buttons(self):
        self.button_widgets = {} # Reset map
        if "pages" in self.layout_data and self.layout_data["pages"]:
            page = self.layout_data["pages"][self.current_page_index]
            for btn in page.get("buttons", []):
                r, c = btn["position"]; rs, cs = btn["size"]
                w_pix, h_pix = cs * self.current_cell_size, rs * self.current_cell_size
                
                is_selected = (btn["id"] == self.selected_button_id)
                b_color = self.sc_teal if is_selected else "#000000"
                b_width = 3 if is_selected else 2
                
                btn_frame = ctk.CTkFrame(self.grid_container, fg_color=btn.get("color", "#333333"), corner_radius=8, border_width=b_width, border_color=b_color, width=w_pix-2, height=h_pix-2)
                btn_frame.place(x=c*self.current_cell_size+1, y=r*self.current_cell_size+1)
                btn_frame.pack_propagate(False)
                
                self.button_widgets[btn["id"]] = btn_frame

                img_path_raw = btn.get("image")
                img_path = get_resource_path(img_path_raw) if img_path_raw else None
                # Use button.png as default placeholder
                placeholder_path = os.path.join("editor/placeholder_buttons", "button.png")
                
                final_img = None
                if img_path and os.path.exists(img_path):
                    final_img = img_path
                else:
                    # Try searching by filename as fallback
                    if img_path_raw:
                        clean_name = os.path.basename(img_path_raw)
                        for d in [self.assets_dir, "editor/pngs"]:
                            p = os.path.join(d, clean_name).replace("\\", "/")
                            if os.path.exists(p): final_img = p; break
                    
                    if not final_img and os.path.exists(placeholder_path):
                        final_img = placeholder_path

                if final_img:
                    try:
                        pil_img = Image.open(final_img)
                        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(w_pix-4, h_pix-4))
                        # Use compound="center" to place text OVER image
                        lbl = ctk.CTkLabel(btn_frame, image=ctk_img, text=btn.get("label", ""), 
                                           text_color="white", font=ctk.CTkFont(weight="bold"), compound="center")
                    except: lbl = ctk.CTkLabel(btn_frame, text=btn.get("label", ""), text_color="white", font=ctk.CTkFont(weight="bold"))
                else: lbl = ctk.CTkLabel(btn_frame, text=btn.get("label", ""), text_color="white", font=ctk.CTkFont(weight="bold"))
                
                lbl.place(relx=0.5, rely=0.5, anchor="center")
                
                # Resize Handle (Bottom Right)
                resize_handle = ctk.CTkFrame(btn_frame, width=8, height=8, fg_color="white", corner_radius=2)
                resize_handle.place(relx=1.0, rely=1.0, x=-2, y=-2, anchor="center")
                resize_handle.configure(cursor="size_nw_se")
                
                # Drag Handle (Top Left)
                drag_handle = ctk.CTkFrame(btn_frame, width=10, height=10, fg_color=self.sc_teal, corner_radius=2)
                drag_handle.place(relx=0.0, rely=0.0, x=2, y=2, anchor="center")
                drag_handle.configure(cursor="fleur")

                # Bindings
                btn_frame.bind("<Button-1>", lambda e, b=btn: self.select_button(b))
                lbl.bind("<Button-1>", lambda e, b=btn: self.select_button(b))
                
                # Right Click to delete
                btn_frame.bind("<Button-3>", lambda e, b=btn: self.show_button_context_menu(e, b))
                lbl.bind("<Button-3>", lambda e, b=btn: self.show_button_context_menu(e, b))
                
                drag_handle.bind("<Button-1>", lambda e, b=btn, f=btn_frame: self.start_button_drag(e, b, f))
                drag_handle.bind("<B1-Motion>", self.do_button_drag)
                drag_handle.bind("<ButtonRelease-1>", self.stop_button_drag)

                resize_handle.bind("<Button-1>", lambda e, b=btn, f=btn_frame: self.start_resize(e, b, f))
                resize_handle.bind("<B1-Motion>", self.do_resize)
                resize_handle.bind("<ButtonRelease-1>", self.stop_resize)

    def start_button_drag(self, event, btn, btn_frame):
        self.select_button(btn)
        self.drag_data["btn"] = btn
        self.drag_data["frame"] = btn_frame
        # Calculate offset of mouse from button's top-left corner
        self.drag_data["start_x"], self.drag_data["start_y"] = self.get_coords_relative_to(event, btn_frame)
        btn_frame.lift()
        return "break"

    def do_button_drag(self, event):
        if not self.drag_data["btn"]: return
        f = self.drag_data["frame"]
        # New position relative to grid_container
        new_x, new_y = self.get_coords_relative_to(event, self.grid_container)
        new_x -= self.drag_data["start_x"]
        new_y -= self.drag_data["start_y"]
        f.place(x=new_x, y=new_y)

    def stop_button_drag(self, event):
        if not self.drag_data["btn"]: return
        btn = self.drag_data["btn"]
        f = self.drag_data["frame"]
        
        # Calculate final grid position relative to grid_container
        gx = f.winfo_x()
        gy = f.winfo_y()
        
        drop_c = round(gx / self.current_cell_size)
        drop_r = round(gy / self.current_cell_size)
        
        cols, rows = int(self.cols_var.get()), int(self.rows_var.get())
        rs, cs = btn["size"]
        btn["position"] = [max(0, min(rows-rs, drop_r)), max(0, min(cols-cs, drop_c))]
        
        self.drag_data["btn"] = None
        self.drag_data["frame"] = None
        self.save_layout()
        self.refresh_visual_grid()
        self.select_button(btn)

    def start_resize(self, event, btn, btn_frame):
        self.resizing_btn_id = btn["id"]
        self.resizing_widget = btn_frame
        # Use relative coords for start position
        self.start_mouse_pos = self.get_coords_relative_to(event, self.grid_container)
        self.start_btn_size = list(btn.get("size", [1, 1]))
        return "break"

    def do_resize(self, event):
        if not self.resizing_btn_id: return
        curr_pos = self.get_coords_relative_to(event, self.grid_container)
        dx, dy = curr_pos[0] - self.start_mouse_pos[0], curr_pos[1] - self.start_mouse_pos[1]
        new_rs, new_cs = max(1, self.start_btn_size[0] + round(dy / self.current_cell_size)), max(1, self.start_btn_size[1] + round(dx / self.current_cell_size))
        self.resizing_widget.configure(width=(new_cs * self.current_cell_size) - 2, height=(new_rs * self.current_cell_size) - 2)

    def stop_resize(self, event):
        if not self.resizing_btn_id: return
        curr_pos = self.get_coords_relative_to(event, self.grid_container)
        dx, dy = curr_pos[0] - self.start_mouse_pos[0], curr_pos[1] - self.start_mouse_pos[1]
        new_rs, new_cs = max(1, self.start_btn_size[0] + round(dy / self.current_cell_size)), max(1, self.start_btn_size[1] + round(dx / self.current_cell_size))
        page = self.layout_data["pages"][self.current_page_index]
        resized_btn = None
        for btn in page["buttons"]:
            if btn["id"] == self.resizing_btn_id:
                btn["size"] = [new_rs, new_cs]
                resized_btn = btn
                break
        self.resizing_btn_id = None
        self.save_layout()
        self.refresh_visual_grid()
        if resized_btn:
            self.select_button(resized_btn)

    def select_button(self, btn):
        is_new_selection = (self.selected_button_id != btn["id"])
        
        if is_new_selection:
            old_id = self.selected_button_id
            self.selected_button_id = btn["id"]
            
            # Update borders manually to avoid destructive refresh
            if old_id in self.button_widgets:
                try: self.button_widgets[old_id].configure(border_color="#000000", border_width=2)
                except: pass
                
            if self.selected_button_id in self.button_widgets:
                try: self.button_widgets[self.selected_button_id].configure(border_color=self.sc_teal, border_width=3)
                except: pass
            
            # Switch to Button tab
            self.right_tabs.set("Button")
            
            # Initialize temporary editing state for images
            self.edit_image_vars = {
                "image": btn.get("image"),
                "image_pressed": btn.get("image_pressed")
            }
        
        # Clear children before rebuilding panel
        for widget in self.prop_container.winfo_children():
            self.recursive_destroy(widget)
        
        self.label_entry = self.add_prop_field("Button Label", btn.get("label", ""))

        # Image previews (Move here, between Label and Game)
        img_frame = ctk.CTkFrame(self.prop_container, fg_color="transparent")
        img_frame.pack(pady=10, padx=20, fill="x")
        for i, field in enumerate(["image", "image_pressed"]):
            box = ctk.CTkFrame(img_frame, width=100, height=100, fg_color="#333333" if i==0 else "#222222", border_width=1)
            box.grid(row=0, column=i, padx=5); box.grid_propagate(False)
            
            path_raw = self.edit_image_vars.get(field)
            path = get_resource_path(path_raw) if path_raw else None
            
            is_default = False
            if path_raw:
                p_lower = path_raw.lower()
                is_default = "placeholder_buttons/button.png" in p_lower or "placeholder_buttons/button_press.png" in p_lower
            
            if path and os.path.exists(path) and not is_default:
                try:
                    p = Image.open(path); c = ctk.CTkImage(light_image=p, dark_image=p, size=(90, 90))
                    l = ctk.CTkLabel(box, image=c, text=""); l.place(relx=0.5, rely=0.5, anchor="center")
                    l.bind("<Button-1>", lambda e, f=field: self.pick_image(btn, f))
                except: pass
            else:
                l = ctk.CTkLabel(box, text=f"{field}\n(Click)", font=ctk.CTkFont(size=10)); l.place(relx=0.5, rely=0.5, anchor="center")
                l.bind("<Button-1>", lambda e, f=field: self.pick_image(btn, f))
            box.bind("<Button-1>", lambda e, f=field: self.pick_image(btn, f))

        # 1. Game Selection Dropdown
        game_frame = ctk.CTkFrame(self.prop_container, fg_color="transparent")
        game_frame.pack(pady=(10, 0), padx=20, fill="x")
        ctk.CTkLabel(game_frame, text="Game").pack(anchor="w")
        self.game_var = ctk.StringVar(value=btn.get("game", "None"))
        game_options = ["None"] + list(self.game_controls.keys())
        game_dropdown = ScrollableOptionMenu(game_frame, values=game_options, variable=self.game_var, 
                                          command=lambda v: self.on_game_change(v, btn))
        game_dropdown.pack(fill="x", pady=2)

        # 2. Control selection
        self.control_select_frame = ctk.CTkFrame(self.prop_container, fg_color="transparent")
        self.control_select_frame.pack(pady=5, padx=20, fill="x")
        self.category_var = ctk.StringVar(value="All Categories")
        self.control_var = ctk.StringVar(value="Select Control...")
        
        action_data = self.actions_data.get(btn["id"], {"on_press": {"type": "key", "value": ""}, "on_release": None})
        
        # 3. Press/Release UIs
        self.press_ui = self.create_action_ui("Button Press", "on_press", action_data.get("on_press"))
        self.release_ui = self.create_action_ui("Button Release", "on_release", action_data.get("on_release"))

        self.update_control_dropdown(btn) 

        # 4. Action Buttons (Bottom)
        ctk.CTkButton(self.prop_container, text="Save Button", command=lambda: self.save_button_props(btn)).pack(pady=20, padx=20, fill="x")

    def on_game_change(self, game, btn):
        if not self.check_menu_cooldown(): return
        print(f"[DEBUG] Game changed to: {game}")
        btn["game"] = game
        self.category_var.set("All Categories")
        self.update_control_dropdown(btn)

    def update_control_dropdown(self, btn):
        for w in self.control_select_frame.winfo_children():
            self.recursive_destroy(w)
        
        game = self.game_var.get()
        if game == "None" or game not in self.game_controls:
            return

        actions = self.game_controls[game].get("actions", [])
        categories = sorted(list(set(a.get("category", "general") for a in actions)))
        cat_options = ["All Categories"] + [c.replace("_", " ").title() for c in categories]

        ctk.CTkLabel(self.control_select_frame, text="Category").pack(anchor="w")
        self.category_dropdown = ScrollableOptionMenu(self.control_select_frame, values=cat_options, variable=self.category_var,
                                                   command=lambda v: self.update_action_dropdown_with_cooldown(v, btn))
        self.category_dropdown.pack(fill="x", pady=2)

        self.action_select_container = ctk.CTkFrame(self.control_select_frame, fg_color="transparent")
        self.action_select_container.pack(fill="x")
        self.update_action_dropdown(btn)

    def update_action_dropdown_with_cooldown(self, val, btn):
        if not self.check_menu_cooldown(): return
        self.update_action_dropdown(btn)

    def update_action_dropdown(self, btn):
        for w in self.action_select_container.winfo_children():
            self.recursive_destroy(w)

        game = self.game_var.get()
        selected_cat = self.category_var.get().lower().replace(" ", "_")
        actions = self.game_controls[game].get("actions", [])
        
        if selected_cat != "all_categories":
            filtered_actions = [a for a in actions if a.get("category", "general") == selected_cat]
        else:
            filtered_actions = actions

        ctk.CTkLabel(self.action_select_container, text="Quick Control").pack(anchor="w")
        labels = ["Select Control..."] + [a["label"] for a in filtered_actions]
        
        self.control_var.set("Select Control...")
        self.control_dropdown = ScrollableOptionMenu(self.action_select_container, values=labels, variable=self.control_var,
                                                  command=lambda v: self.on_control_change(v, game, btn))
        self.control_dropdown.pack(fill="x", pady=2)

    def on_control_change(self, label, game, btn):
        if not self.check_menu_cooldown(): return
        if label == "Select Control...": return
        
        actions = self.game_controls[game].get("actions", [])
        control = next((a for a in actions if a["label"] == label), None)
        if control:
            val = control["default"]
            # Force hold if label indicates it or for specific known hold actions
            label_low = label.lower()
            needs_hold = "hold" in label_low or "long press" in label_low or "quantum" in label_low
            
            # Clean junk from default value
            clean_val = val
            for junk in [" (Hold)", " (hold)", "(Hold)", "(hold)", " (Long Press)", " (long press)", "(Long Press)", "(long press)"]:
                clean_val = clean_val.replace(junk, "")
            
            if needs_hold and not clean_val.lower().startswith("hold"):
                clean_val = f"Hold {clean_val}"
            
            val = clean_val
            
            # Check for ranges like 1-9
            if "1-9" in val:
                num = simpledialog.askinteger("Select Key", f"Choose a number for '{label}' (1-9):", minvalue=1, maxvalue=9)
                if num is not None:
                    val = val.replace("1-9", str(num))
                else:
                    return # Cancelled
            
            # Parsing logic
            is_hold = False
            is_hold_tap = False
            v_low = val.lower()
            
            if "hold " in v_low and "tap " in v_low:
                is_hold_tap = True
                # Extract "X" from "Hold X" and "Y" from "Tap Y"
                # Format: "Hold F4 + Tap Numpad 1"
                parts = val.split("+")
                hold_key = parts[0].lower().replace("hold", "").strip()
                tap_key = parts[1].lower().replace("tap", "").strip()
            elif v_low.startswith("hold "):
                is_hold = True
                clean_key = val[5:].strip()
            elif v_low.startswith("toggle "):
                clean_key = val[7:].strip()
            else:
                clean_key = val
            
            if is_hold_tap:
                # Create specific sequence: Down(Hold), Delay, Down(Tap), Up(Tap), Up(Hold)
                macro_events = [
                    {"type": "down", "key": hold_key, "delay": 0},
                    {"type": "delay", "key": "WAIT", "delay": 200}, # Short delay to ensure hold is registered
                    {"type": "down", "key": tap_key, "delay": 0},
                    {"type": "delay", "key": "WAIT", "delay": 100}, # Key tap duration
                    {"type": "up", "key": tap_key, "delay": 0},
                    {"type": "delay", "key": "WAIT", "delay": 100},
                    {"type": "up", "key": hold_key, "delay": 0}
                ]
                self.press_ui["type"].set("macro")
                self.update_action_fields("macro", {"type": "macro", "events": macro_events}, self.press_ui)
            elif is_hold:
                # Create macro: Down(s), 3s delay, Up(s)
                keys_to_hold = [k.strip() for k in clean_key.split("+") if k.strip()]
                macro_events = []
                # All down
                for k in keys_to_hold:
                    macro_events.append({"type": "down", "key": k, "delay": 0})
                
                # Separate Delay event
                macro_events.append({"type": "delay", "key": "WAIT", "delay": 3000})
                
                # All up
                for k in keys_to_hold:
                    macro_events.append({"type": "up", "key": k, "delay": 0})
                
                self.press_ui["type"].set("macro")
                self.update_action_fields("macro", {"type": "macro", "events": macro_events}, self.press_ui)
            else:
                # Treat single keys and combos as hotkey type
                self.press_ui["type"].set("hotkey")
                self.update_action_fields("hotkey", {"type": "hotkey", "value": clean_key}, self.press_ui)
                
            # Always update the label when a control is selected
            self.label_entry.delete(0, "end")
            # Append the selected number to label if it was a range
            final_label = control["label"]
            if "1-9" in control["default"] and "num" in locals() and num is not None:
                final_label += f" {num}"
            self.label_entry.insert(0, final_label)

    def add_prop_field(self, label, value):
        ctk.CTkLabel(self.prop_container, text=label).pack(anchor="w", padx=20)
        entry = ctk.CTkEntry(self.prop_container); entry.insert(0, value); entry.pack(fill="x", padx=20, pady=2); return entry

    def create_action_ui(self, title, key, data):
        frame = ctk.CTkFrame(self.prop_container, border_width=1, border_color="#444444")
        frame.pack(pady=10, padx=20, fill="x")
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(weight="bold")).pack(pady=5)
        
        type_var = ctk.StringVar(value=data["type"] if data else "none")
        content_frame = ctk.CTkFrame(frame, fg_color="transparent")
        ui_obj = {"type": type_var, "content": content_frame, "entries": {}, "frame": frame}
        
        dropdown = ScrollableOptionMenu(frame, values=["none", "key", "hotkey", "macro", "website", "file"], variable=type_var, 
                                     command=lambda v: self.update_action_fields_with_cooldown(v, data, ui_obj))
        dropdown.pack(pady=5)
        content_frame.pack(fill="x", pady=5)
        
        self.update_action_fields(type_var.get(), data, ui_obj)
        return ui_obj

    def update_action_fields_with_cooldown(self, v, data, ui_obj):
        if not self.check_menu_cooldown(): return
        self.update_action_fields(v, data, ui_obj)

    def recursive_destroy(self, widget):
        for child in widget.winfo_children():
            self.recursive_destroy(child)
        widget.destroy()

    def update_action_fields(self, act_type, data, ui_obj):
        # Use recursive destroy to avoid CTkOptionMenu orphan dropdowns causing TclErrors
        for w in ui_obj["content"].winfo_children():
            self.recursive_destroy(w)
        ui_obj["entries"] = {}
        
        if act_type == "none":
            ui_obj["content"].pack_forget()
            return
        
        # Ensure it is packed if not "none"
        ui_obj["content"].pack(fill="x", pady=5)
        
        if act_type == "key":
            e = ctk.CTkEntry(ui_obj["content"], placeholder_text="Value (e.g. hello)")
            e.pack(padx=10, fill="x")
            e.insert(0, data.get("value", "") if data and data["type"] == "key" else "")
            ui_obj["entries"]["value"] = e
        elif act_type == "hotkey":
            row = ctk.CTkFrame(ui_obj["content"], fg_color="transparent")
            row.pack(fill="x", padx=10)
            val = data.get("value", "") if data and data["type"] == "hotkey" else ""
            e = ctk.CTkEntry(row, placeholder_text="Click to Record...")
            e.insert(0, val)
            e.configure(state="disabled")
            e.pack(side="left", expand=True, fill="x")
            ui_obj["entries"]["value"] = e
            
            clear_btn = ctk.CTkButton(row, text="CLEAR", width=50, command=lambda: self.clear_and_record_hotkey(e))
            clear_btn.pack(side="right", padx=(5, 0))
            
            if not val:
                self.after(100, lambda: self.capture_hotkey(e))
        elif act_type == "macro":
            # Add context for macro editing
            ui_obj["macro_events"] = data.get("events", []) if data and data["type"] == "macro" else []
            
            lf = ctk.CTkScrollableFrame(ui_obj["content"], height=150) # Taller for easier editing
            lf.pack(fill="x", padx=10, pady=5)
            ui_obj["macro_scroll"] = lf
            
            self.refresh_macro_list(ui_obj)
            
            rb_frame = ctk.CTkFrame(ui_obj["content"], fg_color="transparent")
            rb_frame.pack(fill="x", pady=2)
            rb = ctk.CTkButton(rb_frame, text="● REC", fg_color="#aa2222", width=100)
            rb.pack(pady=5)
            rb.configure(command=lambda: self.toggle_recording(rb, ui_obj))
        elif act_type == "website":
            e = ctk.CTkEntry(ui_obj["content"], placeholder_text="URL (e.g. google.com)")
            e.pack(padx=10, fill="x")
            e.insert(0, data.get("value", "") if data and data["type"] == "website" else "")
            ui_obj["entries"]["value"] = e
        elif act_type == "file":
            row = ctk.CTkFrame(ui_obj["content"], fg_color="transparent")
            row.pack(fill="x", padx=10)
            e = ctk.CTkEntry(row, placeholder_text="File Path...")
            e.insert(0, data.get("value", "") if data and data["type"] == "file" else "")
            e.pack(side="left", expand=True, fill="x")
            ui_obj["entries"]["value"] = e
            
            def browse_file(ent=e):
                from tkinter import filedialog
                path = filedialog.askopenfilename(title="Select File to Open")
                if path:
                    ent.delete(0, "end")
                    ent.insert(0, path)
                    
            ctk.CTkButton(row, text="BROWSE", width=70, command=browse_file).pack(side="right", padx=(5, 0))

    def refresh_macro_list(self, ui_obj):
        lf = ui_obj.get("macro_scroll")
        if not lf: return
        
        for w in lf.winfo_children():
            w.destroy()
            
        events = ui_obj.get("macro_events", [])
        for i, ev in enumerate(events):
            self.add_macro_row(lf, ev, i, ui_obj)

    def add_macro_row(self, parent, ev, index, ui_obj):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=1)
        
        content_frame = ctk.CTkFrame(row, fg_color="transparent")
        content_frame.pack(side="left", fill="x", expand=True)

        if ev["type"] == "delay":
            badge = ctk.CTkLabel(content_frame, text=" TIME ", fg_color="#555555", text_color="white", corner_radius=4, font=ctk.CTkFont(size=12, weight="bold"))
            badge.pack(side="left", padx=5)
            lbl = ctk.CTkLabel(content_frame, text=f"Wait {ev['delay']}ms", font=ctk.CTkFont(size=13, slant="italic"))
            lbl.pack(side="left", padx=5)
        else:
            is_down = ev["type"] == "down"
            color = "#22aa22" if is_down else "#aa2222"
            text = " DN " if is_down else " UP "
            
            badge = ctk.CTkLabel(content_frame, text=text, fg_color=color, text_color="white", corner_radius=4, font=ctk.CTkFont(size=12, weight="bold"))
            badge.pack(side="left", padx=5)
            
            delay_str = f" (delay {ev['delay']}ms)" if ev.get("delay", 0) > 0 else ""
            lbl = ctk.CTkLabel(content_frame, text=f"{ev['key']}{delay_str}", font=ctk.CTkFont(size=13))
            lbl.pack(side="left", padx=5)

        # Context Menu Bindings
        def show_macro_menu(event, idx=index):
            menu = tk.Menu(self, tearoff=0, bg=self.sc_header_bg, fg=self.sc_teal, activebackground=self.sc_dark_teal, activeforeground="white", borderwidth=1)
            menu.add_command(label="Edit Event", command=lambda: self.edit_macro_event(idx, ui_obj))
            menu.add_command(label="Copy Event", command=lambda: self.copy_macro_event(idx, ui_obj))
            menu.add_separator()
            if self.macro_clipboard:
                menu.add_command(label="Paste Above", command=lambda: self.paste_macro_event(idx, ui_obj, True))
                menu.add_command(label="Paste Below", command=lambda: self.paste_macro_event(idx, ui_obj, False))
                menu.add_separator()
            menu.add_command(label="Delete Event", command=lambda: self.delete_macro_event(idx, ui_obj))
            menu.post(event.x_root, event.y_root)

        row.bind("<Button-3>", show_macro_menu)
        content_frame.bind("<Button-3>", show_macro_menu)
        badge.bind("<Button-3>", show_macro_menu)
        lbl.bind("<Button-3>", show_macro_menu)

    def edit_macro_event(self, index, ui_obj):
        events = ui_obj["macro_events"]
        ev = events[index]
        
        dialog = ctk.CTkToplevel(self)
        dialog.title("Edit Macro Event")
        dialog.geometry("300x250")
        dialog.transient(self)
        dialog.grab_set()
        
        ctk.CTkLabel(dialog, text="Edit Event", font=ctk.CTkFont(weight="bold")).pack(pady=10)
        
        type_var = ctk.StringVar(value=ev["type"])
        ctk.CTkLabel(dialog, text="Type:").pack()
        type_menu = ScrollableOptionMenu(dialog, values=["down", "up", "delay"], variable=type_var)
        type_menu.pack(pady=5)
        
        ctk.CTkLabel(dialog, text="Key / Wait Label:").pack()
        key_entry = ctk.CTkEntry(dialog)
        key_entry.insert(0, ev["key"])
        key_entry.pack(pady=5)
        
        ctk.CTkLabel(dialog, text="Delay (ms):").pack()
        delay_entry = ctk.CTkEntry(dialog)
        delay_entry.insert(0, str(ev.get("delay", 0)))
        delay_entry.pack(pady=5)
        
        def save():
            try:
                ev["type"] = type_var.get()
                ev["key"] = key_entry.get().strip()
                ev["delay"] = int(delay_entry.get())
                self.refresh_macro_list(ui_obj)
                dialog.destroy()
            except ValueError:
                from tkinter import messagebox
                messagebox.showerror("Error", "Delay must be a number")
                
        ctk.CTkButton(dialog, text="SAVE", command=save, fg_color=self.sc_dark_teal).pack(pady=10)

    def copy_macro_event(self, index, ui_obj):
        import copy
        self.macro_clipboard = copy.deepcopy(ui_obj["macro_events"][index])
        print(f"[DEBUG] Copied macro event: {self.macro_clipboard}")

    def paste_macro_event(self, index, ui_obj, above):
        if not self.macro_clipboard: return
        import copy
        new_ev = copy.deepcopy(self.macro_clipboard)
        idx = index if above else index + 1
        ui_obj["macro_events"].insert(idx, new_ev)
        self.refresh_macro_list(ui_obj)

    def delete_macro_event(self, index, ui_obj):
        ui_obj["macro_events"].pop(index)
        self.refresh_macro_list(ui_obj)

    def clear_and_record_hotkey(self, entry):
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.configure(state="disabled")
        self.capture_hotkey(entry)

    def capture_hotkey(self, entry):
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, "RECORDING...")
        entry.configure(state="disabled")
        
        captured_keys = set()
        
        def on_press(key):
            try:
                k = key.char if hasattr(key, 'char') and key.char else str(key).replace("Key.", "").replace("'", "")
            except:
                k = str(key).replace("Key.", "").replace("'", "")
            captured_keys.add(k.lower())
            
        def on_release(key):
            # Prioritize modifiers in the hotkey string
            priority = {"ctrl": 0, "alt": 1, "shift": 2, "win": 3, "cmd": 3}
            def key_sort(k):
                k = k.lower()
                for p_key, p_val in priority.items():
                    if p_key in k: return p_val
                return 10
            
            sorted_keys = sorted(list(captured_keys), key=key_sort)
            combo = "+".join(sorted_keys)
            # Use self.after to safely update UI from the listener thread
            self.after(0, lambda: self.finish_capture(entry, combo))
            return False # Stop listener

        self.hotkey_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.hotkey_listener.start()

    def finish_capture(self, entry, combo):
        if not entry.winfo_exists(): return
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, combo)
        entry.configure(state="disabled")

    def toggle_recording(self, btn, ui_obj):
        # Clear focus from all entries to prevent "typing" into labels while recording
        self.focus_set()
        
        if not self.recorder.is_recording:
            self.recorder.start()
            btn.configure(text="■ STOP", fg_color="#cc2222")
        else:
            events = self.recorder.stop()
            if btn.winfo_exists():
                btn.configure(text="● REC", fg_color="#aa2222")
            ui_obj["macro_events"] = events
            
            scroll_frame = ui_obj.get("macro_scroll")
            if scroll_frame and scroll_frame.winfo_exists():
                for sub in scroll_frame.winfo_children(): sub.destroy()
                for ev in events:
                    self.add_macro_row(scroll_frame, ev)
            else:
                print("[ERROR] Could not find scrollable frame for macro events")

    def save_button_props(self, btn):
        btn["label"] = self.label_entry.get()
        # Apply temporary image changes on save
        btn["image"] = self.edit_image_vars.get("image")
        btn["image_pressed"] = self.edit_image_vars.get("image_pressed")
        
        self.actions_data[btn["id"]] = {"on_press": self.get_action_data(self.press_ui), "on_release": self.get_action_data(self.release_ui)}
        self.save_layout(); self.refresh_visual_grid()

    def get_action_data(self, ui):
        t = ui["type"].get()
        if t == "none": return None
        res = {"type": t}
        if t in ["key", "hotkey", "website", "file"]: res["value"] = ui["entries"]["value"].get()
        elif t == "macro": res["events"] = ui.get("macro_events", [])
        return res

    def cleanup_unused_asset(self, old_path, new_dest):
        """Removes an asset if it's no longer used by any button or background."""
        if not old_path or not os.path.exists(old_path) or self.assets_dir not in old_path:
            return
            
        if os.path.abspath(old_path) == os.path.abspath(new_dest):
            return

        is_used = False
        # Check all pages
        for p in self.layout_data.get("pages", []):
            if p.get("background_image") == old_path:
                is_used = True; break
            for b in p.get("buttons", []):
                if b.get("image") == old_path or b.get("image_pressed") == old_path:
                    is_used = True; break
            if is_used: break
        
        # Check global config
        if not is_used and self.layout_data.get("config", {}).get("background_image") == old_path:
            is_used = True

        if not is_used:
            try: os.remove(old_path)
            except: pass

    def pick_image(self, btn, field):
        from tkinter import filedialog
        new_src = filedialog.askopenfilename(filetypes=[("PNG", "*.png")])
        if not new_src: return
        
        filename = os.path.basename(new_src)
        # Always relative path for the data
        rel_path = os.path.join("server", "assets", filename).replace("\\", "/")
        new_dest = os.path.join(self.assets_dir, filename)
        
        if os.path.abspath(new_src) != os.path.abspath(new_dest):
            shutil.copy2(new_src, new_dest)
            
        # Update TEMPORARY editing state, not the button yet
        old_path = self.edit_image_vars.get(field)
        self.edit_image_vars[field] = rel_path
        self.cleanup_unused_asset(old_path, rel_path)
        
        # Refresh properties to show the new preview immediately
        self.select_button(btn)

    def pick_background_image(self):
        from tkinter import filedialog
        new_src = filedialog.askopenfilename(filetypes=[("PNG", "*.png"), ("JPG", "*.jpg")])
        if not new_src: return
        
        filename = os.path.basename(new_src)
        # Always relative path for the data
        rel_path = os.path.join("server", "assets", filename).replace("\\", "/")
        new_dest = os.path.join(self.assets_dir, filename)
        
        if os.path.abspath(new_src) != os.path.abspath(new_dest):
            shutil.copy2(new_src, new_dest)
            
        page = self.layout_data["pages"][self.current_page_index]
        old_path = page.get("background_image")
        page["background_image"] = rel_path
        self.cleanup_unused_asset(old_path, rel_path)

        self.save_layout()
        self.refresh_visual_grid()

    def clear_background_image(self):
        page = self.layout_data["pages"][self.current_page_index]
        if "background_image" in page:
            del page["background_image"]
            self.save_layout()
            self.refresh_visual_grid()
        elif "background_image" in self.layout_data["config"]:
            # Optionally clear global too if it's currently showing
            del self.layout_data["config"]["background_image"]
            self.save_layout()
            self.refresh_visual_grid()

    def update_grid_config(self):
        page = self.layout_data["pages"][self.current_page_index]
        page["columns"], page["rows"] = int(self.cols_var.get()), int(self.rows_var.get())
        # Also sync global config if it's the first page
        if self.current_page_index == 0:
            self.layout_data["config"]["columns"], self.layout_data["config"]["rows"] = page["columns"], page["rows"]
        self.save_layout(); self.refresh_visual_grid()

    def sync_to_android(self):
        try:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw_sock:
                raw_sock.settimeout(2)
                with context.wrap_socket(raw_sock) as s:
                    s.connect(("localhost", 5000))
                    s.sendall(b"SYNC_LAYOUT\n")
                    print("[EDITOR] Sent SYNC_LAYOUT command to server")
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Sync Error", f"Could not connect to server: {e}")

    def add_new_button_at(self, r, c, rs, cs):
        page = self.layout_data["pages"][self.current_page_index]
        bid = f"BTN_{random.randint(1000, 9999)}"
        new_btn = {
            "id": bid, 
            "label": "New", 
            "position": [r, c], 
            "size": [rs, cs],
            "image": "editor/placeholder_buttons/button.png",
            "image_pressed": "editor/placeholder_buttons/button_press.png"
        }
        page["buttons"].append(new_btn)
        self.save_layout(); self.refresh_visual_grid()
        self.select_button(new_btn)

    def show_button_context_menu(self, event, btn):
        menu = tk.Menu(self, tearoff=0, bg=self.sc_header_bg, fg=self.sc_teal, activebackground=self.sc_dark_teal, activeforeground="white", borderwidth=1)
        menu.add_command(label=f"Delete Button '{btn.get('label')}'", command=lambda: self.delete_button(btn["id"]))
        menu.post(event.x_root, event.y_root)

    def delete_button(self, bid):
        page = self.layout_data["pages"][self.current_page_index]
        page["buttons"] = [b for b in page["buttons"] if b["id"] != bid]
        if bid in self.actions_data: del self.actions_data[bid]
        self.save_layout(); self.refresh_visual_grid()

    def export_layout(self, path, name):
        save_path = filedialog.asksaveasfilename(defaultextension=".tcd", 
                                                 filetypes=[("TCD Layout", "*.tcd")],
                                                 initialfile=f"{name}.tcd")
        if not save_path: return
        
        try:
            layout_data = self.load_json(path)
            # Find all buttons and their actions for asset bundling
            actions_in_layout = layout_data.get("actions", {})
            assets_to_bundle = set()
            
            # Global background
            bg = layout_data.get("config", {}).get("background_image")
            if bg: assets_to_bundle.add(bg)
            
            for page in layout_data.get("pages", []):
                p_bg = page.get("background_image")
                if p_bg: assets_to_bundle.add(p_bg)
                
                for btn in page.get("buttons", []):
                    b_id = btn["id"]
                    if btn.get("image"): assets_to_bundle.add(btn["image"])
                    if btn.get("image_pressed"): assets_to_bundle.add(btn["image_pressed"])

            with zipfile.ZipFile(save_path, 'w') as zipf:
                # Add Unified Layout JSON
                zipf.writestr("layout.json", json.dumps(layout_data, indent=2))
                
                # Add Assets
                added_filenames = set()
                for asset_path in assets_to_bundle:
                    clean_name = os.path.basename(asset_path)
                    if not clean_name or clean_name in added_filenames:
                        continue
                        
                    found_path = None
                    
                    # Search for the actual file
                    if os.path.exists(asset_path): found_path = asset_path
                    else:
                        for d in [self.assets_dir, "editor/pngs", "editor/placeholder_buttons"]:
                            p = os.path.join(d, clean_name).replace("\\", "/")
                            if os.path.exists(p): found_path = p; break
                    
                    if found_path:
                        zipf.write(found_path, f"assets/{clean_name}")
                        added_filenames.add(clean_name)

            messagebox.showinfo("Success", f"Layout '{name}' exported successfully to {os.path.basename(save_path)}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export layout: {e}")

    def import_layout(self):
        file_path = filedialog.askopenfilename(filetypes=[("TCD Layout", "*.tcd")])
        if not file_path: return
        
        try:
            with zipfile.ZipFile(file_path, 'r') as zipf:
                # 1. Read Layout JSON
                if "layout.json" not in zipf.namelist():
                    raise Exception("Invalid TCD file: missing layout.json")
                
                layout_data = json.loads(zipf.read("layout.json").decode("utf-8"))
                
                # 2. Get Layout Name
                base_name = os.path.basename(file_path).replace(".tcd", "")
                name = simpledialog.askstring("Import Layout", "Enter name for imported layout:", initialvalue=base_name)
                if not name: return
                
                target_path = os.path.join(self.layouts_dir, f"{name}.json")
                if os.path.exists(target_path):
                    if not messagebox.askyesno("Overwrite?", f"A layout named '{name}' already exists. Overwrite?"):
                        return

                # 3. Extract Assets
                for item in zipf.namelist():
                    if item.startswith("assets/"):
                        filename = os.path.basename(item)
                        if filename:
                            data = zipf.read(item)
                            with open(os.path.join(self.assets_dir, filename), "wb") as f:
                                f.write(data)

                # 4. Handle Actions
                if "actions.json" in zipf.namelist():
                    imported_actions = json.loads(zipf.read("actions.json").decode("utf-8"))
                    if "actions" not in layout_data:
                        layout_data["actions"] = {}
                    layout_data["actions"].update(imported_actions)

                # 5. Save Layout
                # Standardize asset paths in the imported layout to use server/assets
                def fix_paths(obj):
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if k in ["image", "image_pressed", "background_image"] and v:
                                obj[k] = f"server/assets/{os.path.basename(v)}"
                            else:
                                fix_paths(v)
                    elif isinstance(obj, list):
                        for item in obj: fix_paths(item)

                fix_paths(layout_data)
                self.save_json(target_path, layout_data)
                
                self.refresh_layouts_list()
                self.load_layout(target_path)
                messagebox.showinfo("Success", f"Layout '{name}' imported successfully!")
                
        except Exception as e:
            messagebox.showerror("Import Error", f"Failed to import layout: {e}")

class ScrollableDropdown(ctk.CTkToplevel):
    def __init__(self, anchor_widget, values, command, width=None, height=250, master=None):
        super().__init__(master=master)
        self.overrideredirect(True)
        self.anchor_widget = anchor_widget
        self.command = command
        
        self.configure(fg_color="#2a4d5e") # sc_border
        self.attributes("-topmost", True)
        
        # If master is a modal dialog, we need to handle grab_set
        if master and hasattr(master, 'grab_status') and master.grab_status():
            self.after(10, self.grab_set)
        
        self.update_idletasks()
        x = anchor_widget.winfo_rootx()
        y = anchor_widget.winfo_rooty() + anchor_widget.winfo_height()
        w = width if width else anchor_widget.winfo_width()
        
        h = min(height, len(values) * 35 + 10)
        if len(values) > 0:
            h = max(h, 45) # Ensure at least one item is visible
        # Ensure it doesn't go off screen bottom
        screen_h = self.winfo_screenheight()
        if y + h > screen_h:
            y = anchor_widget.winfo_rooty() - h
            
        self.geometry(f"{w}x{h}+{x}+{y}")
        
        self.frame = ctk.CTkScrollableFrame(self, fg_color="#0a141a", corner_radius=0, 
                                           scrollbar_button_color="#00f5ff", 
                                           scrollbar_button_hover_color="#005f6b")
        self.frame.pack(fill="both", expand=True, padx=1, pady=1)
        
        for val in values:
            btn = ctk.CTkButton(self.frame, text=val, fg_color="transparent", 
                                text_color="white", hover_color="#005f6b", 
                                anchor="w", height=30, corner_radius=0,
                                command=lambda v=val: self.on_select(v))
            btn.pack(fill="x")
            
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Key>", self._on_key_press)
        
        self._last_char = ""
        self._last_time = 0
        self._last_index = -1
        
        self.after(10, self.focus_set)

    def _on_key_press(self, event):
        char = event.char.lower()
        if not char: return
        
        now = time.time()
        btns = [b for b in self.frame.winfo_children() if isinstance(b, ctk.CTkButton)]
        if not btns: return

        if self._last_char == char and (now - self._last_time) < 1.0:
            start_search = self._last_index + 1
        else:
            start_search = 0
            
        self._last_char = char
        self._last_time = now
        
        for i in range(len(btns)):
            idx = (start_search + i) % len(btns)
            text = btns[idx].cget("text").lower()
            # Jump if any word in the label starts with the pressed character
            words = text.split()
            if any(w.startswith(char) for w in words):
                self._last_index = idx
                # Simple scroll approximation for CTkScrollableFrame
                pos = idx / len(btns)
                self.frame._parent_canvas.yview_moveto(pos)
                break

    def _on_focus_out(self, event):
        # Delay destruction to see if focus moved to a child
        self.after(100, self._check_destroy)

    def _check_destroy(self):
        try:
            focus = self.focus_get()
            # If focus is not on this window or any of its children, destroy
            if focus:
                # Walk up the parent tree of the focused widget
                curr = focus
                while curr:
                    if curr == self:
                        return # Focus is still inside
                    try: curr = curr.master
                    except: break
            self.destroy()
        except:
            try: self.destroy()
            except: pass

    def on_select(self, value):
        self.command(value)
        self.destroy()

class ScrollableOptionMenu(ctk.CTkFrame):
    def __init__(self, master, values, variable, command=None, **kwargs):
        # Extract CTkOptionMenu specific kwargs if any
        width = kwargs.pop("width", 140)
        height = kwargs.pop("height", 28)
        
        super().__init__(master, fg_color="transparent", width=width, height=height)
        self.values = values
        self.variable = variable
        self.command = command
        
        self.btn = ctk.CTkButton(self, text=variable.get(), 
                                 fg_color="#0f1f26", border_width=1, border_color="#2a4d5e",
                                 text_color="#00f5ff", hover_color="#162a33",
                                 command=self.open_dropdown, width=width, height=height, **kwargs)
        self.btn.pack(fill="both", expand=True)
        
        # Update text when variable changes
        self.variable.trace_add("write", self._update_button_text)

    def _update_button_text(self, *args):
        try: self.btn.configure(text=self.variable.get())
        except: pass

    def open_dropdown(self):
        # Search for record_menu_open in parent tree
        curr = self.master
        while curr:
            if hasattr(curr, 'record_menu_open'):
                curr.record_menu_open()
                break
            curr = curr.master

        ScrollableDropdown(self.btn, self.values, self.on_select, master=self.master)
        
    def on_select(self, value):
        self.variable.set(value)
        if self.command:
            self.command(value)
            
    def configure(self, **kwargs):
        if "values" in kwargs:
            self.values = kwargs.pop("values")
        if "variable" in kwargs:
            self.variable = kwargs.pop("variable")
            self.btn.configure(text=self.variable.get())
        self.btn.configure(**kwargs)

if __name__ == "__main__":
    if "--server" in sys.argv:
        # Run in server mode
        try:
            from server.main import start_server
            start_server()
        except ImportError:
            # Fallback if bundled differently
            import server.main as server_main
            server_main.start_server()
    else:
        # Run in editor mode
        app = EditorApp()
        app.mainloop()
