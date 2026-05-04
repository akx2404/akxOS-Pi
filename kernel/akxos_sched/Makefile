# Build akxos_sched as a loadable kernel module
#
# Depends on CONFIG_CPU_FREQ being enabled in the kernel
# (standard on Raspberry Pi OS kernels).

obj-m += akxos_sched.o

KDIR ?= /lib/modules/$(shell uname -r)/build
PWD  := $(shell pwd)

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean

# Convenience: reload module without rebooting
reload:
	-sudo rmmod akxos_sched
	sudo insmod akxos_sched.ko
	dmesg | tail -5
