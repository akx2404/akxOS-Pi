## v0.1.2 — Power Model Specification
- Inputs: CPU% and Mem(KB)
- Outputs: Pdyn, Pleak, Ptotal (mW)
- Formulas:
  - Pdyn = Kdyn × CPU% × V² × f
  - Pleak = Kleak × Mem × V
- Log Format:
  Timestamp, PID, Name, CPU%, Mem(KB), Pdyn(mW), Pleak(mW), Ptotal(mW)
