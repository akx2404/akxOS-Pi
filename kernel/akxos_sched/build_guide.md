# build and reload

cd ~/akxOS-Pi/kernel/akxos_sched

make clean
make

sudo rmmod akxos_sched
sudo insmod akxos_sched.ko

dmesg | tail -20
cat /proc/akxos_sched

# Test

yes > /dev/null &
pid=$!
echo $pid

### Set budget:

echo "set $pid 80" | sudo tee /proc/akxos_sched

### Watch:

watch -n 1 "cat /proc/akxos_sched; ps -o pid,stat,comm -p $pid"

### Clean

echo "clear $pid" | sudo tee /proc/akxos_sched
kill $pid
