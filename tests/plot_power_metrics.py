import matplotlib.pyplot as plt
import numpy as np
import os

output_dir = 'tests/plots'
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

loads = ["Idle", "Medium", "Heavy"]

R_vals = [0.0010, 0.0005, 0.0003]
I_vals = [5.85, 5.85, 5.85]
S_vals = [0.16, 0.16, 0.16]

x = np.arange(len(loads))

plt.figure(figsize=(8,5))
plt.plot(loads, R_vals, marker='o')
plt.title("Leak/Dyn Ratio vs Load")
plt.ylabel("R (Pleak / Pdyn)")
plt.grid(True)
plt.tight_layout()
plt.savefig(os.path.join(output_dir,"ratio_plot.png"), dpi=300)
plt.show()

plt.figure(figsize=(8,5))
plt.plot(loads, I_vals, marker='s')
plt.title("Power Intensity vs Load")
plt.ylabel("I (mW per CPU%)")
plt.grid(True)
plt.tight_layout()
plt.savefig(os.path.join(output_dir,"intensity_plot.png"), dpi=300)
plt.show()

plt.figure(figsize=(8,5))
plt.plot(loads, S_vals, marker='^')
plt.title("Leakage Sensitivity Index vs Load")
plt.ylabel("S (Exp - Linear)/Linear")
plt.grid(True)
plt.tight_layout()
plt.savefig(os.path.join(output_dir,"sensitivity_plot.png"), dpi=300)
plt.show()
