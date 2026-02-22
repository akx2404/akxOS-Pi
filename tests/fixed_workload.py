import math

def is_prime(n):
    if n < 2:
        return False
    for i in range(2, int(math.sqrt(n)) + 1):
        if n % i == 0:
            return False
    return True

count = 0
target = 200000  # Adjust for ~20 sec runtime on Pi

for num in range(2, target):
    is_prime(num)

print("Workload complete")
