# IPTV Tuning Tester with Multi-Thumbnail HTML Reporting
# ------------------------------------------------------
# Uses FFprobe for reliable stream analysis and VLC for performance testing.
# Includes optional, real-time Docker log tailing over SSH with error correlation.
# Console output is mirrored to log.txt.

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
import textwrap
import getpass
import socket

# --- Dependency Checks ---
try:
    import vlc
except ImportError:
    print("Error: The 'vlc' module was not found.")
    print("Please install with: pip install python-vlc")
    exit(1)

try:
    import ffmpeg
except ImportError:
    print("Error: The 'ffmpeg-python' module was not found.")
    print("Please install with: pip install ffmpeg-python")
    print("You also need to install the FFmpeg software on your system. See https://ffmpeg.org/download.html")
    exit(1)

try:
    import paramiko
except ImportError:
    print("Warning: The 'paramiko' module was not found. The --debug feature will be limited.")
    print("To enable it, please install with: pip install paramiko")
    paramiko = None

try:
    import tkinter as tk
except ImportError:
    print("Warning: Tkinter not found, --view mode disabled.")
    tk = None

# --- Configuration ---
SERVER_ADDRESS = "192.168.0.150:9191"
DISPATCHARR_USERNAME = "<USERNAME>"
DISPATCHARR_PASSWORD = "<PASSWORD>"
BASELINE_M3U_URL = f"http://{SERVER_ADDRESS}/output/m3u?direct=true"
NORMAL_M3U_URL = f"http://{SERVER_ADDRESS}/output/m3u"
TARGET_GROUP = "Nederland"
START_CHANNEL_NAME = "NPO1"
CHANNEL_COUNT = 10
RESULTS_FILE = "tuning_results.csv"
REPORT_FILE = "tuning_report.html"
THUMBNAIL_DIR = "thumbnails"
REQUEST_TIMEOUT = 15 # For channel tuning
FFPROBE_TIMEOUT = 10 # For stream analysis
MIN_PLAYBACK_TIME_MS = 200
VLC_USER_AGENT = "TiviMate/4.7.0 (Linux; Android 11)"
VLC_ARGS = ["-Iskins", "--no-video-title-show", "--quiet"]

# --- Docker Log Tailing Configuration ---
SSH_HOSTNAME = "NAS"
SSH_USERNAME = "lucas"
SSH_PRIVATE_KEY_PATH = r"C:\Users\lmole\.ssh\openssh2.key"
DOCKER_CONTAINER_NAME = "dispatcharr"

# --- Helper Classes ---
class Tee:
    """Helper class to redirect print output to multiple files in a thread-safe manner."""
    def __init__(self, *files, lock):
        self.files = files
        self.lock = lock
    def write(self, obj):
        with self.lock:
            for f in self.files:
                f.write(obj)
                f.flush()
    def flush(self):
        with self.lock:
            for f in self.files:
                f.flush()

class PlayerState:
    def __init__(self):
        self.playing_event = threading.Event()
        self.error_event = threading.Event()

# --- Helper Functions ---
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

def get_stream_info_ffprobe(url):
    """Uses FFprobe to get accurate stream info, with a retry mechanism."""
    max_retries = 3
    retry_delay = 2 # seconds
    last_error = ""

    for attempt in range(max_retries):
        try:
            probe_opts = { "user_agent": VLC_USER_AGENT, "timeout": FFPROBE_TIMEOUT * 1_000_000 }
            probe = ffmpeg.probe(url, **probe_opts)
            
            info = {
                "input": ", ".join(probe.get('format', {}).get('format_name', 'N/A').split(',')).upper(),
                "video": "N/A", "audio": "N/A"
            }
            video_stream = next((s for s in probe['streams'] if s['codec_type'] == 'video'), None)
            audio_stream = next((s for s in probe['streams'] if s['codec_type'] == 'audio'), None)
            if video_stream: info['video'] = video_stream.get('codec_name', 'N/A').upper()
            if audio_stream: info['audio'] = audio_stream.get('codec_name', 'N/A').upper()
            info["video"] = info["video"].replace("H264", "AVC").replace("H265", "HEVC")
            
            final_info_string = f"Input: {info['input']}<br>Video: {info['video']}<br>Audio: {info['audio']}"
            retry_needed = attempt > 0
            return final_info_string, retry_needed

        except ffmpeg.Error as e:
            last_error = e.stderr.decode('utf-8', 'ignore').strip().split('\n')[-1]
            if attempt < max_retries - 1:
                print(f"    FFprobe attempt {attempt + 1}/{max_retries} failed, retrying in {retry_delay}s...")
                time.sleep(retry_delay)
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                print(f"    Analysis attempt {attempt + 1}/{max_retries} failed, retrying in {retry_delay}s...")
                time.sleep(retry_delay)

    print(f"    FFprobe Error: {last_error}")
    return "Info: Probe Failed", False

def tail_docker_logs(log_entries, lock, original_stderr):
    """Connects via SSH and silently tails Docker logs, with a health check."""
    if not paramiko:
        print("Cannot tail logs because 'paramiko' library is not installed.")
        return
    
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        print(f"Connecting to {SSH_HOSTNAME} to tail logs...")
        client.connect(SSH_HOSTNAME, username=SSH_USERNAME, key_filename=SSH_PRIVATE_KEY_PATH, timeout=10)
    except paramiko.ssh_exception.PasswordRequiredException:
        try:
            print(f"\n--- SSH key '{SSH_PRIVATE_KEY_PATH}' is encrypted. ---", file=original_stderr)
            prompt_text = "Enter passphrase: "
            key_password = getpass.getpass(prompt_text, stream=original_stderr)
            client.connect(SSH_HOSTNAME, username=SSH_USERNAME, key_filename=SSH_PRIVATE_KEY_PATH, passphrase=key_password, timeout=10)
        except Exception as e:
            print(f"\n--- SSH connection failed: {e} ---", file=original_stderr)
            return
    except Exception as e:
        print(f"\n--- ERROR: Could not connect to tail Docker logs: {e} ---")
        return
    
    try:
        command = f"docker logs -f --tail 25 {DOCKER_CONTAINER_NAME}"
        print(f"Executing remote command: {command}")
        _stdin, stdout, _stderr = client.exec_command(command)
        
        # Health check to see if we receive any data
        stdout.channel.settimeout(5.0)
        try:
            first_line = stdout.readline()
            if not first_line:
                print("Warning: Docker log stream started but was empty. The container may have no recent output.")
                return # End the thread if there's no output
            
            # Process the first line
            with lock:
                log_entries.append((time.time(), first_line.strip()))
            
            # Set back to blocking for the main loop
            stdout.channel.settimeout(None)

            # Process the rest of the lines
            for line in iter(stdout.readline, ""):
                with lock:
                    log_entries.append((time.time(), line.strip()))
        
        except socket.timeout:
            print("\n--- WARNING: Connected to Docker, but no log data was received after 5 seconds. ---")
            print("--- The container might be silent or there could be a connection issue. ---")

    finally:
        client.close()

# --- Dispatcharr API ---
def dispatcharr_login(session, username, password):
    try:
        base_url = f"http://{SERVER_ADDRESS}"
        token_url = f"{base_url}/api/accounts/token/"
        response = session.post(token_url, json={"username": username, "password": password}, timeout=10)
        response.raise_for_status()
        access_token = response.json().get("access")
        if not access_token:
            print("API Error: Login returned no token.")
            return False
        session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json", "X-Requested-With": "XMLHttpRequest", "Referer": f"{base_url}/"
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
    except: return None

def get_active_profile(session):
    url = f"http://{SERVER_ADDRESS}/api/core/settings/"
    try:
        r = session.get(url, timeout=10)
        r.raise_for_status()
        for s in r.json():
            if s.get("key") == "default-stream-profile":
                return s.get("value"), s.get("id")
        return None, None
    except: return None, None

def set_active_profile(session, settings_id, profile_id):
    try:
        url = f"http://{SERVER_ADDRESS}/api/core/settings/{settings_id}/"
        r = session.patch(url, json={"value": str(profile_id)}, timeout=10)
        r.raise_for_status()
        print(f"  -> Set active profile to ID: {profile_id}")
        return True
    except: return False

# --- Core ---
def parse_m3u(url, session):
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching M3U from {url}: {e}")
        return []
    lines, all_channels = r.text.splitlines(), []
    for i, line in enumerate(lines):
        if line.startswith("#EXTINF:"):
            try:
                if (group_match := re.search(r'group-title="([^"]+)"', line)):
                    if group_match.group(1) == TARGET_GROUP:
                        name_match = re.search(r'tvg-name="([^"]+)"', line)
                        name = name_match.group(1) if name_match else line.split(',')[-1].strip()
                        all_channels.append({"name": name, "url": lines[i+1].strip()})
            except IndexError: continue
    start_index = next((i for i, ch in enumerate(all_channels) if START_CHANNEL_NAME in ch['name']), -1)
    if start_index == -1:
        print(f"Warning: Start channel '{START_CHANNEL_NAME}' not found.")
        return []
    return all_channels[start_index:start_index+CHANNEL_COUNT]

def measure_tune_time_with_vlc(player, channel_url, take_thumbnail=False):
    player_state = PlayerState()
    events = player.event_manager()
    events.event_attach(vlc.EventType.MediaPlayerPlaying, vlc_event_handler, player_state)
    events.event_attach(vlc.EventType.MediaPlayerEncounteredError, vlc_event_handler, player_state)
    media = player.get_instance().media_new(channel_url)
    media.add_option(f'http-user-agent={VLC_USER_AGENT}')
    player.set_media(media)
    start_time = time.perf_counter()
    player.play()
    playback_started = player_state.playing_event.wait(timeout=REQUEST_TIMEOUT)
    if playback_started:
        end_time = time.perf_counter()
        snapshot_wait_start = time.perf_counter()
        while player.get_time() < MIN_PLAYBACK_TIME_MS:
            time.sleep(0.05)
            if time.perf_counter() - snapshot_wait_start > 2.0:
                break
        thumbnail_path = None
        if take_thumbnail:
            safe_name = re.sub(r'[\\/*?:"<>|]', "", threading.current_thread().name)
            filename = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            thumbnail_path = os.path.join(THUMBNAIL_DIR, filename)
            player.video_take_snapshot(0, thumbnail_path, 0, 0)
            time.sleep(0.2)
        player.stop()
        return (end_time - start_time), thumbnail_path
    else:
        player.set_media(None)
        player.stop()
        status = "Stream Error" if player_state.error_event.is_set() else "Timed out"
        return None, status

def run_test_session(channels_to_test, log_entries, log_lock, view_mode=False, thumbnail_mode=True, probe_enabled=False, debug_mode=False, tuning_delay=0):
    if thumbnail_mode and not os.path.exists(THUMBNAIL_DIR):
        os.makedirs(THUMBNAIL_DIR)
    instance_args = VLC_ARGS[:]
    if not view_mode: instance_args.append('--vout=dummy')
    root = None
    if view_mode and tk:
        root = tk.Tk()
        root.geometry("854x480")
        video_frame = tk.Frame(root, bg="black")
        video_frame.pack(fill=tk.BOTH, expand=True)
        root.bind('<Escape>', lambda e: root.destroy())
    try:
        instance = vlc.Instance(' '.join(instance_args))
    except Exception as e:
        print(f"Error initializing VLC Instance: {e}")
        if root: root.destroy()
        return {}
    results = {}
    try:
        for channel in channels_to_test:
            base_name = re.sub(r'\s*ᴿᴬᵂ.*', '', channel['name'])
            threading.current_thread().name = base_name
            
            test_start_time = time.time()
            
            print(f"  -> Testing tune time: {channel['name']} ({channel['url']})")
            player = instance.media_player_new()
            if root:
                player.set_hwnd(video_frame.winfo_id()) if sys.platform == "win32" else player.set_xwindow(video_frame.winfo_id())
            try:
                tune_time, thumbnail = measure_tune_time_with_vlc(player, channel['url'], thumbnail_mode)
            finally:
                player.release()

            debug_messages = []
            stream_info, retry_needed = "N/A", False

            if probe_enabled:
                time.sleep(1)
                print(f"  -> Analyzing: {channel['name']}")
                stream_info, retry_needed = get_stream_info_ffprobe(channel['url'])
                if "Failed" in stream_info or "Error" in stream_info:
                    debug_messages.append(f"FFprobe: {stream_info}")
            
            test_end_time = time.time()

            info_string = stream_info
            if tune_time is None:
                debug_messages.append(f"VLC: {thumbnail}")
                info_string = f"{thumbnail}<br>{stream_info}"
            
            if debug_mode:
                correlated_errors = []
                with log_lock:
                    for ts, log_line in log_entries:
                        if test_start_time <= ts <= test_end_time:
                            if any(err in log_line.lower() for err in ['error', 'exception', 'failed', 'traceback']):
                                correlated_errors.append(log_line)
                if correlated_errors:
                    debug_messages.append(f"Docker: {'<br>'.join(correlated_errors)}")

            results[base_name] = {
                'time': tune_time, 
                'thumb': thumbnail if tune_time is not None else None, 
                'info': info_string, 
                'info_retry': retry_needed,
                'debug': "<br>".join(debug_messages)
            }
            if root: root.update()

            if tuning_delay > 0:
                print(f"  -> Waiting for {tuning_delay}s (tuning delay)...")
                time.sleep(tuning_delay)
    finally:
        instance.release()
        if root: root.destroy()
    return results

# --- Reporting ---
def display_results(df):
    if df.empty:
        print("No results to display.")
        return
    profile_cols = [c for c in df.columns if not c.endswith(('_thumb', '_info', '_info_retry', '_debug'))]
    headers = ["Channel"] + [c.split('\n')[0] for c in profile_cols]
    print("\n--- Channel Tuning Performance ---")
    print("{:<25}".format(headers[0]), end="")
    for h in headers[1:]: print("{:>25}".format(h), end="")
    print("\n" + "-" * (25 * len(headers)))
    for channel_name, row_data in df.iterrows():
        print("{:<25}".format(channel_name), end="")
        for col in profile_cols:
            time_val = row_data[col]
            content = f"{time_val:.4f}s" if pd.notna(time_val) else "Failed"
            print("{:>25}".format(content), end="")
        print()

def generate_html_report(df, probe_enabled=False, debug_enabled=False):
    if df.empty:
        print("No results to include in report.")
        return

    profile_cols = [c for c in df.columns if not c.endswith(('_thumb', '_info', '_info_retry', '_debug'))]
    profile_headers_data = [{"full_col_name": c, "name": c.split('\n')[0], "timestamp": c.split('\n')[1] if '\n' in c else ""} for c in profile_cols]
    profile_avgs = {p['name']: df[p['full_col_name']].mean() for p in profile_headers_data}
    
    colspan = 2 + (1 if probe_enabled else 0) + (1 if debug_enabled else 0)

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("""<!DOCTYPE html>
        <html><head><title>IPTV Tuning Report</title>
        <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; margin: 2em; background-color: #f8f9fa; }
        table { border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; background-color: #fff; }
        th, td { border: 1px solid #dee2e6; padding: 0.75rem; text-align: center; vertical-align: middle; }
        th { background-color: #f1f1f1; color: #333; font-weight: 600; }
        th.avg-header { background-color: #343a40; color: #fff; }
        h1, h2 { border-bottom: 2px solid #007bff; padding-bottom: 10px; margin-top: 25px; margin-bottom: 15px; color: #333; }
        .fast { background-color: #d4edda; } .medium { background-color: #fff3cd; } .slow { background-color: #f8d7da; }
        .fail { background-color: #e9ecef; color: #6c757d; }
        .info-cell, .debug-cell { font-size: 0.8em; text-align: left; vertical-align: top; }
        .debug-cell { color: #721c24; background-color: #f8d7da; white-space: pre-wrap; word-wrap: break-word; }
        .retry-note { font-size: 0.9em; color: #856404; font-style: italic; }
        img { max-width: 150px; height: auto; display: block; margin: 0 auto; }
        b { font-weight: 600; }
        </style></head><body>
        <h1>IPTV Channel Tuning Performance</h1>""")

        f.write("<h2>Profile Averages</h2>")
        f.write("<table style='width: 60%; margin-left: auto; margin-right: auto;'><thead><tr><th class='avg-header'>Profile</th><th class='avg-header'>Average Time (s)</th></tr></thead><tbody>")
        for name, avg in sorted(profile_avgs.items(), key=lambda item: item[1] if pd.notna(item[1]) else float('inf')):
            content, css_class = (f"{avg:.4f}", "fast" if avg < 1.5 else "medium" if avg < 3.0 else "slow") if pd.notna(avg) else ("N/A", "fail")
            f.write(f"<tr><td>{name}</td><td class='{css_class}'>{content}</td></tr>")
        f.write("</tbody></table>")

        f.write("<h2>Detailed Results</h2>")
        f.write("<table><thead><tr><th rowspan='2'>Channel</th>")
        for p in profile_headers_data: f.write(f"<th colspan='{colspan}'>{p['name']}<br>{p['timestamp']}</th>")
        f.write("</tr><tr>")
        for _ in profile_headers_data:
            if probe_enabled: f.write("<th>Stream Info</th>")
            f.write("<th>Time</th><th>Thumbnail</th>")
            if debug_enabled: f.write("<th>Debug</th>")
        f.write("</tr></thead><tbody>")

        for channel_name, row_data in df.iterrows():
            f.write(f"<tr><td><b>{channel_name}</b></td>")
            for p in profile_headers_data:
                col = p['full_col_name']
                
                if probe_enabled:
                    info_val = row_data.get(f"{col}_info", "N/A")
                    if row_data.get(f"{col}_info_retry", False):
                        info_val += "<br><small class='retry-note'>(retry was needed)</small>"
                    f.write(f"<td class='info-cell'>{info_val}</td>")
                
                time_val = row_data.get(col)
                content, css_class = (f"{time_val:.4f}s", "fast" if time_val < 1.5 else "medium" if time_val < 3.0 else "slow") if pd.notna(time_val) else ("Failed", "fail")
                f.write(f"<td class='{css_class}'>{content}</td>")
                
                thumb_path = row_data.get(f"{col}_thumb")
                if pd.notna(thumb_path) and os.path.exists(thumb_path):
                    b64 = encode_thumbnail_to_base64(thumb_path)
                    f.write(f"<td><img src='data:image/png;base64,{b64}' alt='Thumb'></td>")
                else: f.write("<td>—</td>")

                if debug_enabled:
                    debug_val = row_data.get(f"{col}_debug", "")
                    f.write(f"<td class='debug-cell'>{debug_val}</td>")
            f.write("</tr>")
            
        f.write("<tr><td><b>Average</b></td>")
        for p in profile_headers_data:
            avg = profile_avgs.get(p['name'])
            content, css_class = (f"<b>{avg:.4f}s</b>", "fast" if avg < 1.5 else "medium" if avg < 3.0 else "slow") if pd.notna(avg) else ("N/A", "fail")
            if probe_enabled: f.write("<td>—</td>")
            f.write(f"<td class='{css_class}'>{content}</td><td>—</td>")
            if debug_enabled: f.write("<td>—</td>")
        f.write("</tr></tbody></table></body></html>")
    print(f"HTML report generated: {REPORT_FILE}")

# --- Main ---
def main():
    print("IPTV Tuning Tester. Run with -h or --help for all options and usage examples.")
    
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    print_lock = threading.Lock()

    with open('log.txt', 'w', encoding='utf-8') as log_file:
        tee = Tee(original_stdout, log_file, lock=print_lock)
        
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        
        parser = argparse.ArgumentParser(
            description="A tool to test IPTV channel tuning times and optionally analyze streams.",
            epilog=textwrap.dedent('''\
                Examples:
                --------------------------------
                # Run a full test with default features (report, thumbnails) but no analysis
                python %(prog)s

                # Run a full test INCLUDING stream analysis and debug mode (log tailing + debug column)
                python %(prog)s --probe --debug

                # Run a fast test, disabling thumbnails and the report, using specific profiles
                python %(prog)s --no-thumbnail --no-report --profiles=1,4

                # Run a test to check for server strain with a 2-second delay between zaps
                python %(prog)s --tuningdelay=2
                '''),
            formatter_class=argparse.RawTextHelpFormatter
        )
        # --- Opt-in Flags (default is False) ---
        parser.add_argument("--reset", action="store_true", help="Reset previous results by deleting the CSV file.")
        parser.add_argument("--view", action="store_true", help="Show VLC video window during testing.")
        parser.add_argument("--probe", action="store_true", help="Enable FFprobe stream analysis (default: disabled).")
        parser.add_argument("--debug", action="store_true", help="Enable debug mode: tails Docker logs and shows a debug column in the report.")
        parser.add_argument("--profiles", type=str, help="Comma-separated list of numeric profile numbers to test (e.g., 1,3,5 or 'all').")
        parser.add_argument("--tuningdelay", type=int, default=0, help="Delay in seconds between each channel tuning test.")
        
        # --- Opt-out Flags (default is True) ---
        parser.add_argument("--no-report", dest="report", action="store_false", help="Disable the HTML report generation (default: enabled).")
        parser.add_argument("--no-thumbnail", dest="thumbnail", action="store_false", help="Disable capturing thumbnails (default: enabled).")
        
        args = parser.parse_args()
        
        sys.stdout = tee
        sys.stderr = tee

        docker_log_entries = []
        
        if args.debug:
            log_thread = threading.Thread(target=tail_docker_logs, args=(docker_log_entries, print_lock, original_stderr), daemon=True)
            log_thread.start()
            time.sleep(2)

        try:
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

            print("\nAvailable Streaming Profiles:")
            for i, p in enumerate(profiles): print(f"  {i+1}) {p['name']} (ID: {p['id']})")

            selected_profiles = []
            if args.profiles:
                print(f"\nUsing profiles from command line: {args.profiles}")
                selection = args.profiles
                if selection.lower() == 'all':
                    selected_profiles = profiles
                else:
                    try:
                        indices = [int(i.strip())-1 for i in selection.split(',')]
                        selected_profiles = [profiles[i] for i in indices if 0 <= i < len(profiles)]
                        if not selected_profiles:
                            print("No valid profiles found for the given numbers."); return
                    except ValueError:
                        print("Invalid format for --profiles argument. Use comma-separated numbers."); return
            else:
                with print_lock:
                    prompt = "\nEnter profile numbers to test (e.g., 1,3 or all): "
                    print(prompt, end='', file=original_stdout)
                    original_stdout.flush()
                    selection = sys.stdin.readline().strip()
                print(selection) 
                if selection.lower() == 'all':
                    selected_profiles = profiles
                else:
                    try:
                        indices = [int(i.strip())-1 for i in selection.split(',')]
                        selected_profiles = [profiles[i] for i in indices if 0 <= i < len(profiles)]
                        if not selected_profiles:
                            print("No valid profiles selected."); return
                    except (ValueError, EOFError):
                        print("Invalid selection."); return

            df = pd.DataFrame()

            print(f"\n--- Testing Baseline (Direct) Profile ---")
            baseline_channels = parse_m3u(BASELINE_M3U_URL, requests.Session())
            if baseline_channels:
                results = run_test_session(baseline_channels, docker_log_entries, print_lock, args.view, args.thumbnail, args.probe, args.debug, args.tuningdelay)
                ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                col = f"Baseline (direct)\n{ts}"
                df[col] = pd.Series({k: v['time'] for k,v in results.items()})
                df[f"{col}_thumb"] = pd.Series({k: v['thumb'] for k,v in results.items()})
                if args.probe:
                    df[f"{col}_info"] = pd.Series({k: v['info'] for k,v in results.items()})
                    df[f"{col}_info_retry"] = pd.Series({k: v['info_retry'] for k,v in results.items()})
                if args.debug:
                    df[f"{col}_debug"] = pd.Series({k: v['debug'] for k,v in results.items()})

            for profile in selected_profiles:
                print(f"\n--- Testing Profile: {profile['name']} ---")
                if not set_active_profile(api_session, settings_id, profile['id']): continue
                time.sleep(2)
                channels = parse_m3u(NORMAL_M3U_URL, api_session)
                if channels:
                    results = run_test_session(channels, docker_log_entries, print_lock, args.view, args.thumbnail, args.probe, args.debug, args.tuningdelay)
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                    col = f"{profile['name']}\n{ts}"
                    df[col] = pd.Series({k: v['time'] for k,v in results.items()})
                    df[f"{col}_thumb"] = pd.Series({k: v['thumb'] for k,v in results.items()})
                    if args.probe:
                        df[f"{col}_info"] = pd.Series({k: v['info'] for k,v in results.items()})
                        df[f"{col}_info_retry"] = pd.Series({k: v['info_retry'] for k,v in results.items()})
                    if args.debug:
                        df[f"{col}_debug"] = pd.Series({k: v['debug'] for k,v in results.items()})

            if active_profile_uuid:
                print(f"\n--- Resetting to original active profile ---")
                set_active_profile(api_session, settings_id, active_profile_uuid)
            
            if not df.empty:
                time_cols = sorted([c for c in df.columns if not c.endswith(('_thumb', '_info', '_info_retry', '_debug'))], key=lambda x: 0 if 'Baseline' in x else 1)
                all_cols = []
                for c in time_cols:
                    all_cols.extend([c, f"{c}_thumb"])
                    if args.probe:
                        all_cols.extend([f"{c}_info", f"{c}_info_retry"])
                    if args.debug:
                        all_cols.append(f"{c}_debug")
                df = df.reindex(columns=all_cols)
                df.to_csv(RESULTS_FILE)
                print(f"\nResults saved to: {RESULTS_FILE}")
            
            display_results(df)
            if args.report:
                generate_html_report(df, args.probe, args.debug)
            print("\nScript finished.")

        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr

if __name__ == "__main__":
    main()
