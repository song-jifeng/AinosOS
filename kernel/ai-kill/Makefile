# Ainos AI KILL 模块 Makefile
# 深度实现 v2.0.0

obj-m += ai_kill.o

ai_kill-objs := ai_kill.o

ccflags-y := -I$(PWD) -O2 -Wall -Werror

all:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules

clean:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean

install:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules_install
	depmod -a

load:
	-sudo insmod ai_kill.ko
	lsmod | grep ai_kill

unload:
	-sudo rmmod ai_kill 2>/dev/null || true

# 查看进程评分
scores:
	@echo "=== Process Scores ==="
	@cat /proc/ai-kill/scores 2>/dev/null || echo "Module not loaded"

# 查看配置
config:
	@echo "=== AI KILL Config ==="
	@cat /proc/ai-kill/config 2>/dev/null || echo "Module not loaded"

# 查看统计
stats:
	@echo "=== AI KILL Stats ==="
	@cat /proc/ai-kill/stats 2>/dev/null || echo "Module not loaded"

# 查看杀戮历史
history:
	@echo "=== Kill History ==="
	@cat /proc/ai-kill/history 2>/dev/null || echo "Module not loaded"

# 查看行为跟踪
behavior:
	@echo "=== Process Behavior ==="
	@cat /proc/ai-kill/behavior 2>/dev/null || echo "Module not loaded"

# 状态概览
status: scores stats

# 功能测试
test:
	@echo "=== AI KILL Module Test ==="
	@echo ""
	@echo "1. Checking /proc/ai-kill files..."
	@ls -la /proc/ai-kill/ 2>/dev/null || echo "  [FAIL] /proc/ai-kill not found"
	@echo ""
	@echo "2. Scores..."
	@cat /proc/ai-kill/scores | head -20 2>/dev/null || echo "  [FAIL]"
	@echo ""
	@echo "3. Config..."
	@cat /proc/ai-kill/config 2>/dev/null || echo "  [FAIL]"
	@echo ""
	@echo "4. Changing config..."
	@echo "threshold 30 50 70" > /proc/ai-kill/config 2>/dev/null && \
		echo "  [OK] Config updated" || echo "  [FAIL]"
	@echo ""
	@echo "5. Changing weight..."
	@echo "weight mem 30" > /proc/ai-kill/config 2>/dev/null && \
		echo "  [OK] Weight updated" || echo "  [FAIL]"
	@echo ""
	@echo "6. Stats..."
	@cat /proc/ai-kill/stats 2>/dev/null || echo "  [FAIL]"
	@echo ""
	@echo "7. Behavior table..."
	@cat /proc/ai-kill/behavior 2>/dev/null || echo "  [FAIL]"
	@echo ""
	@echo "8. Resetting config..."
	@echo "reset" > /proc/ai-kill/config 2>/dev/null && \
		echo "  [OK] Config reset" || echo "  [FAIL]"
	@echo ""
	@echo "=== Test Complete ==="

.PHONY: all clean install load unload scores config stats history behavior status test