# Ainos Hotpatch 模块 Makefile
# 深度实现 v2.0.0

obj-m += hotpatch.o

hotpatch-objs := hotpatch.o

ccflags-y := -I$(PWD) -O2 -Wall -Werror

all:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules

clean:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean

install:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules_install
	depmod -a

load:
	-sudo insmod hotpatch.ko
	lsmod | grep hotpatch

unload:
	-sudo rmmod hotpatch 2>/dev/null || true

status:
	@echo "=== Hotpatch Status ==="
	@cat /proc/ai-hotpatch/status 2>/dev/null || echo "Module not loaded"

patches:
	@echo "=== Patches ==="
	@cat /proc/ai-hotpatch/patches 2>/dev/null || echo "Module not loaded"

hooks:
	@echo "=== Hooks ==="
	@cat /proc/ai-hotpatch/hooks 2>/dev/null || echo "Module not loaded"

config:
	@echo "=== Config ==="
	@cat /proc/ai-hotpatch/config 2>/dev/null || echo "Module not loaded"

test:
	@echo "=== Hotpatch Module Test ==="
	@ls -la /proc/ai-hotpatch/ 2>/dev/null || echo "  [FAIL] /proc/ai-hotpatch not found"
	@echo ""
	@cat /proc/ai-hotpatch/status 2>/dev/null || echo "  [FAIL]"
	@echo ""
	@cat /proc/ai-hotpatch/patches 2>/dev/null || echo "  [FAIL]"
	@echo ""
	@cat /proc/ai-hotpatch/hooks 2>/dev/null || echo "  [FAIL]"
	@echo ""
	@cat /proc/ai-hotpatch/config 2>/dev/null || echo "  [FAIL]"
	@echo ""
	@echo "=== Test Complete ==="

.PHONY: all clean install load unload status patches hooks config test