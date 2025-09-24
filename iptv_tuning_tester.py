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

# --- IMPORTANT ---
# This version requires the python-vlc library for accurate measurements.
# Please install it using: pip install python-vlc
try:
    import vlc
except ImportError:
    print("Error: The 'vlc' module was not found.")
    print("Please install the required library by running: pip install python-vlc")
    exit(1)

# Tkinter is used for the video window in --view mode. It's part of standard Python.
try:
    import tkinter as tk
except ImportError:
    print("Warning: Tkinter module not found. The --view mode will not be available.")
    tk = None


# --- Configuration ---
# The IP address and port of your server
SERVER_ADDRESS = "192.168.0.150:9191"
# The URL for the baseline M3U (direct, no proxy)
BASELINE_M3U_URL = f"http://{SERVER_ADDRESS}/output/m3u?direct=true"
# The URL for the normal M3U (proxied)
NORMAL_M3U_URL = f"http://{SERVER_ADDRESS}/output/m3u"
# The name of the group to test in the M3U file
TARGET_GROUP = "Nederland"
# The name of the channel to start the test from
START_CHANNEL_NAME = "NPO1"
# The number of channels to test
CHANNEL_COUNT = 10
# The file to store results
RESULTS_FILE = "tuning_results.csv"
# The file for the HTML report
REPORT_FILE = "tuning_report.html"
# The directory to store thumbnails
THUMBNAIL_DIR = "thumbnails"
# Request timeout in seconds for a channel to start playing
REQUEST_TIMEOUT = 15
# The minimum playback time (in ms) to consider a stream successfully tuned.
# This ensures we measure actual playback, not just the pre-buffer.
MIN_PLAYBACK_TIME_MS = 200
# User-Agent to emulate a specific client. This is crucial as some servers
# will reject connections from standard Python clients.
USER_AGENT = "TiviMate/4.7.0 (Linux; Android 11)"
# Optional: Provide a direct path to the VLC executable if python-vlc cannot find it.
VLC_EXECUTABLE_PATH = "C:\\Program Files\\VideoLAN\\VLC\\vlc.exe"
# Optional: Provide additional command-line arguments for the VLC instance.
VLC_ARGS = ["-Iskins", "--no-video-title-show", "--quiet"]

# --- Helper class for event-driven measurement ---
class PlayerState:
    """A simple class to share state between the event handler and the main thread."""
    def __init__(self):
        self.playing_event = threading.Event()
        self.error_event = threading.Event()
        self.has_warned_about_error = False

def vlc_event_handler(event, player_state):
    """
    Callback function for libvlc events. Signals when the player enters 'playing' or 'error' state.
    """
    if event.type == vlc.EventType.MediaPlayerPlaying:
        player_state.playing_event.set()
    elif event.type == vlc.EventType.MediaPlayerEncounteredError:
        player_state.error_event.set()


def parse_m3u(url, session):
    """
    Downloads and parses an M3U file to extract channel information using a session.
    """
    print(f"Fetching M3U from {url}...")
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error: Could not fetch M3U file. {e}")
        return []

    lines = response.text.splitlines()
    all_channels = []
    
    for i in range(len(lines)):
        if lines[i].startswith("#EXTINF:"):
            try:
                group_match = re.search(r'group-title="([^"]+)"', lines[i])
                name_match = re.search(r'tvg-name="([^"]+)"', lines[i])
                
                if not name_match:
                    name = lines[i].split(',')[-1].strip()
                else:
                    name = name_match.group(1)

                if group_match and group_match.group(1) == TARGET_GROUP:
                    all_channels.append({
                        "name": name,
                        "url": lines[i+1].strip()
                    })
            except IndexError:
                continue
    
    start_index = next((i for i, ch in enumerate(all_channels) if START_CHANNEL_NAME in ch['name']), -1)
            
    if start_index == -1:
        print(f"Warning: Starting channel '{START_CHANNEL_NAME}' not found in group '{TARGET_GROUP}'.")
        return []

    return all_channels[start_index : start_index + CHANNEL_COUNT]

def get_profile_type(url, name):
    """
    Determines the streaming profile based on the URL and channel name.
    """
    if 'ᴿᴬᵂ' in name: return "ffmpeg"
    if "/proxy/" in url: return "proxy"
    if not url.startswith(f"http://{SERVER_ADDRESS}"): return "direct"
    return "proxy"

def measure_tune_time_with_vlc(player, channel_info, gui_root=None, take_thumbnail=False):
    """
    Measures the time until the stream is confirmed to be rendering video.
    """
    url = channel_info['url']
    print(f"  -> Testing URL: {url}")
    
    player_state = PlayerState()
    
    events = player.event_manager()
    events.event_attach(vlc.EventType.MediaPlayerPlaying, vlc_event_handler, player_state)
    events.event_attach(vlc.EventType.MediaPlayerEncounteredError, vlc_event_handler, player_state)

    media = player.get_instance().media_new(url)
    media.add_option(f'http-user-agent={USER_AGENT}')
    player.set_media(media)

    start_time = time.perf_counter()
    player.play()
    
    def detach_events():
        events.event_detach(vlc.EventType.MediaPlayerPlaying)
        events.event_detach(vlc.EventType.MediaPlayerEncounteredError)

    playback_started_time = time.perf_counter()
    while time.perf_counter() - playback_started_time < REQUEST_TIMEOUT:
        if player_state.error_event.is_set() and not player_state.has_warned_about_error:
            print("  -> Warning: VLC encountered a transient stream error. Will continue to wait...")
            player_state.has_warned_about_error = True # Only warn once

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
            detach_events()
            return (end_time - start_time), thumbnail_path
        
        if gui_root:
            gui_root.update()
        time.sleep(0.05)

    print(f"  -> Failed to tune: Playback did not start within {REQUEST_TIMEOUT}s.")
    player.stop()
    detach_events()
    return None, None

def run_test_session(m3u_url, view_mode=False, thumbnail_mode=False):
    """
    Runs a full performance test session for the given M3U URL using libvlc.
    """
    session = requests.Session()
    session.headers.update({'User-Agent': USER_AGENT})

    channels_to_test = parse_m3u(m3u_url, session)
    if not channels_to_test:
        print("Could not retrieve channel list. Aborting test session.")
        return {}, "unknown"

    if thumbnail_mode and not os.path.exists(THUMBNAIL_DIR):
        os.makedirs(THUMBNAIL_DIR)

    instance_args = VLC_ARGS[:]
    root = None
    if not view_mode:
        instance_args.append('--vout=dummy')
        print("\nLaunching VLC in Headless mode for measurement...")
    else:
        if not tk:
            print("Error: Tkinter is required for --view mode but not found. Aborting.")
            return {}, "unknown"
        print(f"\nLaunching VLC (Visible) for measurement...")
        root = tk.Tk()
        root.title("IPTV Tuning Test - Press ESC to close")
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
        print(f"Error creating VLC instance: {e}")
        if root: root.destroy()
        return {}, "unknown"

    print(f"\nStarting test for {len(channels_to_test)} channels...")
    results = {}
    profile_type = get_profile_type(channels_to_test[0]['url'], channels_to_test[0]['name']) if channels_to_test else "unknown"

    try:
        for channel in channels_to_test:
            print(f"- Testing '{channel['name']}'...")
            if root: root.title(f"Testing: {channel['name']}")
            tune_time, thumb_path = measure_tune_time_with_vlc(player, channel, root, thumbnail_mode)
            base_name = channel['name'].replace(' ᴿᴬᵂ', '')
            results[base_name] = {'time': tune_time, 'thumb': thumb_path}
            if root:
                root.update()
    finally:
        print("\nTest session finished. Releasing VLC instance.")
        player.release()
        instance.release()
        if root:
            root.destroy()

    return results, profile_type
    
def display_results():
    """
    Loads results from the CSV and prints a formatted table with averages.
    """
    if not os.path.exists(RESULTS_FILE):
        print("No results file to display.")
        return
        
    df = pd.read_csv(RESULTS_FILE, index_col=0)
    numeric_cols = df.select_dtypes(include=['number']).columns
    averages = df[numeric_cols].mean()
    
    avg_header = {col: f"{avg:.4f}s avg" for col, avg in averages.items()}
    
    time_cols_df = df.drop(columns=[col for col in df if col.endswith('_thumb')], errors='ignore')

    df_display = time_cols_df.map(lambda x: f"{x:.4f}s" if pd.notna(x) and isinstance(x, (int, float)) else "Failed")
    df_display.columns = [f"{col}\n({avg_header.get(col, 'N/A')})" for col in time_cols_df.columns]

    print("\n--- Channel Tuning Performance ---")
    print(df_display.to_string())
    print("----------------------------------\n")

def generate_html_report():
    """
    Generates a styled HTML report from the results CSV file.
    """
    if not os.path.exists(RESULTS_FILE):
        print("No results file found. Cannot generate HTML report.")
        return

    df = pd.read_csv(RESULTS_FILE, index_col=0)
    
    time_cols = [col for col in df.columns if not col.endswith('_thumb')]
    averages = df[time_cols].mean(numeric_only=True)

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>IPTV Tuning Performance Report</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 2rem; background-color: #f4f7f9; color: #333; }}
            .container {{ max-width: 95%; margin: 0 auto; background-color: #ffffff; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
            h1 {{ text-align: center; color: #1a202c; margin-bottom: 0.5rem; }}
            p.timestamp {{ text-align: center; color: #718096; margin-top: 0; margin-bottom: 2rem; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; table-layout: fixed; }}
            th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #e2e8f0; word-wrap: break-word; }}
            th {{ background-color: #edf2f7; font-weight: 600; white-space: pre-wrap; }}
            tr:nth-child(even) {{ background-color: #f7fafc; }}
            th.channel-col {{ width: 15%; }}
            td img {{ max-width: 120px; height: auto; border-radius: 4px; }}
            td {{ font-family: 'Menlo', 'Consolas', monospace; vertical-align: middle; }}
            .avg-row td {{ font-weight: bold; background-color: #edf2f7; border-top: 2px solid #cbd5e0; }}
            .fast {{ background-color: #c6f6d5; color: #22543d; }}
            .medium {{ background-color: #feebc8; color: #805b1b; }}
            .slow {{ background-color: #fed7d7; color: #822727; }}
            .failed {{ background-color: #fed7d7; font-weight: bold; color: #9b2c2c; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>IPTV Tuning Performance Report</h1>
            <p class="timestamp">Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <table>
                <thead>
                    <tr>
                        <th class="channel-col">Channel</th>
    """
    has_thumbnails = any(col.endswith('_thumb') for col in df.columns)
    for col in time_cols:
        col_name, _, col_date = col.partition('\\n')
        colspan = 2 if has_thumbnails else 1
        html += f'<th colspan="{colspan}">{col_name}<br><small>{col_date}</small></th>'
    html += "</tr>"

    if has_thumbnails:
        html += '<tr><th></th>' 
        for _ in time_cols:
            html += '<th>Time</th><th>Thumbnail</th>'
        html += '</tr>'

    html += "</thead><tbody>"

    for index, row in df.iterrows():
        html += f"<tr><td>{index}</td>"
        for col in time_cols:
            item = row[col]
            if pd.isna(item):
                cell_class = "failed"
                cell_content = "Failed"
            else:
                cell_content = f"{item:.4f}s"
                if item < 2: cell_class = "fast"
                elif item < 5: cell_class = "medium"
                else: cell_class = "slow"
            html += f'<td class="{cell_class}">{cell_content}</td>'
            
            if has_thumbnails:
                thumb_col = f"{col}_thumb"
                thumb_path = row.get(thumb_col)
                if pd.notna(thumb_path) and os.path.exists(thumb_path):
                    try:
                        with open(thumb_path, "rb") as image_file:
                            encoded_string = base64.b64encode(image_file.read()).decode()
                        html += f'<td><img src="data:image/png;base64,{encoded_string}" alt="thumbnail"></td>'
                    except Exception:
                        html += '<td>Error</td>'
                else:
                    html += '<td></td>'
        html += "</tr>"

    html += '<tr class="avg-row"><td>Average Time (s)</td>'
    for col in time_cols:
        avg = averages.get(col)
        colspan = 2 if has_thumbnails else 1
        if pd.isna(avg):
            html += f'<td colspan="{colspan}">N/A</td>'
        else:
            html += f'<td colspan="{colspan}">{avg:.4f}s</td>'
    html += "</tr>"

    html += """
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    try:
        with open(REPORT_FILE, "w", encoding='utf-8') as f:
            f.write(html)
        print(f"\nSuccessfully generated HTML report: {REPORT_FILE}")
    except IOError as e:
        print(f"\nError: Could not write HTML report file. {e}")

def main():
    """
    Main script execution logic.
    """
    if os.path.exists(VLC_EXECUTABLE_PATH):
        vlc_install_dir = os.path.dirname(VLC_EXECUTABLE_PATH)
        if 'VLC_PLUGIN_PATH' not in os.environ:
             os.environ['VLC_PLUGIN_PATH'] = vlc_install_dir

    parser = argparse.ArgumentParser(description="IPTV Channel Tuning Performance Tester")
    parser.add_argument("--reset", action="store_true", help="Delete existing results and start a new full test run.")
    parser.add_argument("--view", action="store_true", help="Launch a visible VLC window for real-time viewing.")
    parser.add_argument("--report", action="store_true", help="Generate an HTML report from the results.")
    parser.add_argument("--thumbnail", action="store_true", help="Capture a thumbnail of each stream for the report.")
    args = parser.parse_args()
    
    # Determine if any action other than just generating a report is requested.
    is_test_run = not (args.report and not args.reset and not args.view and not args.thumbnail and os.path.exists(RESULTS_FILE))
    
    if is_test_run:
        if args.reset and os.path.exists(RESULTS_FILE):
            print(f"Reset flag detected. Deleting '{RESULTS_FILE}'...")
            os.remove(RESULTS_FILE)

        if not os.path.exists(RESULTS_FILE):
            print("No results file found. Starting initial run with baseline.")
            baseline_results, baseline_profile = run_test_session(BASELINE_M3U_URL, args.view, args.thumbnail)
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            col_name = f"Baseline ({baseline_profile})\\n{timestamp}"
            
            df_data = {
                col_name: {k: v['time'] for k, v in baseline_results.items()},
                f"{col_name}_thumb": {k: v['thumb'] for k, v in baseline_results.items()}
            }
            df = pd.DataFrame(df_data)
            
            normal_results, normal_profile = run_test_session(NORMAL_M3U_URL, args.view, args.thumbnail)
            if normal_results:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                col_name = f"{normal_profile.capitalize()}\\n{timestamp}"
                df[col_name] = pd.Series({k: v['time'] for k, v in normal_results.items()})
                df[f"{col_name}_thumb"] = pd.Series({k: v['thumb'] for k, v in normal_results.items()})

            df.to_csv(RESULTS_FILE)
        else:
            print(f"Found '{RESULTS_FILE}'. Appending a new test run.")
            df = pd.read_csv(RESULTS_FILE, index_col=0)
            
            new_results, new_profile = run_test_session(NORMAL_M3U_URL, args.view, args.thumbnail)
            if new_results:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                col_name = f"{new_profile.capitalize()}\\n{timestamp}"
                
                df[col_name] = pd.Series({k: v['time'] for k, v in new_results.items()})
                df[f"{col_name}_thumb"] = pd.Series({k: v['thumb'] for k, v in new_results.items()})

                df.to_csv(RESULTS_FILE)

    display_results()
    
    if args.report:
        generate_html_report()

if __name__ == "__main__":
    main()

