#!/usr/bin/env python3
"""
Test utility for akxOS scheduler control driver

Sends ioctl commands to /dev/akxos_sched to modify process priority (nice values).
"""

import fcntl
import os
import struct
import sys


# Device path for the akxOS scheduler misc device
DEV_PATH = "/dev/akxos_sched"

# Kernel ioctl command encoding: bit field sizes
IOC_NRBITS = 8
IOC_TYPEBITS = 8
IOC_SIZEBITS = 14

# Ioctl direction: IOC_WRITE = data written from user space to kernel
IOC_WRITE = 1

# Bit shift offsets for ioctl command encoding
IOC_NRSHIFT = 0
IOC_TYPESHIFT = IOC_NRSHIFT + IOC_NRBITS
IOC_SIZESHIFT = IOC_TYPESHIFT + IOC_TYPEBITS
IOC_DIRSHIFT = IOC_SIZESHIFT + IOC_SIZEBITS


# Helper to build ioctl "write" command code (similar to kernel's _IOW macro)
def _iow(type_char, nr, size):
    return (
        (IOC_WRITE << IOC_DIRSHIFT)
        | (ord(type_char) << IOC_TYPESHIFT)
        | (nr << IOC_NRSHIFT)
        | (size << IOC_SIZESHIFT)
    )


# Ioctl command codes
AKXOS_IOCTL_SET_NICE = _iow("A", 0x01, 8)
AKXOS_IOCTL_RESET_NICE = _iow("A", 0x02, 8)


def send_ioctl(pid, nice_value, reset=False):
    """
    Send ioctl command to the device driver

    Args:
        pid: Target process ID
        nice_value: Priority value (ignored if reset=True)
        reset: If True, use RESET_NICE command, else use SET_NICE
    """
    # Select appropriate ioctl command
    cmd = AKXOS_IOCTL_RESET_NICE if reset else AKXOS_IOCTL_SET_NICE
    # Pack pid and nice_value as two 32-bit integers in binary format
    req = struct.pack("ii", pid, nice_value)

    # Open device and send ioctl command with packed data
    with open(DEV_PATH, "rb", buffering=0) as dev:
        fcntl.ioctl(dev, cmd, req)


def main():
    """Parse command line arguments and execute requested action"""
    if len(sys.argv) < 3:
        print("Usage:")
        print("  sudo python3 test_sched_ioctl.py set <pid> <nice>")
        print("  sudo python3 test_sched_ioctl.py reset <pid>")
        sys.exit(1)

    action = sys.argv[1]
    pid = int(sys.argv[2])

    if action == "set":
        if len(sys.argv) != 4:
            print("Usage: sudo python3 test_sched_ioctl.py set <pid> <nice>")
            sys.exit(1)

        nice_value = int(sys.argv[3])
        send_ioctl(pid, nice_value, reset=False)
        print(f"[test] Set PID {pid} nice to {nice_value}")

    elif action == "reset":
        send_ioctl(pid, 0, reset=True)
        print(f"[test] Reset PID {pid} nice to 0")

    else:
        print("Unknown action:", action)
        sys.exit(1)


# Script entry point
if __name__ == "__main__":
    main()
