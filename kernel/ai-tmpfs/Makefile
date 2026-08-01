# Ainos AI tmpfs 模块 Makefile
# 深度实现 v2.0.0

obj-m += ai_tmpfs.o

ai_tmpfs-objs := ai_tmpfs.o

ccflags-y := -I$(PWD) -O2 -Wall -Werror

all:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules

clean:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean

install:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules_install
	depmod -a

load:
	-sudo insmod ai_tmpfs.ko
	lsmod | grep ai_tmpfs

unload:
	-sudo rmmod ai_tmpfs 2>/dev/null || true

# 挂载 AI tmpfs
mount:
	@echo "Mounting AI tmpfs at /mnt/ai-tmpfs..."
	-sudo mkdir -p /mnt/ai-tmpfs
	-sudo mount -t ai_tmpfs none /mnt/ai-tmpfs
	@echo "Mounted:"
	@mount | grep ai_tmpfs

# 卸载 AI tmpfs
umount:
	-sudo umount /mnt/ai-tmpfs 2>/dev/null || true

# 查看状态
status:
	@echo "=== AI tmpfs Status ==="
	@cat /proc/ai-tmpfs/status 2>/dev/null || echo "Module not loaded"

# 查看文件列表
files:
	@echo "=== AI tmpfs Files ==="
	@cat /proc/ai-tmpfs/files 2>/dev/null || echo "Module not loaded"

# 查看配置
config:
	@echo "=== AI tmpfs Config ==="
	@cat /proc/ai-tmpfs/config 2>/dev/null || echo "Module not loaded"

# 功能测试
test:
	@echo "=== AI tmpfs Module Test ==="
	@echo ""
	@echo "1. Checking /proc/ai-tmpfs files..."
	@ls -la /proc/ai-tmpfs/ 2>/dev/null || echo "  [FAIL] /proc/ai-tmpfs not found"
	@echo ""
	@echo "2. Status..."
	@cat /proc/ai-tmpfs/status 2>/dev/null || echo "  [FAIL]"
	@echo ""
	@echo "3. Config..."
	@cat /proc/ai-tmpfs/config 2>/dev/null || echo "  [FAIL]"
	@echo ""
	@echo "4. Files..."
	@cat /proc/ai-tmpfs/files 2>/dev/null || echo "  [FAIL]"
	@echo ""
	@echo "5. Mounting filesystem..."
	-sudo mkdir -p /mnt/ai-tmpfs 2>/dev/null
	-sudo mount -t ai_tmpfs none /mnt/ai-tmpfs 2>/dev/null && \
		echo "  [OK] Mounted at /mnt/ai-tmpfs" || echo "  [FAIL] Cannot mount"
	@echo ""
	@echo "6. Writing test file..."
	@echo "Hello Ainos!" | sudo tee /mnt/ai-tmpfs/test.txt > /dev/null 2>&1 && \
		echo "  [OK] File created" || echo "  [FAIL] Cannot create file"
	@echo ""
	@echo "7. Reading test file..."
	@cat /mnt/ai-tmpfs/test.txt 2>/dev/null && echo "  [OK]" || echo "  [FAIL] Cannot read"
	@echo ""
	@echo "8. Checking updated files list..."
	@cat /proc/ai-tmpfs/files 2>/dev/null
	@echo ""
	@echo "9. Unmounting..."
	-sudo umount /mnt/ai-tmpfs 2>/dev/null && echo "  [OK] Unmounted" || echo "  [FAIL]"
	@echo ""
	@echo "=== Test Complete ==="

.PHONY: all clean install load unload mount umount status files config test