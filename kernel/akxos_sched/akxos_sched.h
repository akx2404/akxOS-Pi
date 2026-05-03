#ifndef AKXOS_SCHED_H
#define AKXOS_SCHED_H

#include <linux/ioctl.h>

#define AKXOS_IOCTL_MAGIC 'A'

struct akxos_sched_req {
    int pid;
    int nice_value;
};

#define AKXOS_IOCTL_SET_NICE   _IOW(AKXOS_IOCTL_MAGIC, 0x01, struct akxos_sched_req)
#define AKXOS_IOCTL_RESET_NICE _IOW(AKXOS_IOCTL_MAGIC, 0x02, struct akxos_sched_req)

#endif
