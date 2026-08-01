# Ainos OS 内核模块 Kbuild 文件
# 用于构建 AI 内核模块

obj-m += ai-scheduler.o
obj-m += ai-syscalls.o
obj-m += ai-vector-accel.o
obj-m += proc-ai.o
obj-m += self-heal.o
obj-m += ai-kill.o
obj-m += ai-tmpfs.o
obj-m += ai-readahead.o
obj-m += hotpatch.o

# 多源文件模块
ai-scheduler-objs := ai-scheduler-main.o ai-scheduler-policy.o
ai-syscalls-objs := ai-syscalls-main.o
ai-vector-accel-objs := ai-vector-accel-main.o
proc-ai-objs := ai-proc/proc_ai.o
self-heal-objs := ai-self-heal/self_heal.o
ai-kill-objs := ai-kill/ai_kill.o
ai-tmpfs-objs := ai-tmpfs/ai_tmpfs.o
ai-readahead-objs := ai-readahead/ai_readahead.o
hotpatch-objs := hotpatch/hotpatch.o

# 编译标志
ccflags-y := -I$(PWD)/include -O2 -Wall -Werror

all:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules

clean:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean

install:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules_install
	depmod -a

# 调试目标
debug:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules EXTRA_CFLAGS="-DDEBUG -g"

# AI 模块加载
load-ai:
	-sudo insmod ai-proc/proc_ai.ko 2>/dev/null || true
	-sudo insmod ai-self-heal/self_heal.ko 2>/dev/null || true
	-sudo insmod ai-kill/ai_kill.ko 2>/dev/null || true
	-sudo insmod ai-tmpfs/ai_tmpfs.ko 2>/dev/null || true
	-sudo insmod ai-readahead/ai_readahead.ko 2>/dev/null || true
	-sudo insmod hotpatch/hotpatch.ko 2>/dev/null || true
	lsmod | grep -E "proc_ai|self_heal|ai_kill|ai_tmpfs|ai_readahead|hotpatch"

unload-ai:
	-sudo rmmod hotpatch 2>/dev/null || true
	-sudo rmmod ai_readahead 2>/dev/null || true
	-sudo rmmod ai_tmpfs 2>/dev/null || true
	-sudo rmmod ai_kill 2>/dev/null || true
	-sudo rmmod self_heal 2>/dev/null || true
	-sudo rmmod proc_ai 2>/dev/null || true

test-load:
	-sudo rmmod ai-scheduler 2>/dev/null || true
	-sudo rmmod ai-syscalls 2>/dev/null || true
	-sudo insmod ai-scheduler.ko
	-sudo insmod ai-syscalls.ko
	lsmod | grep ai_

test-unload:
	-sudo rmmod ai-syscalls 2>/dev/null || true
	-sudo rmmod ai-scheduler 2>/dev/null || true
	-sudo rmmod ai-vector-accel 2>/dev/null || true

.PHONY: all clean install debug load-ai unload-ai test-load test-unload