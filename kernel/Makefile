# Ainos OS 内核模块 Kbuild 文件
# 用于构建 AI 内核模块

obj-m += ai-scheduler.o
obj-m += ai-syscalls.o
obj-m += ai-vector-accel.o

# 如果有多个源文件组成一个模块
ai-scheduler-objs := ai-scheduler-main.o ai-scheduler-policy.o
ai-syscalls-objs := ai-syscalls-main.o
ai-vector-accel-objs := ai-vector-accel-main.o

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

# 测试加载
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

.PHONY: all clean install debug test-load test-unload