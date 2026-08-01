# Ainos SDK Makefile (支持 Windows 和 Linux)
CC = gcc
AR = ar
CFLAGS = -Wall -Wextra -O2 -fPIC

# 平台检测
ifeq ($(OS),Windows_NT)
    LIBS = -lws2_32
    LDFLAGS = -shared -Wl,--out-implib,libainos.dll.a
    LIB_SHARED = libainos.dll
    LIB_STATIC = libainos.a
    TEST_BIN = ainos_test.exe
    RM = del /Q 2>nul || true
else
    LIBS = -lpthread
    LDFLAGS = -shared -fPIC
    LIB_SHARED = libainos.so
    LIB_STATIC = libainos.a
    TEST_BIN = ainos_test
    RM = rm -f
endif

# 源文件
SRCS = libainos.c
OBJS = $(SRCS:.c=.o)

.PHONY: all clean install test

all: $(LIB_STATIC) $(LIB_SHARED)

# 静态库
$(LIB_STATIC): $(OBJS)
	$(AR) rcs $@ $^

# 动态库
$(LIB_SHARED): $(OBJS)
	$(CC) $(LDFLAGS) -o $@ $^ $(LIBS)

# 编译
%.o: %.c ainos.h
	$(CC) $(CFLAGS) -c $< -o $@

# 清理
clean:
	-$(RM) $(OBJS) $(LIB_STATIC) $(LIB_SHARED) $(TEST_BIN)

# 测试程序
test: $(LIB_STATIC) ainos_test.c
	$(CC) $(CFLAGS) -o $(TEST_BIN) ainos_test.c -L. -lainos $(LIBS)
	./$(TEST_BIN)