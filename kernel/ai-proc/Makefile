# Ainos /proc/ai 内核模块 Makefile

obj-m += proc_ai.o

proc_ai-objs := proc_ai.o

ccflags-y := -I$(PWD) -O2 -Wall -Werror

BRIDGE := ai-proc-bridge
BRIDGE_SRC := ai-proc-bridge.c
CC := gcc

all: module bridge

module:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules

bridge: $(BRIDGE_SRC)
	$(CC) -O2 -Wall -Wextra -o $(BRIDGE) $(BRIDGE_SRC)

clean:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean
	rm -f $(BRIDGE)

install: module
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules_install
	depmod -a

# 加载模块
load:
	-sudo insmod proc_ai.ko
	lsmod | grep proc_ai

# 卸载模块
unload:
	-sudo rmmod proc_ai 2>/dev/null || true
	-sudo pkill ai-proc-bridge 2>/dev/null || true

# 启动 bridge (前台)
bridge-start:
	@echo "Starting ai-proc-bridge (foreground)..."
	@echo "Make sure ai-daemon is running on $(DAEMON_ADDR):$(DAEMON_PORT)"
	./$(BRIDGE)

# 启动 bridge (后台守护进程)
bridge-daemon:
	@echo "Starting ai-proc-bridge (daemon)..."
	./$(BRIDGE) -d

# 全栈启动
start: load
	@echo "Starting ai-proc-bridge..."
	./$(BRIDGE) -d

# 全栈停止
stop: unload

# 功能测试
test:
	@echo "=== /proc/ai files ==="
	@ls -la /proc/ai/ 2>/dev/null || echo "Module not loaded"
	@echo ""
	@echo "=== Status ==="
	@cat /proc/ai/status 2>/dev/null || echo "Module not loaded"
	@echo ""
	@echo "=== Config ==="
	@cat /proc/ai/config 2>/dev/null || echo "Module not loaded"
	@echo ""
	@echo "=== Stats ==="
	@cat /proc/ai/stats 2>/dev/null || echo "Module not loaded"

# 集成测试 (需要加载模块并启动 bridge + daemon)
test-integration:
	@echo "=== Integration Test: /proc/ai ==="
	@echo "1. Status check:"
	@cat /proc/ai/status
	@echo ""
	@echo "2. Model list:"
	@cat /proc/ai/models
	@echo ""
	@echo "3. Inference test:"
	@echo "Hello, Ainos!" > /proc/ai/infer
	@sleep 1
	@cat /proc/ai/infer
	@echo ""
	@echo "4. Embedding test:"
	@echo "Test text" > /proc/ai/embed
	@sleep 1
	@cat /proc/ai/embed
	@echo ""
	@echo "5. Stats:"
	@cat /proc/ai/stats
	@echo ""
	@echo "=== Test complete ==="

# 并发压力测试
test-concurrency:
	@echo "=== Concurrency Test ==="
	for i in $$(seq 1 10); do \
		echo "request $$i from $$(date +%H:%M:%S)" > /proc/ai/infer & \
	done
	@sleep 2
	@echo "Results:"
	@cat /proc/ai/stats

# 设备测试
test-device:
	@echo "=== /dev/ainos-proc ==="
	@ls -la /dev/ainos-proc 2>/dev/null || echo "Device not found"
	@echo ""
	@echo "Device info:"
	@cat /proc/devices | grep ainos || echo "Not in /proc/devices"

# 性能基准
benchmark:
	@echo "=== Benchmark ==="
	@echo "Testing inference throughput..."
	@echo "Sending 100 requests..."
	@for i in $$(seq 1 100); do \
		echo "benchmark request $$i" > /proc/ai/infer 2>/dev/null; \
	done
	@sleep 2
	@cat /proc/ai/stats

.PHONY: all module bridge clean install load unload bridge-start bridge-daemon
.PHONY: start stop test test-integration test-concurrency test-device benchmark