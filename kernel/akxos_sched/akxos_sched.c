/*
 * akxOS Scheduler Control Driver
 *
 * Provides user-space control over process priority (nice values) via a misc device.
 * User applications can modify process scheduling priority through ioctl calls.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/miscdevice.h>
#include <linux/sched.h>
#include <linux/sched/signal.h>
#include <linux/pid.h>

#include "akxos_sched.h"

#define DRIVER_NAME "akxos_sched"

/* Helper function: safely look up kernel task by PID with proper reference counting */
static struct task_struct *akxos_find_task_by_pid(pid_t pid)
{
    struct task_struct *task;

    rcu_read_lock();

    task = pid_task(find_vpid(pid), PIDTYPE_PID);

    if (task)
        get_task_struct(task);

    rcu_read_unlock();

    return task;
}

/*
 * Main device ioctl handler
 *
 * Processes commands from user space to modify process priority.
 * Commands: AKXOS_IOCTL_SET_NICE - set nice value [-20, 19]
 *           AKXOS_IOCTL_RESET_NICE - reset to default (0)
 */
static long akxos_sched_ioctl(struct file *file,
                              unsigned int cmd,
                              unsigned long arg)
{
    struct akxos_sched_req req;
    struct task_struct *task;

    if (copy_from_user(&req, (void __user *)arg, sizeof(req)))
        return -EFAULT;

    if (req.pid <= 0)
        return -EINVAL;

    task = akxos_find_task_by_pid(req.pid);

    if (!task)
        return -ESRCH;

    switch (cmd) {
    case AKXOS_IOCTL_SET_NICE:
        if (req.nice_value < -20 || req.nice_value > 19) {
            put_task_struct(task);
            return -EINVAL;
        }

        set_user_nice(task, req.nice_value);

        pr_info("akxOS sched: PID %d nice set to %d\n",
                req.pid, req.nice_value);
        break;

    case AKXOS_IOCTL_RESET_NICE:
        set_user_nice(task, 0);

        pr_info("akxOS sched: PID %d nice reset to 0\n",
                req.pid);
        break;

    default:
        put_task_struct(task);
        return -ENOTTY;
    }

    put_task_struct(task);
    return 0;
}

/* Device registration structures */
static const struct file_operations akxos_sched_fops = {
    .owner = THIS_MODULE,
    .unlocked_ioctl = akxos_sched_ioctl,
#ifdef CONFIG_COMPAT
    .compat_ioctl = akxos_sched_ioctl,
#endif
};

static struct miscdevice akxos_sched_dev = {
    .minor = MISC_DYNAMIC_MINOR,
    .name = DRIVER_NAME,
    .fops = &akxos_sched_fops,
    .mode = 0666,
};

/* Module lifecycle: init and exit handlers */
static int __init akxos_sched_init(void)
{
    int ret;

    ret = misc_register(&akxos_sched_dev);

    if (ret) {
        pr_err("akxOS sched: failed to register misc device\n");
        return ret;
    }

    pr_info("akxOS sched driver loaded: /dev/%s\n", DRIVER_NAME);
    return 0;
}

static void __exit akxos_sched_exit(void)
{
    misc_deregister(&akxos_sched_dev);
    pr_info("akxOS sched driver unloaded\n");
}

module_init(akxos_sched_init);
module_exit(akxos_sched_exit);

/* Module metadata */
MODULE_LICENSE("GPL");
MODULE_AUTHOR("akxOS");
MODULE_DESCRIPTION("akxOS minimal scheduler control driver");
MODULE_VERSION("0.1");
