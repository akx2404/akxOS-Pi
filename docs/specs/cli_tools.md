## v0.1.3 — CLI Tools Specification

### Commands
| Command | Description |
|----------|--------------|
| `akxos ps` | Displays current process stats |
| `akxos power` | Displays power estimates per process |
| `akxos log --interval <s> --duration <s>` | Continuously logs power data to CSV |

### Output
All data logged to `/logs/power_log_<timestamp>.csv`.

### Dependencies
- process_info.py
- power_model.py

### Next phase
Will integrate with `/dev/akxos` kernel driver for real-time IOCTL communication.
