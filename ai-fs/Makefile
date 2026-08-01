# Ainos OS - AI File System Kbuild Makefile

obj-m += ai-fs.o

ai-fs-objs := fuse-layer/ainos_fuse.o

ccflags-y := -I$(PWD)/include -I$(PWD)/fuse-layer -O2 -Wall

all:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules

clean:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean

install:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules_install
	depmod -a

test-load:
	-sudo rmmod ai-fs 2>/dev/null || true
	-sudo insmod ai-fs.ko
	lsmod | grep ai-fs
	mount -t ai-fs none /mnt/ai-fs

test-unload:
	-umount /mnt/ai-fs 2>/dev/null || true
	-sudo rmmod ai-fs 2>/dev/null || true

.PHONY: all clean install test-load test-unload