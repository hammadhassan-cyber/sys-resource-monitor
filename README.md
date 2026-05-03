# System Resource Monitor

A GUI-based system monitoring tool for real-time tracking of CPU, RAM, and Disk usage on your computer. This application displays live performance metrics, triggers alerts when usage exceeds user-defined thresholds, and logs all readings into a CSV file for later analysis.

## Features
- Real-time CPU, RAM, and Disk usage monitoring
- User-configurable alert thresholds (CPU, RAM, Disk)
- Desktop notifications and pop-up warnings when thresholds are exceeded
- CSV logging of all measurements with timestamp and status
- Live performance graph using matplotlib
- Clean Tkinter GUI with status indicator and scrollable log viewer

## Requirements
- Python 3.x
- `psutil` – for system metrics
- `tkinter` – GUI toolkit (usually included with Python)
- `plyer` – for desktop notifications
- `matplotlib` – for graph visualization

## Installation
1. Install required packages:
   ```bash
   pip install psutil plyer matplotlib
   ```
2. Run the script:
   ```bash
   python system_monitor.py
   ```

## Usage
- Click "Start Monitoring" to begin real-time tracking.
- Adjust CPU, RAM, and Disk thresholds in the "Alert Thresholds" section and click "Update Thresholds".
- View live graphs in the "Performance Graph" panel.
- Check logs via "View Logs" or the "Recent Activity" panel.
- Clear all logs with the "Clear Logs" button.
