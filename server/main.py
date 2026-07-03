import socket
import threading
import json
import pyautogui
import random
import string
import ssl
import base64
import os
import time
import sys
import ctypes
import builtins
import webbrowser
import subprocess

def get_resource_path(relative_path):
    """ Get absolute path to resource, prioritizing live folder for server data """
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        bundle_dir = getattr(sys, '_MEIPASS', exe_dir)
        
        # If we are in _internal (one-dir mode), the live files are one level up
        if os.path.basename(exe_dir).lower() == "_internal":
            exe_dir = os.path.dirname(exe_dir)
            
        # Check live folder first for user-data
        live_path = os.path.join(exe_dir, relative_path)
        user_files = ["layout.json", "actions.json", "editor_settings.json", "assets", "layouts", "known_devices.json", "Bug_fixes.txt", "Bug_fixes_joke.txt", "joke_index.txt"]
        is_user_data = any(u in relative_path for u in user_files) or relative_path.endswith("_default_keys.json")
        
        if is_user_data:
            return live_path
            
        # For non-user data (like certs), check bundle then live
        bundled_path = os.path.join(bundle_dir, relative_path)
        if os.path.exists(bundled_path):
            return bundled_path
        return live_path
    else:
        # Dev mode - absolute path from CWD
        return os.path.abspath(relative_path)

# Override print to only show problems and essential info
def print(*args, **kwargs):
    if sys.stdout is None:
        return
    msg = " ".join(map(str, args))
    # Keywords that indicate a problem or essential info that the Editor needs to see
    # Also allow sequential joke/fixes markers
    problem_keywords = [
        "[WARNING]", "[ERROR]", "[FATAL ERROR]", "FAILED", 
        "*** PAIRING CODE", "[LISTENING]", "Server is ready", "Local IP",
        "Bug Fixes", "----"
    ]
    # If the message contains one of our keywords, or it's NOT a standard server/auth/macro log, show it
    if any(k in msg for k in problem_keywords) or (not msg.startswith("[SERVER]") and not msg.startswith("[AUTH]") and not msg.startswith("  ->")):
        try:
            import builtins
            builtins.print(*args, **kwargs, flush=True)
        except:
            pass

# Global pairing code for this session
PAIRING_CODE = ''.join(random.choices(string.digits, k=6))

def load_layout():
    try:
        path = get_resource_path("server/layout.json")
        if not os.path.exists(path): return {}
        with open(path, "r") as f:
            data = json.load(f)
            # Migration: if actions not in layout, try loading from separate file
            if "actions" not in data:
                old_actions_path = get_resource_path("server/actions.json")
                if os.path.exists(old_actions_path):
                    with open(old_actions_path, "r") as af:
                        data["actions"] = json.load(af)
            return data
    except Exception as e:
        print(f"[ERROR] Failed to load layout: {e}")
        return {}

def load_known_devices():
    try:
        with open(get_resource_path("server/known_devices.json"), "r") as f:
            return json.load(f).get("devices", [])
    except: return []

def save_known_devices(devices):
    with open(get_resource_path("server/known_devices.json"), "w") as f:
        json.dump({"devices": devices}, f, indent=2)

LAYOUT = load_layout()
KNOWN_DEVICES = load_known_devices()
ACTIVE_CLIENTS = []
CLIENTS_LOCK = threading.Lock()

def broadcast_layout():
    layout_msg = json.dumps({"type": "LAYOUT", "data": load_layout()}) + "\n"
    with CLIENTS_LOCK:
        for client in ACTIVE_CLIENTS:
            try:
                client.sendall(layout_msg.encode('utf-8'))
            except: pass
    print("[SERVER] Broadcasted layout to all clients")

def map_key(key):
    # Expanded key map for pynput, Star Citizen names -> pyautogui
    km = {
        "alt_l": "altleft", "alt_r": "altright", "alt_gr": "altright",
        "shift_l": "shiftleft", "shift_r": "shiftright",
        "ctrl_l": "ctrlleft", "ctrl_r": "ctrlright",
        "cmd": "win", "cmd_r": "win",
        "caps_lock": "capslock",
        "page_up": "pgup", "page_down": "pgdn",
        "print_screen": "printscreen",
        "scroll_lock": "scrolllock",
        "num_lock": "numlock",
        # Star Citizen specific names from starcitizen.json
        "left control": "ctrlleft",
        "right control": "ctrlright",
        "left ctrl": "ctrlleft",
        "right ctrl": "ctrlright",
        "left shift": "shiftleft",
        "right shift": "shiftright",
        "left alt": "altleft",
        "right alt": "altright",
        "left mouse button": "left",
        "right mouse button": "right",
        "middle mouse button": "middle",
        "space": "space",
        "spacebar": "space",
        "backspace": "backspace",
        "enter": "enter",
        "escape": "esc",
        "tab": "tab",
        "up": "up", "down": "down", "left": "left", "right": "right",
        "up arrow": "up", "down arrow": "down", "left arrow": "left", "right arrow": "right",
        "numpad 0": "num0", "numpad 1": "num1", "numpad 2": "num2",
        "numpad 3": "num3", "numpad 4": "num4", "numpad 5": "num5",
        "numpad 6": "num6", "numpad 7": "num7", "numpad 8": "num8",
        "numpad 9": "num9", "numpad *": "multiply", "numpad -": "subtract",
        "numpad +": "add", "numpad .": "decimal", "numpad /": "divide",
        "numpad 1-9": "num1", # Fallback for ranges
        # New SC format mappings
        "comma": "comma", "period": "period", "slash": "slash",
        "1.0": "num1", "2.0": "num2", "3.0": "num3", "4.0": "num4", "5.0": "num5",
        "6.0": "num6", "7.0": "num7", "8.0": "num8", "9.0": "num9", "0.0": "num0"
    }
    k = key.lower().strip()
    return km.get(k, k)

# Windows low-level keyboard injection fallback for games like Star Citizen
if sys.platform == "win32":
    user32 = ctypes.windll.user32
    KEYEVENTF_KEYUP = 0x0002
    VK_CODE = {
        "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "shiftleft": 0xA0, "shiftright": 0xA1,
        "ctrlleft": 0xA2, "ctrlright": 0xA3, "altleft": 0xA4, "altright": 0xA5,
        "pause": 0x13, "capslock": 0x14, "esc": 0x1B, "space": 0x20,
        "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
        "printscreen": 0x2C, "insert": 0x2D, "delete": 0x2E,
        "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
        "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
        "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
        "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
        "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
        "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
        "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59,
        "z": 0x5A,
        "num0": 0x60, "num1": 0x61, "num2": 0x62, "num3": 0x63,
        "num4": 0x64, "num5": 0x65, "num6": 0x66, "num7": 0x67,
        "num8": 0x68, "num9": 0x69,
        "numpad0": 0x60, "numpad1": 0x61, "numpad2": 0x62, "numpad3": 0x63,
        "numpad4": 0x64, "numpad5": 0x65, "numpad6": 0x66, "numpad7": 0x67,
        "numpad8": 0x68, "numpad9": 0x69,
        "multiply": 0x6A, "add": 0x6B, "separator": 0x6C, "subtract": 0x6D,
        "decimal": 0x6E, "divide": 0x6F,
        "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
        "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
        "f11": 0x7A, "f12": 0x7B,
        "minus": 0xBD, "equals": 0xBB, "leftbracket": 0xDB, "rightbracket": 0xDD,
        "backslash": 0xDC, "semicolon": 0xBA, "quote": 0xDE,
        "comma": 0xBC, "period": 0xBE, "slash": 0xBF,
        "win": 0x5B, "menu": 0x5D
    }

    def win_vkey(name):
        if not name:
            return None
        normalized = name.lower().replace(" ", "").replace("_", "")
        return VK_CODE.get(normalized)

    def win_key_event(name, down):
        vk = win_vkey(name)
        if not vk:
            return False
        scan = user32.MapVirtualKeyW(vk, 0)
        flags = 0 if down else KEYEVENTF_KEYUP
        user32.keybd_event(vk, scan, flags, 0)
        return True

    def send_win_keypress(name):
        if not win_key_event(name, True):
            return False
        time.sleep(0.01)
        return win_key_event(name, False)

    def send_win_hotkey(names):
        for key in names:
            if not win_key_event(key, True):
                return False
            time.sleep(0.01)
        time.sleep(0.02)
        for key in reversed(names):
            win_key_event(key, False)
            time.sleep(0.01)
        return True

    def send_win_macro_event(key, event_type):
        if event_type == "down":
            return win_key_event(key, True)
        return win_key_event(key, False)

else:
    def send_win_keypress(name):
        return False
    def send_win_hotkey(names):
        return False
    def send_win_macro_event(key, event_type):
        return False


def perform_action(action_id, event_type):
    # Reload layout to catch editor saves
    layout = load_layout()
    actions = layout.get("actions", {})
    
    if action_id not in actions:
        print(f"[WARNING] No action defined for {action_id}")
        return

    btn_actions = actions[action_id]
    action = btn_actions.get(f"on_{event_type}")
    
    if not action:
        return

    print(f"[ACTION] {action_id} {event_type}: {action['type']}")

    if action["type"] == "key":
        val = action["value"]
        if not val: return
        mapped_key = map_key(val)
        if sys.platform == "win32" and send_win_keypress(mapped_key):
            return
        pyautogui.press(mapped_key)
        
    elif action["type"] == "hotkey":
        keys = [map_key(k) for k in action["value"].split("+") if k]
        if not keys: return
        print(f"  -> Hotkey: {keys}")
        if sys.platform == "win32" and send_win_hotkey(keys):
            return
        pyautogui.hotkey(*keys)
        
    elif action["type"] == "macro":
        print(f"  -> Executing macro with {len(action.get('events', []))} events")
        for ev in action.get("events", []):
            if ev.get("delay", 0) > 0:
                time.sleep(ev["delay"] / 1000.0)
            
            if ev["type"] == "delay":
                continue
                
            key = map_key(ev["key"])
            if sys.platform == "win32" and send_win_macro_event(key, ev["type"]):
                continue
            if ev["type"] == "down":
                pyautogui.keyDown(key)
            else:
                pyautogui.keyUp(key)

    elif action["type"] == "website":
        url = action.get("value", "")
        if url:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            webbrowser.open(url)
            
    elif action["type"] == "file":
        path = action.get("value", "")
        if path and os.path.exists(path):
            if sys.platform == "win32":
                os.startfile(path)
            else:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.call([opener, path])

def send_asset(client_socket, filename):
    clean_name = os.path.basename(filename)
    
    search_dirs = [
        get_resource_path("server/assets"),
        get_resource_path("editor/pngs"),
        get_resource_path("editor/placeholder_buttons")
    ]
    
    found_path = next((p for p in (os.path.join(d, clean_name) for d in search_dirs) if os.path.exists(p)), None)
            
    if not found_path:
        layout = load_layout()
        # Search buttons
        for page in layout.get("pages", []):
            for btn in page.get("buttons", []):
                for key in ["image", "image_pressed"]:
                    p = btn.get(key, "")
                    if p and os.path.basename(p) == clean_name and os.path.exists(p):
                        found_path = p; break
                if found_path: break
            if found_path: break
        
        # Search background
        if not found_path:
            bg = layout.get("config", {}).get("background_image", "")
            if bg and os.path.basename(bg) == clean_name and os.path.exists(bg):
                found_path = bg

    if found_path:
        try:
            with open(found_path, "rb") as f:
                data = f.read()
                encoded = base64.b64encode(data).decode("utf-8")
                response = json.dumps({"type": "ASSET", "filename": clean_name, "data": encoded})
                client_socket.sendall((response + "\n").encode("utf-8"))
        except Exception as e:
            print(f"[ERROR] Failed to send asset {clean_name}: {e}")
    else:
        print(f"[WARNING] Asset NOT FOUND: {clean_name}")

def handle_client(client_socket, addr):
    authenticated = False
    connected = True
    print(f"[SERVER] Client connected: {addr}")
    
    with CLIENTS_LOCK:
        ACTIVE_CLIENTS.append(client_socket)
    
    try:
        f = client_socket.makefile('r', encoding='utf-8')
        while connected:
            line = f.readline()
            if not line: break
            data = line.strip()
            if not data: continue
            
            if data.startswith("HELLO|"):
                device_id = data.split("|")[1]
                if device_id in KNOWN_DEVICES:
                    authenticated = True
                    print(f"[AUTH] Device {device_id} authenticated ({addr})")
                    client_socket.sendall("AUTH_SUCCESS\n".encode('utf-8'))
                    layout_data = json.dumps({"type": "LAYOUT", "data": load_layout()})
                    client_socket.sendall((layout_data + "\n").encode('utf-8'))
                else: 
                    print(f"[AUTH] Device {device_id} requires pairing ({addr})")
                    client_socket.sendall("AUTH_REQUIRED\n".encode('utf-8'))
            
            elif data.startswith("PAIR|"):
                parts = data.split("|")
                if parts[2] == PAIRING_CODE:
                    device_id = parts[1]
                    if device_id not in KNOWN_DEVICES:
                        KNOWN_DEVICES.append(device_id)
                        save_known_devices(KNOWN_DEVICES)
                    authenticated = True
                    print(f"[AUTH] Device {device_id} paired successfully ({addr})")
                    client_socket.sendall("PAIR_SUCCESS\n".encode('utf-8'))
                    layout_data = json.dumps({"type": "LAYOUT", "data": load_layout()})
                    client_socket.sendall((layout_data + "\n").encode('utf-8'))
                else: 
                    print(f"[AUTH] Pairing FAILED for {addr}")
                    client_socket.sendall("PAIR_FAILED\n".encode('utf-8'))

            elif data == "SYNC_LAYOUT":
                # Special command for Editor to trigger broadcast
                broadcast_layout()
                break # Close connection after sync command

            elif data.startswith("GET_ASSET|"):
                filename = data.split("|")[1]
                send_asset(client_socket, filename)

            elif authenticated:
                if "|" in data:
                    # Format: BTN_ID|EVENT (PRESS/RELEASE)
                    parts = data.split("|")
                    perform_action(parts[0], parts[1].lower())
                else:
                    perform_action(data, "press")

    except (ConnectionResetError, BrokenPipeError):
        pass
    except Exception as e:
        if "[WinError 10054]" not in str(e):
            print(f"[ERROR] Client {addr} error: {e}")
            
    with CLIENTS_LOCK:
        if client_socket in ACTIVE_CLIENTS:
            ACTIVE_CLIENTS.remove(client_socket)
    client_socket.close()
    print(f"[SERVER] Client disconnected: {addr}")

def terminal_listener():
    # Only run if connected to a real terminal
    if not sys.stdin or not sys.stdin.isatty():
        return
    while True:
        try:
            cmd = input().strip().lower()
            if cmd == "restart":
                print("[SERVER] Restarting...")
                os.execv(sys.executable, ['python'] + sys.argv)
        except EOFError:
            break
        except Exception as e:
            print(f"[ERROR] Terminal listener error: {e}")
            break

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def display_fixes_and_jokes():
    try:
        # 1. Display Bug Fixes
        fixes_path = get_resource_path("server/Bug_fixes.txt")
        if os.path.exists(fixes_path):
            with open(fixes_path, "r", encoding="utf-8") as f:
                print(f.read())
        
        # 2. Display Sequential Joke Block
        joke_path = get_resource_path("server/Bug_fixes_joke.txt")
        index_path = get_resource_path("server/joke_index.txt")
        
        if os.path.exists(joke_path):
            with open(joke_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Split by sections { ... }
            import re
            blocks = re.findall(r'\{(.*?)\}', content, re.DOTALL)
            if blocks:
                # Get current index
                idx = 0
                if os.path.exists(index_path):
                    try:
                        with open(index_path, "r") as f:
                            idx = int(f.read().strip())
                    except: idx = 0
                
                # Select block and increment index
                block = blocks[idx % len(blocks)].strip()
                print(block)
                
                # Save next index
                with open(index_path, "w") as f:
                    f.write(str((idx + 1) % len(blocks)))
    except Exception as e:
        print(f"[ERROR] Could not display fixes/jokes: {e}")

def start_server():
    print(f"*** PAIRING CODE: {PAIRING_CODE} ***")
    print("[SERVER] Starting startup sequence...")
    print(f"[SERVER] Local IP: {get_local_ip()}")
    # Start terminal listener thread
    threading.Thread(target=terminal_listener, daemon=True).start()
    
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        print("[SERVER] Binding to 0.0.0.0:5000...")
        server.bind(("0.0.0.0", 5000))
        server.listen()
        
        # SSL
        print("[SERVER] Loading SSL certificates...")
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(
            certfile=get_resource_path("server/cert.pem"), 
            keyfile=get_resource_path("server/key.pem")
        )
        
        print("[LISTENING] Server is ready.")
        display_fixes_and_jokes()
        
        while True:
            newsock, addr = server.accept()
            try:
                conn = context.wrap_socket(newsock, server_side=True)
                threading.Thread(target=handle_client, args=(conn, addr)).start()
            except Exception as e:
                print(f"[ERROR] SSL Wrap error: {e}")
                newsock.close()
    except Exception as e:
        print(f"[FATAL ERROR] Server failed to start: {e}")
        sys.exit(1)

if __name__ == "__main__":
    start_server()
