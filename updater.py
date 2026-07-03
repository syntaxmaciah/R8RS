import os
import sys
import time
import shutil
import zipfile
import subprocess

def log(msg):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    full_msg = f"[{timestamp}] {msg}"
    print(full_msg)
    with open("updater_log.txt", "a") as f:
        f.write(full_msg + "\n")

def run_update(zip_path, target_dir, exe_name):
    # Clear old log
    if os.path.exists("updater_log.txt"):
        try: os.remove("updater_log.txt")
        except: pass

    log(f"Update started...")
    log(f"Target Directory: {target_dir}")
    log(f"Update Package: {zip_path}")
    
    # Absolute paths are safer
    zip_path = os.path.abspath(zip_path)
    target_dir = os.path.abspath(target_dir)
    exe_path = os.path.join(target_dir, exe_name)
    
    # Wait for the main application to close
    max_retries = 15
    log("Waiting for application to close...")
    
    # SPECIAL CASE: If updater.exe is inside the target dir, we need to be careful
    # But usually it's replacing TacticalCommandDeck.exe
    
    for i in range(max_retries):
        try:
            if os.path.exists(exe_path):
                # Try to rename it temporarily to check for lock
                temp_name = exe_path + ".tmp"
                if os.path.exists(temp_name): os.remove(temp_name)
                os.rename(exe_path, temp_name)
                os.rename(temp_name, exe_path)
            log("Application closed successfully.")
            break
        except OSError:
            time.sleep(1)
    else:
        log("Error: Application failed to close in time (file still locked).")
        input("\nPress Enter to exit...")
        return

    # Extracting
    try:
        log("Extracting files...")
        if not os.path.exists(zip_path):
            log(f"Error: ZIP file not found at {zip_path}")
            input("\nPress Enter to exit...")
            return

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Check if zip is empty
            if not zip_ref.namelist():
                log("Error: ZIP file is empty.")
                input("\nPress Enter to exit...")
                return
            
            # Extract everything
            zip_ref.extractall(target_dir)
            
        log("Extraction complete.")
        
        # Clean up ZIP
        try:
            log("Removing update package...")
            os.remove(zip_path)
        except Exception as e:
            log(f"Warning: Could not remove ZIP: {e}")
            
        # Restart application
        log(f"Restarting {exe_name}...")
        if os.path.exists(exe_path):
            # Use start command to fully detach
            subprocess.Popen(f'start "" "{exe_name}"', cwd=target_dir, shell=True)
            log("Done.")
        else:
            log(f"Error: Could not find {exe_name} to restart at {exe_path}")
            input("\nPress Enter to exit...")
            
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        import traceback
        log(traceback.format_exc())
        input("\nPress Enter to exit...")

if __name__ == "__main__":
    # Wait for file system and app closure
    time.sleep(2.0)
    
    if len(sys.argv) < 4:
        log(f"Updater received insufficient arguments: {sys.argv}")
        time.sleep(3)
        sys.exit(1)
        
    run_update(sys.argv[1], sys.argv[2], sys.argv[3])
