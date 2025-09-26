## \# IPTV Tuning Tester with Multi-Thumbnail HTML Reporting

A Python-based tool for benchmarking IPTV channel tuning times across
different streaming profiles.\
It integrates **FFprobe** for accurate stream analysis and **VLC** for
playback performance testing.\
Optional features include real-time **Docker log tailing over SSH** for
error correlation, and a detailed HTML report with multi-thumbnails.

------------------------------------------------------------------------

## Features

-   Measures IPTV channel **tuning times** using VLC.
-   Generates an **HTML report** with thumbnails, averages, and
    per-channel details.
-   Supports **FFprobe stream analysis** for video/audio codec info.
-   Real-time **Docker log tailing via SSH** for debugging server-side
    errors.
-   Results saved in both **CSV** and **HTML** formats.
-   Console output mirrored to **log.txt**.

------------------------------------------------------------------------

## Requirements

-   Python 3.8+

-   Dependencies (install via pip):

    ``` bash
    pip install requests pandas python-vlc ffmpeg-python paramiko
    ```

-   System dependencies:

    -   [FFmpeg](https://ffmpeg.org/download.html) (must be installed
        separately)
    -   VLC media player
    -   (Optional) Docker & SSH access for log tailing

------------------------------------------------------------------------

## Usage

Run the script with various options:

``` bash
# Run a full test with default features (report + thumbnails)
python iptv_tester.py

# Run with FFprobe analysis + debug mode (includes Docker log tailing)
python iptv_tester.py --probe --debug

# Run without thumbnails and report (fast mode)
python iptv_tester.py --no-thumbnail --no-report --profiles=1,4

# Add delay between channel zaps to test load handling
python iptv_tester.py --tuningdelay=2

# Run a test suite across multiple delays (1–4 seconds)
python iptv_tester.py --tuningdelay=1-4
```

------------------------------------------------------------------------

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

------------------------------------------------------------------------

## Output

-   **log.txt** → Console output log
-   **tuning_results.csv** → Stores timing results
-   **tuning_report.html** → Interactive HTML report with thumbnails &
    stream info

------------------------------------------------------------------------

## Example HTML Report

The generated report includes: - Average tuning times per profile -
Thumbnails for visual verification - Stream info (video/audio codecs) -
Debug logs (if enabled)

------------------------------------------------------------------------

## Notes

-   Default configuration points to a local Dispatcharr server
    (`192.168.0.150:9191`). Update constants in the script to match your
    environment.
-   SSH-based Docker log tailing requires a valid private key and
    hostname in the configuration section of the script.

------------------------------------------------------------------------

## License

This project is provided **as-is** under an open license. Use at your
own risk.
