# akxOS — Power-Aware Operating System Layer for Linux

**Professional User & Technical Guide**

**Target Platform:** Raspberry Pi (Linux-based systems)
**Audience:** Engineers, Researchers, System Integrators

## 1. Executive Overview

akxOS extends Linux with power-awareness at the process level. It treats power as a first-class operating system resource, alongside CPU and memory.

### akxOS provides:

- Per-process power estimation
- Hardware-aware telemetry integration
- Time-series logging
- User-space power budgeting
- Multi-layer enforcement mechanisms
- Experimental evaluation framework

Unlike traditional Linux monitoring tools, akxOS integrates:

- Microelectronics-based power modeling
- Live DVFS telemetry
- Closed-loop power control

This document describes the complete architecture, theory, CLI usage, and operational flow of the system.

## 2. System Architecture

### 2.1 Layered Design

akxOS follows strict separation of concerns:

1. **CLI Layer**
2. **Budget Engine** (Control Logic)
3. **Power State Aggregator**
4. **Telemetry + Process Parsing**
5. **Power Model**
6. **Linux Kernel Interfaces**

Each layer is independent, testable, and modular.

## 3. Theoretical Foundation

### 3.1 Power Model

akxOS uses classical CMOS power equations.

### Total Power = $$P_{total} = P_{dynamic} + P_{leakage}$$

### 3.1.1 Dynamic Power

$$P_{dyn} = \alpha \cdot C_{eff} \cdot V^2 \cdot f \cdot U$$

Where:

| Symbol | Meaning |
|--------|---------|
| $\alpha$ | Switching activity factor |
| $C_{eff}$ | Effective capacitance |
| $V$ | Supply voltage |
| $f$ | Clock frequency |
| $U$ | CPU utilization fraction |

Dynamic power scales quadratically with voltage and linearly with frequency.

### 3.1.2 Leakage Power

$$P_{leak} = K_{leak} \cdot M \cdot V$$

Where:

| Symbol | Meaning |
|--------|---------|
| $K_{leak}$ | Leakage scaling constant |
| $M$ | Memory footprint (KB) |
| $V$ | Supply voltage |

Leakage models static silicon power loss.

### 3.2 Why This Model

- Derived from CMOS VLSI fundamentals
- Suitable for OS-level abstraction
- Captures relative trends across workloads
- Calibratable using regression techniques

akxOS emphasizes trend-accurate modeling, not transistor-level accuracy.

## 4. System Components

### 4.1 Telemetry Module

Reads live hardware information from: `/sys/devices/system/cpu/`

**Provides:**
- CPU voltage
- CPU frequency
- CPU temperature

**CLI Command:**
```
akxos power
```

### 4.2 Process Parser

Reads: `/proc/[pid]/stat`

**Extracts:**
- PID
- Process name
- CPU usage %
- Memory usage (RSS)

**CLI Command:**
```
akxos ps
```

### 4.3 Power State Aggregator

**Combines:**
- Process data
- Telemetry data
- Power model

**Produces:**
- Per-process dynamic power
- Per-process leakage power
- Total power

### 4.4 Logger

Records time-series power data to CSV.

**Generates:** `logs/power_log_TIMESTAMP.csv`

**Fields include:**
- timestamp
- pid
- cpu_percent
- voltage
- frequency
- dynamic_power
- leakage_power
- total_power

**CLI Command:**
```
akxos log --interval [time-in-seconds] --duration [time-in-seconds]
```

## 5. CLI Usage Guide

### 5.1 Process Monitoring

Show current processes:
```
akxos ps
```

Live monitoring:
```
akxos ps --refresh --interval 1
```

### 5.2 Power Monitoring

Show per-process power:
```
akxos power
```

Live power tracking:
```
akxos power --refresh --interval 1
```

### 5.3 Logging Power Data

Record time-series data:
```
akxos log --interval 1 --duration 60
```

## 6. Power Budgeting

akxOS enables per-process power budgets enforced in user space.

### 6.1 Concept

A power budget specifies:

- Target power limit (mW)
- Enforcement mechanism
- Monitoring window

If a process exceeds its power limit over a windowed average, akxOS applies enforcement.

### 6.2 Enforcement Modes

#### sched_weight

Scheduler-based shaping using `nice()`.

- **Per-process**
- **Low invasiveness**
- **Minimal collateral impact**
- Suitable for interactive workloads

#### dvfs_cap

DVFS-based frequency cap via `/sys`.

- **System-wide**
- **Rapid power reduction**
- Affects all processes
- Suitable for thermal containment

#### cpu_quota

CPU-time enforcement via cgroups.

- **Strong containment**
- **Deterministic resource limits**
- Suitable for batch or sandbox workloads

### 6.3 Budget Commands

**Add a Budget:**
```
akxos budget add <pid> <limit_mw> --mode sched_weight
```

**List Budgets:**
```
akxos budget list
```

**Remove Budget:**
```
akxos budget remove <pid>
```

**Run Budget Engine:**
```
akxos budget run
```

Optional duration:
```
akxos budget run --duration 60
```

## 7. Budget Engine Operation

The engine runs a closed-loop controller:

1. Poll power states
2. Update sliding window average
3. Detect violation
4. Apply enforcement
5. Relax enforcement when safe

This prevents oscillation and ensures stability.

## 8. Multi-Budget Behavior

Multiple budgets may coexist:

- Each PID is tracked independently
- Enforcement decisions are per-policy
- System-wide mechanisms (DVFS) may affect other processes

This behavior is intentional and documented.

## 9. Calibration & Model Validation

akxOS supports empirical calibration:

- Idle measurement → leakage estimation
- CPU sweep → dynamic constant fitting
- DVFS sweep → voltage scaling validation
- Linear regression → constant refinement

**Accuracy metrics:**
- Mean Absolute Percentage Error (MAPE)
- Root Mean Square Error (RMSE)
