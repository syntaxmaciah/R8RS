import os
import sys
import json
import requests

def get_config():
    # Look for a config file for the GitHub Token
    config_path = "github_config.json"
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            return json.load(f)
    return {}

def save_config(token):
    with open("github_config.json", "w") as f:
        json.dump({"token": token}, f)

def release():
    print("--- TCD GitHub Release Tool ---")
    
    # 1. Get Token
    config = get_config()
    token = config.get("token")
    if not token:
        token = input("Please enter your GitHub Personal Access Token (or press Enter to exit): ").strip()
        if not token: return
        save_config(token)

    # 2. Get Version
    try:
        with open("version.json", "r") as f:
            version = json.load(f)["version"]
    except Exception as e:
        print(f"Error reading version.json: {e}")
        return

    repo = "syntaxmaciah/R8RS"
    tag = f"v{version}"
    zip_path = "dist/TCD_Update.zip"
    
    if not os.path.exists(zip_path):
        print(f"Error: {zip_path} not found. Did you run bump_version.bat?")
        return

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    # 3. Create Release
    print(f"Creating release {tag} on GitHub...")
    release_data = {
        "tag_name": tag,
        "name": f"Tactical Command Deck {tag}",
        "body": f"Automated update for version {version}",
        "draft": False,
        "prerelease": False
    }
    
    response = requests.post(f"https://api.github.com/repos/{repo}/releases", 
                             headers=headers, json=release_data)
    
    if response.status_code == 201:
        release_id = response.json()["id"]
        upload_url = response.json()["upload_url"].replace("{?name,label}", "")
        print(f"Release created successfully! (ID: {release_id})")
    elif response.status_code == 422:
        error_data = response.json()
        print(f"Release/Tag {tag} conflict (422): {error_data.get('message')}")
        for err in error_data.get('errors', []):
            print(f" - {err.get('resource')} {err.get('code')}: {err.get('message')}")

        print(f"Fetching info for tag {tag}...")
        # 1. Try fetching release by tag name
        response = requests.get(f"https://api.github.com/repos/{repo}/releases/tags/{tag}", headers=headers)
        
        if response.status_code == 404:
            # 2. Check if the TAG exists but has no RELEASE
            print(f"No release found for {tag}, checking if tag exists...")
            tag_resp = requests.get(f"https://api.github.com/repos/{repo}/tags", headers=headers)
            if tag_resp.status_code == 200:
                tags = [t['name'] for t in tag_resp.json()]
                if tag in tags:
                    print(f"Found tag '{tag}' with no release. This can happen if a release was deleted but the tag remained.")
                    print("Attempting to create a release using the existing tag...")
                    # We try to create it again but it might fail if we don't handle the "already_exists" error
                    # Actually, if the tag exists, POST /releases should still work if there's no release.
                    # If it's failing with 422, there's likely a hidden draft or something.
                else:
                    print(f"Tag '{tag}' not found in: {tags}")
            
            # 3. Fallback: List all releases including drafts
            print("Searching all releases (including drafts)...")
            response = requests.get(f"https://api.github.com/repos/{repo}/releases", headers=headers)
            if response.status_code == 200:
                releases = response.json()
                matching = [r for r in releases if r["tag_name"] == tag]
                if matching:
                    response.status_code = 200 
                    release_data = matching[0]
                else:
                    print(f"Could not find any release matching tag {tag}")
                    return
            else:
                print(f"Error listing releases: {response.status_code}")
                return

        if response.status_code == 200:
            if not 'release_data' in locals():
                release_data = response.json()
            release_id = release_data["id"]
            upload_url = release_data["upload_url"].replace("{?name,label}", "")
            
            # Check for existing asset and delete it if found
            for asset in release_data.get("assets", []):
                if asset["name"] == os.path.basename(zip_path):
                    print(f"Deleting existing asset {asset['name']}...")
                    requests.delete(asset["url"], headers=headers)
        else:
            print(f"Error fetching existing release: {response.status_code}")
            print(response.text)
            return
    else:
        print(f"Error creating release: {response.status_code}")
        print(response.text)
        return

    # 4. Upload Asset
    print(f"Uploading {zip_path}...")
    with open(zip_path, "rb") as f:
        upload_headers = headers.copy()
        upload_headers["Content-Type"] = "application/zip"
        params = {"name": os.path.basename(zip_path)}
        
        response = requests.post(upload_url, headers=upload_headers, params=params, data=f)

    if response.status_code == 201:
        download_url = response.json()["browser_download_url"]
        print("\n" + "="*40)
        print("SUCCESS! Update is live on GitHub.")
        print("Copy this link to your Google Doc:")
        print(download_url)
        print("="*40)
    else:
        print(f"Error uploading asset: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    release()
