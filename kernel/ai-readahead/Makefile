# Ainos AI readahead 模块 Makefile
# 深度实现 v2.0.0

obj-m += ai_readahead.o

ai_readahead-objs := ai_readahead.o

ccflags-y := -I$(PWD) -O2 -Wall -Werror

all:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules

clean:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean

install:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules_install
	depmod -a

load:
	-sudo insmod ai_readahead.ko
	lsmod | grep ai_readahead

unload:
	-sudo rmmod ai_readahead 2>/dev/null || true

status:
	@echo "=== AI Readahead Status ==="
	@cat /proc/ai-readahead/status 2>/dev/null || echo "Module not loaded"

files:
	@echo "=== Tracked Files ==="
	@cat /proc/ai-readahead/files 2>/dev/null || echo "Module not loaded"

config:
	@echo "=== Config ==="
	@cat /proc/ai-readahead/config 2>/dev/null || echo "Module not loaded"

test:
	@echo "=== AI Readahead Module Test ==="
	@ls -la /proc/ai-readahead/ 2>/dev/null || echo "  [FAIL] /proc/ai-readahead not found"
	@echo ""
	@cat /proc/ai-readahead/status 2>/dev/null || echo "  [FAIL] Cannot read status"
	@echo ""
	@cat /proc/ai-readahead/files 2>/dev/null || echo "  [FAIL] Cannot read files"
	@echo ""
	@cat /proc/ai-readahead/config 2>/dev/null || echo "  [FAIL] Cannot read config"
	@echo ""
	@echo "=== Test Complete ==="

.PHONY: all clean install load unload status files config test