import matplotlib.pyplot as plt
import numpy as np

# Replace with real measured averages
loads = ["Idle", "Medium", "Heavy"]

# Example data (replace with your logs)
R_vals = [0.9, 0.2, 0.05]
I_vals = [5.1, 6.8, 8.2]
S_vals = [0.02, 0.08, 0.15]

x = np.arange(len(loads))

plt.figure(figsize=(8,5))
plt.plot(loads, R_vals, marker='o')
plt.title("Leak/Dyn Ratio vs Load")
plt.ylabel("R (Pleak / Pdyn)")
plt.grid(True)
plt.tight_layout()
plt.savefig("ratio_plot.png", dpi=300)
plt.show()

plt.figure(figsize=(8,5))
plt.plot(loads, I_vals, marker='s')
plt.title("Power Intensity vs Load")
plt.ylabel("I (mW per CPU%)")
plt.grid(True)
plt.tight_layout()
plt.savefig("intensity_plot.png", dpi=300)
plt.show()

plt.figure(figsize=(8,5))
plt.plot(loads, S_vals, marker='^')
plt.title("Leakage Sensitivity Index vs Load")
plt.ylabel("S (Exp - Linear)/Linear")
plt.grid(True)
plt.tight_layout()
plt.savefig("sensitivity_plot.png", dpi=300)
plt.show()
