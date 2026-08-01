# Ainos /proc/self-heal 内核模块 Makefile
# 深度实现 v2.0.0

obj-m += self_heal.o

self_heal-objs := self_heal.o

ccflags-y := -I$(PWD) -O2 -Wall -Werror

all:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules

clean:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean

install:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules_install
	depmod -a

# 加载模块
load:
	-sudo insmod self_heal.ko
	lsmod | grep self_heal

# 卸载模块
unload:
	-sudo rmmod self_heal 2>/dev/null || true

# 查看状态
status:
	@echo "=== Health Status ==="
	@cat /proc/self-heal/status 2>/dev/null || echo "Module not loaded"
	@echo ""
	@echo "=== Event Config ==="
	@cat /proc/self-heal/config 2>/dev/null || echo "Module not loaded"
	@echo ""
	@echo "=== Event History ==="
	@cat /proc/self-heal/history 2>/dev/null || echo "Module not loaded"

# 功能测试
test:
	@echo "=== Self-Heal Module Test ==="
	@echo ""
	@echo "1. Checking /proc/self-heal files..."
	@ls -la /proc/self-heal/ 2>/dev/null || echo "  [FAIL] /proc/self-heal not found"
	@echo ""
	@echo "2. Status..."
	@cat /proc/self-heal/status 2>/dev/null || echo "  [FAIL] Cannot read status"
	@echo ""
	@echo "3. Config..."
	@cat /proc/self-heal/config 2>/dev/null || echo "  [FAIL] Cannot read config"
	@echo ""
	@echo "4. Simulating memory pressure event..."
	@echo "mem_pressure soft 0 'test trigger'" > /proc/self-heal/trigger 2>/dev/null && \
		echo "  [OK] Trigger sent" || echo "  [FAIL] Cannot trigger"
	@echo ""
	@echo "5. Checking history after trigger..."
	@cat /proc/self-heal/history 2>/dev/null || echo "  [FAIL] Cannot read history"
	@echo ""
	@echo "6. Checking stats update..."
	@cat /proc/self-heal/status 2>/dev/null | grep -i "events" || echo "  [FAIL]"
	@echo ""
	@echo "=== Test Complete ==="

# 压力测试 (模拟多种事件)
test-stress:
	@echo "=== Self-Heal Stress Test ==="
	@echo "Sending 10 trigger events..."
	@for i in $$(seq 1 10); do \
		echo "custom log 0 'stress test $$i'" > /proc/self-heal/trigger 2>/dev/null; \
	done
	@sleep 1
	@echo "History after stress:"
	@cat /proc/self-heal/history | tail -15
	@echo ""
	@echo "Stats:"
	@cat /proc/self-heal/status | grep -E "Events|Recovery|Prevention"
	@echo "=== Stress Test Complete ==="

# 配置测试
test-config:
	@echo "=== Config Test ==="
	@echo "1. Current config:"
	@cat /proc/self-heal/config
	@echo ""
	@echo "2. Changing mem_pressure to reclaim..."
	@echo "mem_pressure reclaim 30000 3 yes yes" > /proc/self-heal/config 2>/dev/null && \
		echo "  [OK] Config updated" || echo "  [FAIL]"
	@echo ""
	@echo "3. Verify config change:"
	@cat /proc/self-heal/config | grep mem_pressure
	@echo ""
	@echo "4. Resetting config..."
	@echo "reset" > /proc/self-heal/config 2>/dev/null && \
		echo "  [OK] Config reset" || echo "  [FAIL]"
	@echo ""
	@echo "5. Verify reset:"
	@cat /proc/self-heal/config | grep mem_pressure
	@echo ""
	@echo "=== Config Test Complete ==="

# 重置统计
reset-stats:
	@echo "reset" > /proc/self-heal/trigger 2>/dev/null && \
		echo "Stats reset" || echo "Failed to reset"

.PHONY: all clean install load unload status test test-stress test-config reset-stats