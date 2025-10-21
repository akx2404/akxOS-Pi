# akxOS-Pi Release Targets (v0.1 → v5.0)

A detailed roadmap for the complete akxOS-Pi development cycle — from foundational user-space tools to dual-driver power-aware scheduling and system-wide optimization.
Each major release (vX.0) is divided into **three sub-releases (vX.1, vX.2, vX.3)** representing implementation, integration, and validation milestones.

---

## v0.1 – Foundations
**Goal:** Build the user-space base for per-process power visibility and modeling.

### Overview
This release focuses on establishing the user-space layer of akxOS-Pi.
It provides commands to parse process data from `/proc`, compute **dynamic and leakage power**, and log power activity into CSV files.

### Sub-Releases
| Version | Focus | Targets |
|----------|--------|----------|
| **v0.1.1** | `/proc` parser | Implement process listing (`akxos ps`), extract CPU% and memory from `/proc/[pid]/stat`. |
| **v0.1.2** | Power model scripts | Add dynamic (`Pdyn = α·C·V²·f`) and leakage (`Pleak = Ileak·Vdd`) models, integrate with parser. |
| **v0.1.3** | CLI + logger integration | Build unified CLI (`akxos power`, `akxos log`), enable CSV logging. |

### Deliverables
User-space CLI: `akxos ps`, `akxos power`, `akxos log`.
Base CSV logging and per-process power model.

---

## v0.2 – Kernel Control
**Goal:** Introduce kernel driver `akxos_pm.ko` for process-level power enforcement.

### Overview
This phase connects user-space models to kernel control.
The driver exposes `/dev/akxos` for user-space commands to set **budgets**, **DVFS states**, and **power gating**.

### Sub-Releases
| Version | Focus | Targets |
|----------|--------|----------|
| **v0.2.1** | Driver skeleton | Create basic `akxos_pm.ko` with load/unload routines and `/dev/akxos` interface. |
| **v0.2.2** | IOCTL interface | Implement IOCTLs (`SET_BUDGET`, `SET_DVFS`, `GATE/UNGATE`) and link to CLI. |
| **v0.2.3** | Enforcement testing | Run enforcement tests, validate response, stabilize kernel–user communication. |

### Deliverables
Kernel driver v1 (`akxos_pm.ko`) with CLI-based budget and DVFS control.

---

## v1.0 – Model Refinement & Evaluation
**Goal:** Calibrate and validate power models using system data.

### Overview
This release focuses on validating akxOS-Pi’s power models with measured system performance and refining the coefficients for accurate estimation.

### Sub-Releases
| Version | Focus | Targets |
|----------|--------|----------|
| **v1.1** | Calibration tools | Add tools to correlate CPU frequency/load with estimated power. |
| **v1.2** | Validation framework | Compare modeled vs. system-measured power, compute accuracy metrics. |
| **v1.3** | Adaptive modeling | Introduce correction factors and model self-adjustment logic. |

### Deliverables
Validated power models and automated evaluation scripts.

---

## v2.0 – Developer API Integration
**Goal:** Allow applications to provide power-intent hints to the OS.

### Overview
This release introduces an API layer (`libakxosapi.so`) so developers can guide the OS with hints like `LOW_POWER`, `BACKGROUND`, or `HIGH_PERF`.

### Sub-Releases
| Version | Focus | Targets |
|----------|--------|----------|
| **v2.1** | Library foundation | Implement base API calls and structures. |
| **v2.2** | Hint propagation | Ensure API communicates with kernel drivers correctly. |
| **v2.3** | Sample app integration | Create demo apps using API, measure power savings. |

### Deliverables
Developer library (`libakxosapi.so`) + sample demo applications.

---

## v3.0 – Advanced Scheduling & Dual Drivers
**Goal:** Implement cooperative power-aware scheduling using two kernel drivers.

### Overview
This version adds a scheduler-aware driver `akxos_sched.ko` working alongside `akxos_pm.ko`.
Together, they dynamically adjust CPU allocation and frequency based on process budgets and power hints.

### Sub-Releases
| Version | Focus | Targets |
|----------|--------|----------|
| **v3.1** | Scheduler driver base | Create `akxos_sched.ko` and connect to Linux scheduler hooks. |
| **v3.2** | Dual-driver link | Enable data exchange between PM and Scheduler drivers. |
| **v3.3** | Policy testing | Evaluate scheduling fairness and power efficiency. |

### Deliverables
Dual-driver system: `akxos_pm.ko` + `akxos_sched.ko`.
Dynamic power-aware process scheduling.

---

## v4.0 – System-Level Optimization
**Goal:** Develop a policy engine to balance performance and power dynamically.

### Overview
This phase adds adaptive logic for power caps and workload-based redistribution of available power budgets.
It introduces system-wide control policies operating above both kernel drivers.

### Sub-Releases
| Version | Focus | Targets |
|----------|--------|----------|
| **v4.1** | Policy engine | Build high-level controller for system-wide power capping. |
| **v4.2** | Adaptive DVFS | Implement per-core adaptive frequency scaling based on utilization. |
| **v4.3** | System profiling | Evaluate response time and efficiency across workloads. |

### Deliverables
Adaptive policy engine integrated into `akxos_pm.ko`.
CLI tools for viewing and tuning global power budgets.

---

## v5.0 – Final Integration & Research Evaluation
**Goal:** Deliver full akxOS-Pi integration and final evaluation results.

### Overview
This release merges all subsystems — user-space tools, kernel drivers, scheduler, and policy engine — into a unified power-aware OS prototype for Raspberry Pi.
It focuses on documentation, testing, and research-grade evaluation.

### Sub-Releases
| Version | Focus | Targets |
|----------|--------|----------|
| **v5.1** | Integration | Merge all modules and verify system stability. |
| **v5.2** | Evaluation | Benchmark akxOS-Pi against Linux governors (ondemand, powersave). |
| **v5.3** | Documentation | Compile technical report, diagrams, and demo results. |

### Deliverables
Fully integrated akxOS-Pi stack, academic report, and final demonstration results.

---

## Project Flow Summary

| **Phase** | **Focus** | **Output** |
|------------|------------|------------|
| v0.1 | User-space data collection and power modeling | CLI + power models |
| v0.2 | Kernel-space enforcement | akxos_pm.ko |
| v1.0 | Model validation and accuracy | Calibrated models |
| v2.0 | Developer API | libakxosapi.so |
| v3.0 | Power-aware scheduling | akxos_sched.ko |
| v4.0 | Policy optimization | Adaptive DVFS + system control |
| v5.0 | Final integration | Full system + research results |

---
