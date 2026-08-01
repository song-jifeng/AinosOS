# Ainos OS - AI 安全策略模块 (ai-policy) 架构设计

## 1. 概述

ai-policy 是 Ainos OS 的 AI 数据访问权限管理模块。系统级 AI 可以访问大量个人数据（文件、剪贴板、浏览器历史、摄像头等），需要一套**细粒度的权限控制**来保护用户隐私。

```
用户: "AI 可以读剪贴板，但不能读浏览器历史"
                        ↓
              ┌─────────────────────┐
              │   AI 安全策略引擎     │
              │   (ai-policyd)       │
              └─────────┬───────────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
   ┌──────────┐  ┌──────────┐  ┌──────────┐
   │ 策略定义   │  │ 策略执行   │  │ 审计日志  │
   │ (策略语言) │  │ (LSM钩子) │  │ (审计)   │
   └──────────┘  └──────────┘  └──────────┘
```

## 2. 设计原则

### 2.1 最小权限 (Least Privilege)
- AI 默认没有任何数据访问权限
- 每个数据源需要显式授权
- 权限可以按时间、范围、用途细化

### 2.2 分层策略模型

```
策略层级 (从高到低):
┌─────────────────────────────────────┐
│  1. 系统强制策略 (System-Wide)       │  ← 管理员设置，不可覆盖
│     "所有AI不能访问 /etc/shadow"      │
├─────────────────────────────────────┤
│  2. 用户级策略 (User-Level)          │  ← 用户设置，可覆盖默认
│     "AI可以读 Documents/ 但不可写"    │
├─────────────────────────────────────┤
│  3. 应用级策略 (App-Level)           │  ← 每个AI应用单独设置
│     "AI编辑器可以访问当前打开的文件"    │
├─────────────────────────────────────┤
│  4. 会话级策略 (Session-Level)       │  ← 临时授权，用完即弃
│     "允许本次对话读取剪贴板"           │
└─────────────────────────────────────┘
```

### 2.3 数据分类

```
AI 数据权限分类:
├── 📁 文件系统
│   ├── Documents/           ← 个人文档
│   ├── Downloads/           ← 下载文件
│   ├── Desktop/             ← 桌面
│   ├── ~/.config/           ← 应用配置
│   └── ~/.local/            ← 本地数据
│
├── 📋 剪贴板
│   ├── clipboard-read       ← 读取剪贴板
│   └── clipboard-write      ← 写入剪贴板
│
├── 🌐 网络
│   ├── browser-history      ← 浏览器历史
│   ├── browser-bookmarks    ← 浏览器书签
│   ├── browser-cookies      ← 浏览器 Cookie
│   └── network-status       ← 网络状态
│
├── 🎤 硬件
│   ├── microphone           ← 麦克风
│   ├── camera               ← 摄像头
│   ├── screen-capture       ← 屏幕截图
│   └── location             ← 位置
│
├── 💬 通信
│   ├── contacts             ← 联系人
│   ├── messages             ← 消息记录
│   ├── emails               ← 邮件
│   └── notifications        ← 通知
│
└── 🔑 系统
    ├── process-list         ← 进程列表
    ├── system-logs          ← 系统日志
    ├── environment          ← 环境变量
    └── credentials          ← 凭据存储
```

## 3. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      用户空间                                  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │             AI 安全策略守护进程 (ai-policyd)           │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │   │
│  │  │ 策略引擎   │  │ 策略数据库 │  │ 审计日志          │   │   │
│  │  │ (policy  │  │ (SQLite) │  │ (journald)       │   │   │
│  │  │  engine) │  │          │  │                  │   │   │
│  │  └─────┬────┘  └────┬─────┘  └──────────────────┘   │   │
│  │        │             │                               │   │
│  │  ┌─────┴─────────────┴──────────────────────────┐   │   │
│  │  │              策略编译器                        │   │   │
│  │  │  (Policy Compiler: 策略语言 → 二进制策略)      │   │   │
│  │  └───────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
│                           │ IPC                              │
│          ┌────────────────┼────────────────┐                │
│          ▼                ▼                ▼                │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │ AI 守护进程   │ │ AI 应用      │ │ ai-policy     │        │
│  │ (ai-daemon)  │ │ (请求权限)   │ │ 控制面板      │        │
│  └──────┬───────┘ └──────────────┘ └──────────────┘        │
│         │                                                   │
├─────────┴───────────────────────────────────────────────────┤
│                       内核层                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         LSM 钩子 (Linux Security Module)              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │   │
│  │  │ ai_access │  │ ai_audit │  │ sys_ai_check_perm│   │   │
│  │  │ 钩子      │  │ 钩子     │  │ 系统调用          │   │   │
│  │  └──────────┘  └──────────┘  └──────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 4. 策略语言定义

### 4.1 策略语法 (Ainos Policy Language - APL)

```apl
// 文件: /etc/ainos/policy/ai-policies.apl

// 系统级策略
system_policy "base" {
    // 所有 AI 不能访问系统关键文件
    deny ai any read path "/etc/shadow";
    deny ai any read path "/etc/gshadow";
    deny ai any read path "/var/log/auth.log";

    // 所有 AI 不能访问凭据
    deny ai any read category "credentials";
}

// 用户级策略
user_policy "default" {
    // 默认允许读取 Documents，禁止写入
    allow ai any read path "/home/*/Documents/**";
    deny ai any write path "/home/*/Documents/**";

    // 剪贴板需要明确授权
    deny ai any read resource "clipboard";
    deny ai any write resource "clipboard";

    // 网络资源需要明确授权
    deny ai any read resource "browser-history";
    deny ai any read resource "browser-bookmarks";
}

// 应用级策略
app_policy "AI-Editor" {
    // AI 编辑器可以读写当前文件
    allow ai editor read path "/home/*/Projects/**";
    allow ai editor write path "/home/*/Projects/**";

    // 可以读剪贴板（用于粘贴）
    allow ai editor read resource "clipboard" 
        max_duration "5s";
}

// 临时授权
temp_auth "clipboard-paste" {
    allow ai "AI-Editor" read resource "clipboard"
        expires "2026-08-01T12:00:00";
}
```

### 4.2 策略规则结构

```c
struct ai_policy_rule {
    enum ai_policy_effect effect;  // allow / deny / audit
    enum ai_policy_scope scope;    // system / user / app / session
    char *subject;                  // AI 应用标识
    enum ai_policy_action action;  // read / write / execute / all
    enum ai_policy_resource_type type;  // path / resource / category
    char *target;                    // 资源路径或名称
    struct ai_policy_constraint *constraints;  // 时间、范围等约束
};
```

## 5. 权限检查流程

```
AI 应用请求访问数据
       │
       ▼
┌──────────────────┐
│ 1. 收集请求信息   │  subject, action, resource, context
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 2. 策略匹配       │  ← 从高到低逐级匹配 (system→user→app→session)
└────────┬─────────┘
         ▼
┌──────────────────┐     ┌──────────┐
│ 3. 决策           │────▶│ allow    │──▶ 允许访问 + 审计日志
│ (效力计算)        │     └──────────┘
└────────┬─────────┘     ┌──────────┐
         │               │ deny     │──▶ 拒绝访问 + 审计日志
         │               └──────────┘
         │               ┌──────────┐
         │               │ ask      │──▶ 弹窗询问用户
         │               └──────────┘
         ▼
┌──────────────────┐
│ 4. 缓存决策结果   │  默认缓存 5 分钟
└──────────────────┘
```

## 6. 权限请求 UI 流程

```
AI 应用请求访问数据时:
  1. 系统托盘弹出权限请求通知
  2. 用户可以选择:
     [允许本次]  [允许永久]  [拒绝本次]  [拒绝永久]
  3. 用户的选择被记录到策略数据库
  4. ai-policyd 更新策略并缓存决策

用户可以通过控制面板查看:
  ├── 当前活跃的 AI 权限
  ├── 最近的 AI 访问审计日志
  └── 管理所有 AI 应用权限
```

## 7. 与 SELinux/AppArmor 集成

```c
// 内核 LSM 钩子集成
struct ai_security_ops {
    int (*ai_file_permission)(struct file *file, int mask);
    int (*ai_check_access)(const char *resource, int mask);
    int (*ai_audit_event)(const char *event, int result);
};

// 注册到 LSM 框架
void ai_register_lsm_hooks(void) {
    security_add_hooks(ai_hooks, ARRAY_SIZE(ai_hooks), "ainos");
}
```

## 8. 审计日志格式

```json
{
    "timestamp": "2026-08-01T10:00:00Z",
    "ai_app": "AI-Editor",
    "action": "read",
    "resource": "/home/user/Documents/project.md",
    "decision": "allow",
    "policy": "app_policy/AI-Editor",
    "user_id": 1000,
    "session_id": "sess-abc123"
}
```

## 9. 安全考量

- 策略文件只允许 root 写入
- AI 守护进程以非特权用户运行
- 所有权限检查在内核态有第二道防线
- 审计日志不可篡改 (append-only)
- 紧急切断开关 (kill switch) 一键禁用所有 AI 数据访问