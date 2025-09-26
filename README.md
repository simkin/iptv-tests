# IPTV Tuning Tester for Dispatcharr

*A benchmarking tool with multi-thumbnail HTML reporting*

This project provides a Python-based test suite for measuring and
analyzing **channel tuning times** in
[**Dispatcharr**]([https://github.com/Dispatcharr/Dispatcharr).\
It integrates **VLC** for playback timing, **FFprobe** for stream
analysis, and can optionally pull **Docker logs over SSH** for
debugging.\
A detailed **HTML report with multi-thumbnails** is generated to
visualize performance.

## Features

-   Benchmark IPTV channel **tuning times** across Dispatcharr profiles
-   Generate an **HTML report** with thumbnails, averages, and
    per-channel details
-   Collect stream details via **FFprobe** (video/audio codec info)
-   Optional **Docker log tailing via SSH** for server-side debugging
-   Save results in **CSV + HTML** formats
-   Console output mirrored to **log.txt**

## Requirements

-   Python 3.8+

-   Python dependencies:

    ``` bash
    pip install requests pandas python-vlc ffmpeg-python paramiko
    ```

-   System dependencies:

    -   [FFmpeg](https://ffmpeg.org/download.html) (installed
        separately)
    -   VLC media player
    -   (Optional) Docker & SSH access for log tailing

## Usage

Run the script with different options depending on your test scenario:

``` bash
# Full test with default settings (report + thumbnails)
python iptv_tester.py

# Run with FFprobe analysis + debug mode (includes Docker log tailing)
python iptv_tester.py --probe --debug

# Run without thumbnails and report (fast mode)
python iptv_tester.py --no-thumbnail --no-report --profiles=1,4

# Add a 2s delay between channel zaps
python iptv_tester.py --tuningdelay=2

# Sweep across multiple delays (1–4 seconds)
python iptv_tester.py --tuningdelay=1-4
```

## Command-Line Arguments

  -----------------------------------------------------------------------
  Argument                                 Description
  ---------------------------------------- ------------------------------
  `--reset`                                Reset previous results
                                           (deletes CSV).

  `--view`                                 Show VLC video window during
                                           testing.

  `--probe`                                Enable FFprobe stream
                                           analysis.

  `--debug`                                Enable debug mode (Docker log
                                           tailing + debug column).

  `--profiles`                             Comma-separated profile list
                                           (e.g., `1,3,5` or `all`).

  `--tuningdelay`                          Delay in seconds between tunes
                                           (single number or range
                                           `1-4`).

  `--no-report`                            Disable HTML report
                                           generation.

  `--no-thumbnail`                         Disable thumbnail snapshots.
  -----------------------------------------------------------------------

## Output

-   **log.txt** → Console output log
-   **tuning_results.csv** → Stores timing results
-   **tuning_report.html** → Interactive HTML report with thumbnails &
    stream info

## Example Report

The HTML report includes: - Average tuning times per profile -
Thumbnails for visual verification - Stream info (video/audio codecs) -
Debug logs (if enabled)

## Notes

-   Default configuration points to a local Dispatcharr server
    (`192.168.0.150:9191`).\
    Update constants in the script to match your environment.\
-   SSH-based Docker log tailing requires a valid private key and
    hostname configured in the script.

## License

This project is provided **as-is** under an open license. Use at your
own risk.
