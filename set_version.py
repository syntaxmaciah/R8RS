import sys
import re
import os
import json

def update_file(path, pattern, replacement):
    if not os.path.exists(path):
        print(f"[ERROR] File not found: {path}")
        return
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if the replacement string (or a similar versioned string) already exists
    # If the file already has the exact version we want, skip and report success
    if replacement in content:
        print(f"[SUCCESS] {path} is already up to date.")
        return

    new_content = re.sub(pattern, replacement, content)
    
    if content == new_content:
        print(f"[WARNING] No changes made to {path}. Pattern not found?")
    else:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"[SUCCESS] Updated {path}")

def get_current_version():
    path = "version.json"
    if not os.path.exists(path):
        return "1.0"
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("version", "1.0")
    except:
        return "1.0"

def save_version(ver):
    path = "version.json"
    data = {"version": ver}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    print(f"[SUCCESS] Updated {path}")

def increment_version(v):
    parts = v.split('.')
    if len(parts) >= 2:
        # Increment last part (e.g., 1.1 -> 1.2, 1.9 -> 1.10)
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    else:
        # Just add .1 if it's a single number
        return f"{v}.1"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        current = get_current_version()
        ver = increment_version(current)
        print(f"[INFO] Auto-incrementing: {current} -> {ver}")
    else:
        ver = sys.argv[1]
        print(f"[INFO] Setting version to: {ver}")

    # Update version.json first
    save_version(ver)

    # 1. Update build_dist.bat
    update_file("build_dist.bat", r"set VERSION=[\d.]+", f"set VERSION={ver}")

    # 2. Update Android build.gradle
    update_file("android_app/app/build.gradle", r'versionName "[\d.]+"', f'versionName "{ver}"')

    # 3. Update Android MainActivity.kt
    update_file("android_app/app/src/main/java/com/tcd/app/MainActivity.kt", 
                r'setTitle\("Tactical Command Deck v[\d.]+"\)', 
                f'setTitle("Tactical Command Deck v{ver}")')
    update_file("android_app/app/src/main/java/com/tcd/app/MainActivity.kt", 
                r'val currentVersion = "[\d.]+"', 
                f'val currentVersion = "{ver}"')

    # 4. Update Editor main.py
    update_file("editor/main.py", 
                r'self.VERSION = "[\d.]+"', 
                f'self.VERSION = "{ver}"')

    print(f"\n--- Project bumped to v{ver} ---")
