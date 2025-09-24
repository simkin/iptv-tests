# IPTV Channel Tuning Performance Tester

A Python script designed to accurately measure and benchmark the channel tuning performance of IPTV streams from M3U playlists. It uses the `libvlc` engine to get precise "time-to-video" metrics, comparing a baseline (direct stream) against one or more proxied test runs.

The script generates a clean, color-coded HTML report with optional thumbnails, providing visual proof of successful channel tuning and making it easy to analyze and share the results.

![Example HTML Report](https://i.imgur.com/gYdI5wW.png)

## Features

* **Accurate Measurement:** Uses VLC's internal events to measure the exact time until video playback begins, providing realistic tuning times.
* **Comparative Analysis:** Automatically runs a baseline test against a direct stream URL and compares it with subsequent tests against proxied URLs.
* **Persistent Results:** Saves test sessions to a `.csv` file, allowing you to append new test runs and track performance over time.
* **Interactive Viewing Mode:** An optional `--view` flag lets you watch the channels being tested in a real-time video window.
* **Visual Validation:** A `--thumbnail` flag captures a snapshot of each successfully tuned channel.
* **Detailed HTML Reports:** Generates a single, self-contained HTML file with color-coded results and embedded thumbnails for easy analysis.
* **Smart Error Handling:** Tolerates transient stream errors and only marks a tune as failed if playback doesn't start within the configured timeout.
* **Client Emulation:** Uses a TiviMate User-Agent to ensure compatibility with IPTV servers that restrict access to unknown clients.

## Requirements

* **Python 3.6+**
* **VLC Media Player:** The script requires a local installation of VLC. The `python-vlc` library needs to find the VLC installation to function.
* **Python Libraries:** Install the necessary libraries using pip:

pip install pandas requests python-vlc
## How to Use

1.  **Configure the Script:** Open `iptv_tuning_tester.py` and edit the variables in the **Configuration** section to match your setup (server address, channel group, etc.).

2.  **Initial Run (Baseline + First Test):** Run the script for the first time. It will automatically create the results file by running a baseline test and your first normal test.
python iptv_tuning_tester.py
3.  **Append a New Test:** To run another test and add its results as a new column, simply run the script again.
python iptv_tuning_tester.py
4.  **Reset and Start Over:** To delete all previous results and start a fresh test (including a new baseline), use the `--reset` flag.
python iptv_tuning_tester.py --reset
### Command-Line Arguments

* `--view`: Opens a video window to show each channel as it's being tested.
* `--thumbnail`: Captures a snapshot of each successful tune and saves it to the `thumbnails/` folder.
* `--report`: Generates (or updates) the `tuning_report.html` file after the test run is complete.
* `--reset`: Deletes `tuning_results.csv` before running to start a fresh series of tests.

**Example of a full test run with all features enabled:**
python iptv_tuning_tester.py --reset --view --thumbnail --report
