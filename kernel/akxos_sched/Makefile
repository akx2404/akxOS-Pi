# Build akxos_sched as a loadable kernel module
obj-m += akxos_sched.o

# Kernel build directory - defaults to current kernel's build tree
KDIR ?= /lib/modules/$(shell uname -r)/build
# Current working directory (module source location)
PWD  := $(shell pwd)

# Build target: compile the kernel module
all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

# Clean target: remove build artifacts
clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean
