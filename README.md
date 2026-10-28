# m4top

A Python terminal monitor for Apple Silicon Macs, with an interface inspired by htop.

Displays individual logical CPU core usage, aggregate GPU metrics, memory usage, and running processes. Data collection uses `psutil` and the JSON output provided by `macmon`.

## Features

- Usage bars for each logical CPU core.
- GPU active residency and frequency-adjusted activity.
- History of recent GPU samples.
- GPU frequency, power consumption, and temperature when available.
- RAM and swap usage.
- Process list showing PID, CPU usage, and resident memory.
- Process sorting by CPU or RAM.
- CPU core scrolling for smaller terminals.
- CPU, memory, and process monitoring even without macmon.

## Requirements

- macOS running on an Apple Silicon Mac.
- Python 3.10 or later.
- [Homebrew](https://brew.sh/) to install macmon.
- A terminal window with at least 76 columns and 26 rows.

The only required Python package is `psutil`. Other modules, including `curses`, are part of the Python standard library on macOS.

GPU metrics require `macmon`, which is installed separately.

## Installation

Download `m4top.py` and open a terminal in the directory containing the file.

### 1. Install macmon

```bash
brew install macmon
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install the Python dependency

```bash
python -m pip install psutil
```

## Usage

Run the monitor with the virtual environment activated.

```bash
python m4top.py
```

The default sampling interval is one second.

### Custom sampling interval

Update every half second.

```bash
python m4top.py --interval 0.5
```

The minimum supported interval is 0.2 seconds.

### Run without GPU monitoring

```bash
python m4top.py --no-gpu
```

### Specify the macmon executable

If macmon is not available in your `PATH`, specify its location.

```bash
python m4top.py --macmon /opt/homebrew/bin/macmon
```

### Display help

```bash
python m4top.py --help
```

### Run in a new terminal session

From the project directory, activate the virtual environment again before running.

```bash
source .venv/bin/activate
python m4top.py
```

## Keyboard Shortcuts

| Key | Action |
| --- | --- |
| `q` or `Esc` | Quit |
| `c` | Sort processes by CPU usage |
| `m` | Sort processes by RAM usage |
| `↑` | Scroll the CPU core list up |
| `↓` | Scroll the CPU core list down |

## Understanding the Metrics

The current interface uses Portuguese labels.

| Display label | Meaning |
| --- | --- |
| `CPU 00`, `CPU 01`, etc. | Usage of each logical CPU core, reported by the operating system |
| `Ativa` | Percentage of the sampling interval during which the GPU was active |
| `Freq.adj` | GPU activity weighted by its operating frequency |
| `Clock` | GPU frequency reported by macmon |
| `Histórico` | History of recent GPU samples |
| `N/D` | Metric unavailable or data collection no longer updating |

`Freq.adj` is not a measurement of FLOPS or utilization across all GPU execution units.

In the process list, CPU usage can exceed 100% when a process uses multiple cores. Process memory is reported as resident memory in MiB.

## Limitations

- GPU metrics are aggregate. Individual physical GPU core usage is not available through the metrics used by this program.
- Frequency, power, and temperature availability depend on the macOS version, hardware, and macmon version.
- Missing fields appear as `N/D`.
- On unsupported configurations, a power reading of zero may indicate an unavailable counter.
- Some protected processes may be omitted when their information cannot be accessed.
- The program does not require `sudo`.

## Troubleshooting

### Missing psutil dependency

Activate the virtual environment and install the package.

```bash
source .venv/bin/activate
python -m pip install psutil
```

### GPU metrics unavailable

Check whether macmon can produce a sample.

```bash
macmon pipe -s 1
```

Check the installed version.

```bash
macmon --version
```

If necessary, update macmon.

```bash
brew update
brew upgrade macmon
```

If macmon works directly but is not detected by m4top, locate the executable.

```bash
which macmon
```

Then pass the returned path using `--macmon`.

### Terminal too small

Enlarge the terminal window or reduce the font size. The minimum supported size is 76 columns and 26 rows.

## Dependencies and References

- [psutil](https://github.com/giampaolo/psutil)
- [macmon](https://github.com/vladkens/macmon)
- [Python curses documentation](https://docs.python.org/3/library/curses.html)

## Validation Status

Parsing of the supported JSON formats, basic screen rendering, and collector shutdown were checked using controlled data. Integration with a physical Apple Silicon GPU still requires validation on a Mac.
