import requests
import time
import argparse
import os
import pandas as pd
from datetime import datetime
import re
import sys
import threading
import base64

try:
    import vlc
except ImportError:
    print("Error: The 'vlc' module was not found.")
    print("Please install with: pip install python-vlc")
    exit(1)

try:
    import tkinter as tk
except ImportError:
    print("Warning: Tkinter not found, --view mode disabled.")
    tk = None

# --- Configuration ---
SERVER_ADDRESS = "192.168.0.150:9191"
DISPATCHARR_USERNAME = "<username>"
DISPATCHARR_PASSWORD = "<password>"
BASELINE_M3U_URL = f"http://{SERVER_ADDRESS}/output/m3u?direct=true"
NORMAL_M3U_URL = f"http://{SERVER_ADDRESS}/output/m3u"
TARGET_GROUP = "Nederland"
START_CHANNEL_NAME = "NPO1"
CHANNEL_COUNT = 10
RESULTS_FILE = "tuning_results.csv"
REPORT_FILE = "tuning_report.html"
THUMBNAIL_DIR = "thumbnails"
REQUEST_TIMEOUT = 15
MIN_PLAYBACK_TIME_MS = 200
VLC_USER_AGENT = "TiviMate/4.7.0 (Linux; Android 11)"
VLC_EXECUTABLE_PATH = "C:\\Program Files\\VideoLAN\\VLC\\vlc.exe"
VLC_ARGS = ["-Iskins", "--no-video-title-show", "--quiet"]

# --- VLC Helper ---
class PlayerState:
    def __init__(self):
        self.playing_event = threading.Event()
        self.error_event = threading.Event()
        self.has_warned_about_error = False

def vlc_event_handler(event, player_state):
    if event.type == vlc.EventType.MediaPlayerPlaying:
        player_state.playing_event.set()
    elif event.type == vlc.EventType.MediaPlayerEncounteredError:
        player_state.error_event.set()

def encode_thumbnail_to_base64(path):
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None

# --- Dispatcharr API ---
def dispatcharr_login(session, username, password):
    try:
        base_url = f"http://{SERVER_ADDRESS}"
        token_url = f"{base_url}/api/accounts/token/"
        response = session.post(token_url, json={"username": username, "password": password}, timeout=10)
        response.raise_for_status()
        tokens = response.json()
        access_token = tokens.get("access")
        if not access_token:
            print("API Error: Login returned no token.")
            return False
        session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": base_url + "/"
        })
        print("Successfully authenticated with Dispatcharr API using JWT.")
        return True
    except requests.exceptions.RequestException as e:
        print(f"API Error: Login failed: {e}")
        return False

def get_dispatcharr_profiles(session):
    url = f"http://{SERVER_ADDRESS}/api/core/streamprofiles/"
    try:
        r = session.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except:
        return None

def get_active_profile(session):
    url = f"http://{SERVER_ADDRESS}/api/core/settings/"
    try:
        r = session.get(url, timeout=10)
        r.raise_for_status()
        settings = r.json()
        if not isinstance(settings, list):
            return None, None
        for s in settings:
            if s.get("key") == "default-stream-profile":
                return s.get("value"), s.get("id")
        return None, None
    except:
        return None, None

def set_active_profile(session, settings_id, profile_id):
    try:
        url = f"http://{SERVER_ADDRESS}/api/core/settings/{settings_id}/"
        payload = {"value": str(profile_id)}
        r = session.patch(url, json=payload, timeout=10)
        r.raise_for_status()
        print(f"  -> Set active profile to ID: {profile_id}")
        return True
    except:
        return False

# --- Core ---
def parse_m3u(url, session):
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching M3U from {url}: {e}")
        return []
    lines = r.text.splitlines()
    all_channels = []
    for i in range(len(lines)):
        if lines[i].startswith("#EXTINF:"):
            try:
                group_match = re.search(r'group-title="([^"]+)"', lines[i])
                name_match = re.search(r'tvg-name="([^"]+)"', lines[i])
                name = name_match.group(1) if name_match else lines[i].split(',')[-1].strip()
                if group_match and group_match.group(1) == TARGET_GROUP:
                    all_channels.append({"name": name, "url": lines[i+1].strip()})
            except IndexError:
                continue
    start_index = next((i for i, ch in enumerate(all_channels) if START_CHANNEL_NAME in ch['name']), -1)
    if start_index == -1:
        print(f"Warning: Start channel '{START_CHANNEL_NAME}' not found in group '{TARGET_GROUP}'.")
        return []
    return all_channels[start_index:start_index+CHANNEL_COUNT]

def measure_tune_time_with_vlc(player, channel_info, gui_root=None, take_thumbnail=False):
    url = channel_info['url']
    print(f"  -> Testing stream: {channel_info['name']} ({url})")
    player_state = PlayerState()
    events = player.event_manager()
    events.event_attach(vlc.EventType.MediaPlayerPlaying, vlc_event_handler, player_state)
    events.event_attach(vlc.EventType.MediaPlayerEncounteredError, vlc_event_handler, player_state)
    media = player.get_instance().media_new(url)
    media.add_option(f'http-user-agent={VLC_USER_AGENT}')
    player.set_media(media)
    start_time = time.perf_counter()
    player.play()
    playback_started_time = time.perf_counter()
    while time.perf_counter() - playback_started_time < REQUEST_TIMEOUT:
        if player.get_time() > MIN_PLAYBACK_TIME_MS:
            end_time = time.perf_counter()
            thumbnail_path = None
            if take_thumbnail:
                safe_name = re.sub(r'[\\/*?:"<>|]', "", channel_info['name'])
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{safe_name}_{ts}.png"
                thumbnail_path = os.path.join(THUMBNAIL_DIR, filename)
                player.video_take_snapshot(0, thumbnail_path, 0, 0)
                time.sleep(0.2)
            player.stop()
            return (end_time - start_time), thumbnail_path
        if gui_root:
            gui_root.update()
        time.sleep(0.05)
    player.stop()
    return None, None

def run_test_session(channels_to_test, view_mode=False, thumbnail_mode=False):
    if thumbnail_mode and not os.path.exists(THUMBNAIL_DIR):
        os.makedirs(THUMBNAIL_DIR)
    instance_args = VLC_ARGS[:]
    root = None
    if not view_mode:
        instance_args.append('--vout=dummy')
    else:
        if not tk:
            print("Warning: Tkinter not available, cannot run in --view mode.")
            return {}
        root = tk.Tk()
        root.geometry("854x480")
        video_frame = tk.Frame(root, bg="black")
        video_frame.pack(fill=tk.BOTH, expand=True)
        root.bind('<Escape>', lambda e: root.destroy())
    try:
        instance = vlc.Instance(' '.join(instance_args))
        player = instance.media_player_new()
        if root:
            if sys.platform == "win32":
                player.set_hwnd(video_frame.winfo_id())
            else:
                player.set_xwindow(video_frame.winfo_id())
    except Exception as e:
        print(f"Error initializing VLC: {e}")
        if root: root.destroy()
        return {}
    results = {}
    try:
        for channel in channels_to_test:
            tune_time, thumb_path = measure_tune_time_with_vlc(player, channel, root, thumbnail_mode)
            base_name = re.sub(r'\s*ᴿᴬᵂ.*', '', channel['name'])
            results[base_name] = {'time': tune_time, 'thumb': thumb_path}
            if root: root.update()
    finally:
        player.release()
        instance.release()
        if root: root.destroy()
    return results

# --- Reporting ---
def display_results(df):
    if df.empty:
        print("No results to display.")
        return
    profile_cols = [c for c in df.columns if not c.endswith('_thumb')]
    headers = ["Channel"] + profile_cols
    print("\n--- Channel Tuning Performance ---")
    print("{:<25}".format(headers[0]), end="")
    for h in headers[1:]:
        print("{:>25}".format(h.split('\n')[0]), end="") # Only print profile name
    print("\n" + "-" * (25 * len(headers)))
    for channel_name, row_data in df.iterrows():
        print("{:<25}".format(channel_name), end="")
        for col in profile_cols:
            time_val = row_data[col]
            content = f"{time_val:.4f}s" if pd.notna(time_val) else "Failed"
            print("{:>25}".format(content), end="")
        print()

def generate_html_report(df):
    if df.empty:
        print("No results to include in report.")
        return

    profile_cols = [c for c in df.columns if not c.endswith('_thumb')]
    
    # Extract profile names and timestamps for headers
    profile_headers_data = []
    for col in profile_cols:
        parts = col.split('\n')
        name = parts[0]
        timestamp = parts[1] if len(parts) > 1 else ""
        profile_headers_data.append({"full_col_name": col, "name": name, "timestamp": timestamp})

    avg_row_data = df[profile_cols].mean()
    profile_avgs = {p['name']: avg_row_data[p['full_col_name']] for p in profile_headers_data}

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        # --- HTML Head and Styles ---
        f.write("""<!DOCTYPE html>
        <html><head><title>IPTV Tuning Report</title>
        <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; margin: 2em; background-color: #f8f9fa; }
        table { border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; background-color: #fff; }
        th, td { border: 1px solid #dee2e6; padding: 0.75rem; text-align: center; vertical-align: middle; }
        th { background-color: #f1f1f1; color: #333; font-weight: 600; } /* Lighter background for headers */
        th.avg-header { background-color: #343a40; color: #fff; } /* Darker for average summary table */
        h1, h2 { border-bottom: 2px solid #007bff; padding-bottom: 10px; margin-top: 25px; margin-bottom: 15px; color: #333; }
        .fast { background-color: #d4edda; }
        .medium { background-color: #fff3cd; }
        .slow { background-color: #f8d7da; }
        .fail { background-color: #e9ecef; color: #6c757d; }
        img { max-width: 150px; height: auto; display: block; margin: 0 auto; }
        b { font-weight: 600; }
        </style></head><body>
        <h1>IPTV Channel Tuning Performance</h1>""")

        # --- Profile Averages Table ---
        f.write("<h2>Profile Averages</h2>")
        f.write("<table style='width: 60%; margin-left: auto; margin-right: auto;'><thead><tr><th class='avg-header'>Profile</th><th class='avg-header'>Average Time (s)</th></tr></thead><tbody>")
        for name, avg in sorted(profile_avgs.items(), key=lambda item: item[1] if pd.notna(item[1]) else float('inf')):
            if pd.notna(avg):
                css_class = "fast" if avg < 1.5 else "medium" if avg < 3.0 else "slow"
                content = f"{avg:.4f}"
            else:
                css_class = "fail"
                content = "N/A"
            f.write(f"<tr><td>{name}</td><td class='{css_class}'>{content}</td></tr>")
        f.write("</tbody></table>")

        # --- Detailed Results Table ---
        f.write("<h2>Detailed Results</h2>")
        f.write("<table><thead>")
        
        # First header row (Channel + Profile Names with Timestamps)
        f.write("<tr>")
        f.write("<th rowspan='2'>Channel</th>")
        for p_data in profile_headers_data:
            f.write(f"<th colspan='2'>{p_data['name']}<br>{p_data['timestamp']}</th>")
        f.write("</tr>")

        # Second header row (Time + Thumbnail)
        f.write("<tr>")
        for _ in profile_headers_data:
            f.write("<th>Time</th><th>Thumbnail</th>")
        f.write("</tr>")
        
        f.write("</thead><tbody>")

        for channel_name, row_data in df.iterrows():
            f.write("<tr>")
            f.write(f"<td><b>{channel_name}</b></td>")
            for p_data in profile_headers_data:
                col = p_data['full_col_name']
                time_val = row_data[col]
                if pd.notna(time_val):
                    css_class = "fast" if time_val < 1.5 else "medium" if time_val < 3.0 else "slow"
                    content = f"{time_val:.4f}s"
                else:
                    css_class = "fail"
                    content = "Failed"
                f.write(f"<td class='{css_class}'>{content}</td>")
                thumb_path = row_data.get(f"{col}_thumb")
                if pd.notna(thumb_path) and os.path.exists(thumb_path):
                    b64 = encode_thumbnail_to_base64(thumb_path)
                    f.write(f"<td><img src='data:image/png;base64,{b64}' alt='Thumbnail for {channel_name} on {p_data['name']}'></td>")
                else:
                    f.write("<td>—</td>")
            f.write("</tr>")
        
        # --- Averages Row in Detailed Table ---
        f.write("<tr><td><b>Average</b></td>")
        for p_data in profile_headers_data:
            avg = profile_avgs.get(p_data['name'])
            if pd.notna(avg):
                css_class = "fast" if avg < 1.5 else "medium" if avg < 3.0 else "slow"
                content = f"<b>{avg:.4f}s</b>"
            else:
                css_class = "fail"
                content = "N/A"
            f.write(f"<td class='{css_class}'>{content}</td><td>—</td>")
        f.write("</tr></tbody></table></body></html>")

    print(f"HTML report generated: {REPORT_FILE}")

# --- Main ---
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Reset previous results by deleting the CSV file.")
    parser.add_argument("--view", action="store_true", help="Show VLC video window during testing (requires Tkinter).")
    parser.add_argument("--report", action="store_true", help="Generate an HTML report.")
    parser.add_argument("--thumbnail", action="store_true", help="Capture thumbnails for each channel/profile in the report.")
    args = parser.parse_args()

    api_session = requests.Session()
    if not dispatcharr_login(api_session, DISPATCHARR_USERNAME, DISPATCHARR_PASSWORD):
        return

    profiles = get_dispatcharr_profiles(api_session)
    active_profile_uuid, settings_id = get_active_profile(api_session)
    
    if not profiles or not settings_id:
        print("Could not retrieve Dispatcharr profiles or settings ID.")
        return

    if args.reset and os.path.exists(RESULTS_FILE):
        os.remove(RESULTS_FILE)
        print(f"Deleted previous results file: {RESULTS_FILE}")

    print("Available Streaming Profiles:")
    for i, p in enumerate(profiles):
        print(f"  {i+1}) {p['name']} (ID: {p['id']})")

    selection = input("Enter profile numbers to test (e.g., 1,3 or all): ")
    if selection.lower() == 'all':
        selected_profiles = profiles
    else:
        try:
            indices = [int(i.strip())-1 for i in selection.split(',')]
            selected_profiles = [profiles[i] for i in indices if 0 <= i < len(profiles)]
            if not selected_profiles:
                print("No valid profiles selected.")
                return
        except ValueError:
            print("Invalid selection. Please enter comma-separated numbers or 'all'.")
            return

    df = pd.DataFrame()

    # Test Baseline (Direct)
    baseline_channels = parse_m3u(BASELINE_M3U_URL, requests.Session())
    if baseline_channels:
        print("\n--- Testing Baseline (Direct) Profile ---")
        baseline_results = run_test_session(baseline_channels, args.view, args.thumbnail)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        col = f"Baseline (direct)\n{ts}"
        df[col] = pd.Series({k: v['time'] for k,v in baseline_results.items()})
        df[f"{col}_thumb"] = pd.Series({k: v['thumb'] for k,v in baseline_results.items()})
    else:
        print("Skipping Baseline (Direct) test as no channels were found or parsed.")

    # Test selected Dispatcharr profiles
    for profile in selected_profiles:
        print(f"\n--- Testing Profile: {profile['name']} ---")
        if not set_active_profile(api_session, settings_id, profile['id']):
            print(f"  Failed to set active profile to {profile['name']}. Skipping.")
            continue
        time.sleep(2) # Give Dispatcharr time to apply profile change
        profile_channels = parse_m3u(NORMAL_M3U_URL, api_session)
        if profile_channels:
            profile_results = run_test_session(profile_channels, args.view, args.thumbnail)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            col = f"{profile['name']}\n{ts}"
            df[col] = pd.Series({k: v['time'] for k,v in profile_results.items()})
            df[f"{col}_thumb"] = pd.Series({k: v['thumb'] for k,v in profile_results.items()})
        else:
            print(f"Skipping profile {profile['name']} test as no channels were found or parsed.")
    
    # Reset to original active profile
    if active_profile_uuid:
        print(f"\n--- Resetting to original active profile (ID: {active_profile_uuid}) ---")
        set_active_profile(api_session, settings_id, active_profile_uuid)
    
    if not df.empty:
        # Reorder columns to ensure Baseline is first if it exists
        time_cols = sorted([c for c in df.columns if not c.endswith('_thumb')], key=lambda x: 0 if 'Baseline' in x else 1)
        all_cols = []
        for c in time_cols:
            all_cols.append(c)
            all_cols.append(f"{c}_thumb")
        df = df[all_cols]
        df.to_csv(RESULTS_FILE)
        print(f"Results saved to: {RESULTS_FILE}")
    else:
        print("No test data was generated.")
    
    display_results(df)
    
    if args.report:
        generate_html_report(df)

if __name__ == "__main__":
    main()
