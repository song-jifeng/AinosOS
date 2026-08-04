# AinosOS Security Guide / 安全指南

> **Version:** 1.0.0 | **Updated:** 2026-08-04
>
> Comprehensive security guide for the AinosOS inference platform.
> AinosOS 推理平台的全面安全指南。

---

## Table of Contents / 目录

1. [Security Model Overview / 安全模型概述](#1-security-model-overview)
2. [Authentication Setup / 认证配置](#2-authentication-setup)
3. [TLS Configuration / TLS 配置](#3-tls-configuration)
4. [Rate Limiting / 速率限制](#4-rate-limiting)
5. [Audit Logging / 审计日志](#5-audit-logging)
6. [Firewall Rules / 防火墙规则](#6-firewall-rules)
7. [SELinux/AppArmor Profiles / SELinux/AppArmor 配置文件](#7-selinuxapparmor-profiles)
8. [Container Security / 容器安全](#8-container-security)
9. [Secrets Management / 密钥管理](#9-secrets-management)
10. [Security Checklist / 安全检查清单](#10-security-checklist)
11. [Incident Response / 事件响应](#11-incident-response)
12. [Vulnerability Management / 漏洞管理](#12-vulnerability-management)

---

## 1. Security Model Overview / 安全模型概述

### Architecture / 架构

```
┌─────────────────────────────────────────────────────────┐
│                     Internet / Client                     │
└────────────────────────┬────────────────────────────────┘
                         │
                    ┌────▼────┐
                    │  TLS    │
                    │  LB     │
                    └────┬────┘
                         │
              ┌──────────┼──────────┐
              │          │          │
         ┌────▼────┐ ┌───▼───┐ ┌───▼───┐
         │ Nginx   │ │ API   │ │ WS    │
         │ Reverse │ │ Server│ │ Proxy │
         │ Proxy   │ │       │ │       │
         └────┬────┘ └───┬───┘ └───┬───┘
              │          │          │
         ┌────▼──────────▼──────────▼────┐
         │         App Layer              │
         │  Auth | Rate Limit | Audit     │
         └───────────────────────────────┘
                         │
              ┌──────────┼──────────┐
              │          │          │
         ┌────▼────┐ ┌───▼───┐ ┌───▼───┐
         │ Models  │ │ DB    │ │ Redis  │
         │ Storage │ │       │ │ Cache  │
         └─────────┘ └───────┘ └───────┘
```

### Security Principles / 安全原则

1. **Defense in Depth / 纵深防御** - Multiple layers of security controls
2. **Least Privilege / 最小权限** - Minimal required access for all components
3. **Secure by Default / 默认安全** - Secure defaults with opt-in for less secure options
4. **Zero Trust / 零信任** - Verify every request regardless of source
5. **Fail Secure / 安全失效** - Failures default to secure state
6. **Audit Everything / 全面审计** - Log all security-relevant events

### Threat Model / 威胁模型

| Threat | Impact | Mitigation |
|--------|--------|------------|
| Unauthorized API access | Data breach, model theft | Token auth, rate limiting, IP whitelist |
| Model poisoning | Malicious outputs | Model integrity checks, input validation |
| DoS attack | Service disruption | Rate limiting, auto-scaling, WAF |
| Data exfiltration | Sensitive data leak | Encryption, access control, audit |
| Privilege escalation | System compromise | Container isolation, least privilege |
| Supply chain attack | Malicious dependencies | Dependency scanning, signatures |
| Side-channel attack | Information leakage | Constant-time operations, isolation |

---

## 2. Authentication Setup / 认证配置

### Token-Based Authentication / 基于令牌的认证

```bash
# 1. Generate a secure API token
# Use a cryptographically strong random token
export AINOS_API_TOKEN=$(openssl rand -hex 32)
echo "API Token: ${AINOS_API_TOKEN}"

# Alternative: Use UUID
export AINOS_API_TOKEN=$(python3 -c "import uuid; print(uuid.uuid4().hex)")
echo "API Token: ${AINOS_API_TOKEN}"

# 2. Configure the server
# Set in environment
export AINOS_ENABLE_AUTH=true
export AINOS_API_TOKEN=${AINOS_API_TOKEN}

# Or in config file
cat >> config/ainos.yaml << 'EOF'
auth:
  enabled: true
  token: ${AINOS_API_TOKEN}
  rate_limit: 100
  token_header: "Authorization"
  token_scheme: "Bearer"
EOF
```

### Client Configuration / 客户端配置

```python
# Python SDK - Authenticated client
import requests

API_BASE = "https://api.ainos.ai"
API_TOKEN = "your-token-here"

def get_headers():
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json",
    }

# Status check
response = requests.get(f"{API_BASE}/api/status", headers=get_headers())
print(response.json())

# Inference
response = requests.post(
    f"{API_BASE}/api/inference",
    headers=get_headers(),
    json={
        "model": "ainos-llama-3.1-8b",
        "prompt": "Hello, how are you?",
        "max_tokens": 100,
    }
)
print(response.json())
```

```javascript
// Node.js SDK - Authenticated client
const API_BASE = 'https://api.ainos.ai';
const API_TOKEN = 'your-token-here';

async function queryAPI(endpoint, method = 'GET', body = null) {
    const options = {
        method,
        headers: {
            'Authorization': `Bearer ${API_TOKEN}`,
            'Content-Type': 'application/json',
        },
    };
    if (body) options.body = JSON.stringify(body);
    const response = await fetch(`${API_BASE}${endpoint}`, options);
    return response.json();
}
```

### API Key Rotation / 密钥轮换

```bash
#!/bin/bash
# D:/Ainos/scripts/rotate-api-token.sh
# API Token Rotation Script
# ===========================

set -euo pipefail

echo "[$(date)] Starting API token rotation..."

# 1. Generate new token
NEW_TOKEN=$(openssl rand -hex 32)
echo "Generated new token"

# 2. Update configuration
# For docker-compose:
sed -i "s/AINOS_API_TOKEN=.*/AINOS_API_TOKEN=${NEW_TOKEN}/" .env

# For Kubernetes:
kubectl create secret generic ainos-secrets \
    --namespace ainos \
    --from-literal=api-token=${NEW_TOKEN} \
    --dry-run=client -o yaml | kubectl apply -f -

# 3. Graceful restart
docker compose restart ainos-api
# or
kubectl rollout restart deployment ainos-api -n ainos

# 4. Verify new token
sleep 10
curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer ${NEW_TOKEN}" \
    "http://localhost:8080/api/status"

echo "[$(date)] Token rotation completed"
echo "New token: ${NEW_TOKEN:0:8}... (first 8 chars shown)"
```

### Multi-Factor Authentication (MFA)

```yaml
# D:/Ainos/config/auth/mfa.yaml
# MFA Configuration
# ==================

mfa:
  enabled: true
  methods:
    - totp  # Time-based One-Time Password
    - email_otp  # Email OTP fallback
  
  totp:
    issuer: "AinosOS"
    algorithm: "SHA1"
    digits: 6
    period: 30
  
  email_otp:
    expiry: 300  # 5 minutes
    length: 8
    rate_limit: 3  # Max attempts per period
```

### OAuth2 / OpenID Connect Integration

```yaml
# D:/Ainos/config/auth/oidc.yaml
# OpenID Connect Configuration
# ============================

oidc:
  enabled: false
  provider: "https://accounts.google.com"
  client_id: "${OIDC_CLIENT_ID}"
  client_secret: "${OIDC_CLIENT_SECRET}"
  redirect_uri: "https://dashboard.ainos.ai/auth/callback"
  scopes:
    - openid
    - profile
    - email
  claims:
    - email
    - name
    - roles
  
  # Role mapping
  role_mapping:
    admin: ["admin@ainos.ai"]
    operator: ["*@ainos.ai"]
```

---

## 3. TLS Configuration / TLS 配置

### Self-Signed Certificate (Development)

```bash
# Generate self-signed certificate for development
mkdir -p /opt/ainos/ssl
cd /opt/ainos/ssl

# Generate CA key and certificate
openssl genrsa -out ca.key 4096
openssl req -new -x509 -days 3650 -key ca.key -out ca.crt \
    -subj "/C=CN/ST=Beijing/L=Beijing/O=AinosOS/CN=AinosOS CA"

# Generate server key and CSR
openssl genrsa -out server.key 4096
openssl req -new -key server.key -out server.csr \
    -subj "/C=CN/ST=Beijing/L=Beijing/O=AinosOS/CN=api.ainos.ai"

# Configure SAN (Subject Alternative Names)
cat > san.cnf << 'EOF'
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = CN
ST = Beijing
L = Beijing
O = AinosOS
CN = api.ainos.ai

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = api.ainos.ai
DNS.2 = dashboard.ainos.ai
DNS.3 = localhost
IP.1 = 127.0.0.1
EOF

# Sign the certificate
openssl x509 -req -days 365 -in server.csr \
    -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out server.crt -extensions v3_req -extfile san.cnf

# Verify
openssl x509 -in server.crt -text -noout | grep -A1 "Subject Alternative Name"
```

### Let's Encrypt (Production)

```bash
# Using certbot
sudo apt-get install -y certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d api.ainos.ai -d dashboard.ainos.ai \
    --non-interactive \
    --agree-tos \
    --email admin@ainos.ai

# Auto-renewal (certbot adds systemd timer automatically)
sudo certbot renew --dry-run

# Using acme.sh (alternative)
curl https://get.acme.sh | sh
acme.sh --issue -d api.ainos.ai -d dashboard.ainos.ai \
    --nginx \
    --keylength ec-384
```

### Nginx TLS Configuration

```nginx
# D:/Ainos/deploy/nginx/ssl.conf
# TLS Configuration
# ==================

# Modern TLS configuration (Mozilla recommended)
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
ssl_prefer_server_ciphers off;
ssl_ecdh_curve X25519:prime256v1:secp384r1;

# OCSP Stapling
ssl_stapling on;
ssl_stapling_verify on;
resolver 1.1.1.1 8.8.8.8 valid=300s;
resolver_timeout 5s;

# Session cache
ssl_session_cache shared:SSL:10m;
ssl_session_timeout 1d;
ssl_session_tickets off;

# HSTS
add_header Strict-Transport-Security "max-age=63072000" always;

# Certificate paths
ssl_certificate /etc/nginx/ssl/fullchain.pem;
ssl_certificate_key /etc/nginx/ssl/privkey.pem;
ssl_trusted_certificate /etc/nginx/ssl/chain.pem;
```

### TLS Certificate Monitoring

```bash
#!/bin/bash
# D:/Ainos/scripts/check-cert-expiry.sh
# Certificate Expiry Check
# =========================

DOMAINS="api.ainos.ai dashboard.ainos.ai"
WARN_DAYS=30
CRITICAL_DAYS=7

for domain in $DOMAINS; do
    echo "Checking $domain..."
    
    expiry_date=$(echo | openssl s_client -servername "$domain" -connect "$domain:443" 2>/dev/null | openssl x509 -noout -enddate | cut -d= -f2)
    expiry_epoch=$(date -d "$expiry_date" +%s)
    now_epoch=$(date +%s)
    days_left=$(( (expiry_epoch - now_epoch) / 86400 ))
    
    echo "  Expires: $expiry_date ($days_left days left)"
    
    if [ $days_left -le $CRITICAL_DAYS ]; then
        echo "  CRITICAL: Certificate expires in $days_left days!"
        # Send alert
        curl -s -X POST "$WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"text\":\"CRITICAL: Certificate for $domain expires in $days_left days\"}"
    elif [ $days_left -le $WARN_DAYS ]; then
        echo "  WARNING: Certificate expires in $days_left days"
    fi
done
```

---

## 4. Rate Limiting / 速率限制

### Server-Side Rate Limiting

```python
# D:/Ainos/system-services/web-panel/rate_limiter.py
# Rate Limiter Implementation
# =============================

import time
from collections import defaultdict
from typing import Dict, Tuple, Optional

class RateLimiter:
    """
    Sliding window rate limiter.
    """
    
    def __init__(self):
        self._windows: Dict[str, list] = defaultdict(list)
    
    def check_rate_limit(
        self,
        key: str,
        max_requests: int = 100,
        window_seconds: int = 60,
    ) -> Tuple[bool, Dict]:
        """
        Check if request is within rate limit.
        
        Returns:
            (allowed, headers)
        """
        now = time.time()
        window_start = now - window_seconds
        
        # Clean old entries
        self._windows[key] = [
            t for t in self._windows[key] if t > window_start
        ]
        
        # Count requests in window
        count = len(self._windows[key])
        remaining = max(0, max_requests - count)
        
        headers = {
            "X-RateLimit-Limit": str(max_requests),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(int(window_start + window_seconds)),
        }
        
        if count >= max_requests:
            return False, headers
        
        # Record this request
        self._windows[key].append(now)
        return True, headers
    
    def get_remaining(self, key: str, max_requests: int = 100, window_seconds: int = 60) -> int:
        now = time.time()
        window_start = now - window_seconds
        self._windows[key] = [t for t in self._windows[key] if t > window_start]
        return max(0, max_requests - len(self._windows[key]))


# Rate limit tiers
RATE_LIMIT_TIERS = {
    "free": {
        "requests_per_minute": 10,
        "requests_per_hour": 100,
        "requests_per_day": 500,
        "concurrent": 1,
    },
    "basic": {
        "requests_per_minute": 60,
        "requests_per_hour": 1000,
        "requests_per_day": 5000,
        "concurrent": 5,
    },
    "pro": {
        "requests_per_minute": 300,
        "requests_per_hour": 5000,
        "requests_per_day": 50000,
        "concurrent": 20,
    },
    "enterprise": {
        "requests_per_minute": 1000,
        "requests_per_hour": 50000,
        "requests_per_day": 500000,
        "concurrent": 100,
    },
}
```

### Nginx Rate Limiting

```nginx
# D:/Ainos/deploy/nginx/rate-limit.conf
# Rate Limiting Configuration
# =============================

# Define rate limit zones
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=100r/s;
limit_req_zone $binary_remote_addr zone=auth_limit:10m rate=10r/m;
limit_req_zone $http_authorization zone=token_limit:10m rate=1000r/m;

# Connection limiting
limit_conn_zone $binary_remote_addr zone=addr_limit:10m;
limit_conn_zone $server_name zone=server_limit:10m;

server {
    # API rate limiting
    location /api/ {
        limit_req zone=api_limit burst=200 nodelay;
        limit_req_status 429;
        
        # Per-IP connection limit
        limit_conn addr_limit 10;
        limit_conn_status 429;
        
        # Token-based rate limiting
        if ($http_authorization) {
            set $token_key $http_authorization;
        }
        
        # Error response
        error_page 429 @rate_limited;
        
        proxy_pass http://ainos_backend;
    }
    
    # Auth endpoint - stricter limits
    location /api/auth/ {
        limit_req zone=auth_limit burst=5 nodelay;
        limit_req_status 429;
        proxy_pass http://ainos_backend;
    }
    
    # Rate limit response
    location @rate_limited {
        default_type application/json;
        return 429 '{"error":"Too Many Requests","detail":"Rate limit exceeded. Please try again later.","retry_after":60}';
        add_header Retry-After 60;
    }
}
```

### Redis-Based Distributed Rate Limiting

```python
# D:/Ainos/system-services/web-panel/redis_rate_limiter.py
# Redis-based rate limiter for distributed deployments
# ======================================================

import time
import hashlib
import aioredis
from typing import Optional

class RedisRateLimiter:
    """
    Distributed rate limiter using Redis.
    Implements sliding window counter algorithm.
    """
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
    
    async def connect(self):
        if not self.redis:
            self.redis = await aioredis.from_url(
                self.redis_url,
                max_connections=10,
                decode_responses=True,
            )
    
    async def check(self, key: str, limit: int, window: int = 60) -> bool:
        """
        Check if request is within rate limit.
        
        Args:
            key: Rate limit key (e.g., IP, user ID)
            limit: Maximum requests in window
            window: Time window in seconds
        
        Returns:
            True if request is allowed
        """
        await self.connect()
        
        now = int(time.time())
        window_key = f"ratelimit:{key}:{now // window}"
        
        count = await self.redis.incr(window_key)
        
        if count == 1:
            # Set expiry on first increment
            await self.redis.expire(window_key, window * 2)
        
        return count <= limit
    
    async def get_remaining(self, key: str, limit: int, window: int = 60) -> int:
        """Get remaining requests in current window."""
        await self.connect()
        
        now = int(time.time())
        window_key = f"ratelimit:{key}:{now // window}"
        
        count = int(await self.redis.get(window_key) or 0)
        return max(0, limit - count)
    
    async def reset(self, key: str):
        """Reset rate limit for a key."""
        await self.connect()
        now = int(time.time())
        pattern = f"ratelimit:{key}:*"
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern)
            if keys:
                await self.redis.delete(*keys)
            if cursor == 0:
                break
```

---

## 5. Audit Logging / 审计日志

### Audit Log Configuration

```yaml
# D:/Ainos/config/audit.yaml
# Audit Logging Configuration
# =============================

audit:
  enabled: true
  log_file: /var/log/ainos/audit.log
  format: json
  
  # Events to audit
  events:
    authentication:
      - login_success
      - login_failure
      - token_created
      - token_revoked
    
    api:
      - inference_request
      - model_load
      - model_unload
      - context_create
      - context_delete
      - plugin_toggle
      - settings_change
    
    admin:
      - user_created
      - user_deleted
      - role_changed
      - system_config_change
    
    security:
      - rate_limit_exceeded
      - auth_failure
      - invalid_token
      - suspicious_activity
  
  # Sensitive data masking
  masking:
    enabled: true
    fields:
      - password
      - token
      - secret
      - api_key
      - credit_card
      - ssn
    mask_char: "*"
    mask_length: 8
  
  # Retention
  retention:
    max_size: 10GB
    max_age: 365d
    compression: gzip
```

### Audit Log Format

```json
{
  "timestamp": "2026-08-04T10:30:00.123Z",
  "event_id": "evt_abc123def456",
  "event_type": "api.inference_request",
  "severity": "info",
  "actor": {
    "id": "user_xyz789",
    "ip": "203.0.113.42",
    "user_agent": "AinosSDK/1.0.0 Python/3.12",
    "token_id": "tok_1234567890"
  },
  "resource": {
    "type": "model",
    "id": "ainos-llama-3.1-8b",
    "action": "infer"
  },
  "request": {
    "method": "POST",
    "path": "/api/inference",
    "params": {
      "max_tokens": 1024,
      "temperature": 0.7
    }
  },
  "response": {
    "status": 200,
    "duration_ms": 1234,
    "tokens_generated": 150
  },
  "security": {
    "auth_method": "bearer_token",
    "rate_limit_remaining": 45,
    "tls_version": "TLSv1.3",
    "country": "CN"
  },
  "metadata": {
    "environment": "production",
    "region": "us-east-1",
    "host": "ainos-api-1"
  }
}
```

### Audit Log Implementation

```python
# D:/Ainos/system-services/web-panel/audit.py
# Audit Logging Implementation
# ==============================

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

class AuditLogger:
    """
    Secure audit logging for security-relevant events.
    """
    
    def __init__(self, log_file: str = "/var/log/ainos/audit.log"):
        self.log_file = log_file
        self._logger = logging.getLogger("ainos.audit")
        self._setup_logger()
    
    def _setup_logger(self):
        handler = logging.handlers.RotatingFileHandler(
            self.log_file,
            maxBytes=100 * 1024 * 1024,  # 100MB
            backupCount=10,
        )
        formatter = logging.Formatter(
            '%(message)s'
        )
        handler.setFormatter(formatter)
        self._logger.addHandler(handler)
        self._logger.setLevel(logging.INFO)
    
    def log(
        self,
        event_type: str,
        severity: str = "info",
        actor: Optional[Dict] = None,
        resource: Optional[Dict] = None,
        request: Optional[Dict] = None,
        response: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
    ):
        """Log an audit event."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_id": uuid.uuid4().hex,
            "event_type": event_type,
            "severity": severity,
            "actor": actor or {},
            "resource": resource or {},
            "request": self._mask_sensitive(request or {}),
            "response": response or {},
            "metadata": metadata or {},
        }
        
        self._logger.info(json.dumps(entry, default=str))
        
        # Also log to system log for critical events
        if severity in ("critical", "alert"):
            logging.getLogger("ainos").critical(
                f"Audit: {event_type} - {actor.get('id', 'unknown')}"
            )
    
    def _mask_sensitive(self, data: Dict) -> Dict:
        """Mask sensitive fields in audit logs."""
        sensitive_fields = {"password", "token", "secret", "api_key", "authorization"}
        masked = {}
        for key, value in data.items():
            if key.lower() in sensitive_fields:
                masked[key] = "********"
            elif isinstance(value, dict):
                masked[key] = self._mask_sensitive(value)
            else:
                masked[key] = value
        return masked
    
    # Convenience methods
    def log_auth(self, success: bool, actor: Dict, details: Dict = None):
        """Log authentication event."""
        self.log(
            event_type="authentication.login_success" if success else "authentication.login_failure",
            severity="info" if success else "warning",
            actor=actor,
            metadata=details,
        )
    
    def log_api_call(self, request: Dict, response: Dict, actor: Dict):
        """Log API call."""
        self.log(
            event_type=f"api.{request.get('path', '').replace('/', '.')}",
            severity="info" if response.get("status", 500) < 400 else "warning",
            actor=actor,
            request=request,
            response=response,
        )
    
    def log_security_event(self, event: str, actor: Dict, details: Dict = None):
        """Log security event."""
        self.log(
            event_type=f"security.{event}",
            severity="warning",
            actor=actor,
            metadata=details,
        )
```

---

## 6. Firewall Rules / 防火墙规则

### iptables Rules

```bash
#!/bin/bash
# D:/Ainos/scripts/setup-firewall.sh
# AinosOS Firewall Configuration
# ================================

set -euo pipefail

echo "Configuring AinosOS firewall rules..."

# Flush existing rules
iptables -F
iptables -X
iptables -t nat -F
iptables -t mangle -F

# Default policies
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT ACCEPT

# Allow loopback
iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT

# Allow established connections
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Rate limit ICMP
iptables -A INPUT -p icmp --icmp-type echo-request -m limit --limit 1/s -j ACCEPT
iptables -A INPUT -p icmp --icmp-type echo-request -j DROP

# SSH (restrict to management network)
iptables -A INPUT -p tcp --dport 22 -s 10.0.0.0/8 -j ACCEPT
iptables -A INPUT -p tcp --dport 22 -s 172.16.0.0/12 -j ACCEPT

# HTTP/HTTPS for API
iptables -A INPUT -p tcp --dport 80 -j ACCEPT
iptables -A INPUT -p tcp --dport 443 -j ACCEPT

# API server port
iptables -A INPUT -p tcp --dport 8080 -s 10.0.0.0/8 -j ACCEPT
iptables -A INPUT -p tcp --dport 8080 -s 172.16.0.0/12 -j ACCEPT

# Metrics (internal only)
iptables -A INPUT -p tcp --dport 9090 -s 127.0.0.1 -j ACCEPT
iptables -A INPUT -p tcp --dport 9090 -s 10.0.0.0/8 -j ACCEPT

# Redis (internal only)
iptables -A INPUT -p tcp --dport 6379 -s 10.0.0.0/8 -j ACCEPT

# PostgreSQL (internal only)
iptables -A INPUT -p tcp --dport 5432 -s 10.0.0.0/8 -j ACCEPT

# Drop invalid packets
iptables -A INPUT -m state --state INVALID -j DROP

# Rate limit NEW connections
iptables -A INPUT -p tcp --syn -m connlimit --connlimit-above 100 -j REJECT

# Log dropped packets (rate limited)
iptables -A INPUT -m limit --limit 5/min -j LOG --log-prefix "AinosFW-DROP: " --log-level 7

# Save rules
iptables-save > /etc/iptables/rules.v4

echo "Firewall configured successfully"

# Show rules
iptables -L -n -v
```

### nftables Rules (Modern Alternative)

```bash
#!/bin/bash
# nftables Configuration
# =======================

cat > /etc/nftables.conf << 'EOF'
#!/usr/sbin/nft -f

flush ruleset

table inet ainos_filter {
    chain input {
        type filter hook input priority 0; policy drop;
        
        # Allow loopback
        iif lo accept
        
        # Allow established
        ct state established,related accept
        
        # Rate limit SSH
        tcp dport 22 ip saddr { 10.0.0.0/8, 172.16.0.0/12 } accept
        
        # HTTP/HTTPS
        tcp dport { 80, 443 } accept
        
        # API
        tcp dport 8080 ip saddr { 10.0.0.0/8, 172.16.0.0/12 } accept
        
        # Metrics
        tcp dport 9090 ip saddr { 127.0.0.1, 10.0.0.0/8 } accept
        
        # Rate limit connections
        tcp flags syn limit rate 100/second accept
        tcp flags syn counter drop
        
        # Log and drop
        log prefix "NFT-DROP: " limit rate 5/minute
        counter drop
    }
    
    chain forward {
        type filter hook forward priority 0; policy drop;
    }
    
    chain output {
        type filter hook output priority 0; policy accept;
    }
}

table inet ainos_rate_limit {
    chain input {
        type filter hook input priority -50;
        
        # Per-IP connection limit
        tcp dport 8080 meter web-meter { ip saddr ct count over 20 } reject
    }
}
EOF

nft -f /etc/nftables.conf
systemctl enable nftables
```

### Cloud Firewall (AWS Security Group)

```hcl
# D:/Ainos/terraform/security_group.tf
# AWS Security Group Configuration
# =================================

resource "aws_security_group" "ainos_api" {
  name        = "ainos-api-sg"
  description = "AinosOS API Server Security Group"
  vpc_id      = aws_vpc.main.id

  # HTTP/HTTPS from internet
  ingress {
    description = "HTTPS from internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP redirect"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # API from internal networks
  ingress {
    description = "API from internal"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = var.internal_cidr_blocks
  }

  # SSH from bastion
  ingress {
    description = "SSH from bastion"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [aws_instance.bastion.private_ip]
  }

  # Allow all outbound
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "ainos-api-sg"
    Environment = var.environment
  }
}
```

---

## 7. SELinux/AppArmor Profiles / SELinux/AppArmor 配置文件

### AppArmor Profile

```bash
# D:/Ainos/deploy/apparmor/ainos-api-profile
# ============================================
# AppArmor profile for AinosOS API server
# ============================================

#include <tunables/global>

profile ainos-api /opt/ainos/bin/api_server.py flags=(attach_disconnected) {
  #include <abstractions/base>
  #include <abstractions/python>
  #include <abstractions/ssl_certs>

  # Network
  network inet stream,
  network inet6 stream,
  network inet dgram,
  network inet6 dgram,

  # Capabilities
  capability setgid,
  capability setuid,
  capability net_bind_service,
  capability sys_resource,

  # Application directories
  /opt/ainos/** r,
  /opt/ainos/bin/api_server.py r,
  /opt/ainos/system-services/** r,
  /opt/ainos/models/** rw,

  # Log files
  /var/log/ainos/** rw,
  /var/log/ainos/audit.log rw,

  # Config files
  /etc/ainos/** r,
  /opt/ainos/config/** r,

  # SSL certificates
  /etc/ssl/** r,
  /opt/ainos/ssl/** r,

  # Temporary files
  /tmp/** rw,
  /var/tmp/** rw,

  # System
  /proc/@{pid}/** r,
  /sys/class/** r,
  /dev/nvidia* rw,
  /dev/shm/** rw,

  # Deny write to sensitive paths
  deny /etc/** w,
  deny /usr/** w,
  deny /bin/** w,
  deny /sbin/** w,
  deny /boot/** w,
  deny /sys/** w,
  deny /proc/** w,
}
```

### SELinux Policy

```bash
# D:/Ainos/deploy/selinux/ainos.te
# ==================================
# SELinux policy for AinosOS
# ==================================

policy_module(ainos, 1.0.0)

# Types
type ainos_t;
type ainos_exec_t;
type ainos_var_log_t;
type ainos_etc_t;
type ainos_model_t;

# File contexts
files_type(ainos_exec_t)
files_type(ainos_var_log_t)
files_type(ainos_etc_t)
files_type(ainos_model_t)

# Allow network access
corenet_tcp_connect_all_ports(ainos_t)
corenet_tcp_bind_all_ports(ainos_t)
corenet_udp_bind_all_ports(ainos_t)
corenet_sendrecv_all_packets(ainos_t)

# Allow process operations
domain_type(ainos_t)
domain_obj_id_change_exemption(ainos_t)
allow ainos_t self:capability { net_bind_service sys_resource };
allow ainos_t self:process signal;

# Allow file operations
allow ainos_t ainos_exec_t:file execute;
allow ainos_t ainos_var_log_t:dir { create read write };
allow ainos_t ainos_var_log_t:file { create read write append };
allow ainos_t ainos_etc_t:dir { read search };
allow ainos_t ainos_etc_t:file read;
allow ainos_t ainos_model_t:dir { read search };
allow ainos_t ainos_model_t:file { read write };

# Allow GPU access
dev_read_sysfs(ainos_t)
allow ainos_t self:dev_nvidia_t:chr_file { read write };

# Allow logging
logging_log_filetrans(ainos_t, ainos_var_log_t, dir, "ainos")
```

### Applying Profiles

```bash
# AppArmor
sudo cp deploy/apparmor/ainos-api-profile /etc/apparmor.d/
sudo apparmor_parser -r /etc/apparmor.d/ainos-api-profile
sudo aa-enforce ainos-api

# Verify
sudo aa-status | grep ainos

# SELinux
sudo checkmodule -M -m -o ainos.mod ainos.te
sudo semodule_package -o ainos.pp -m ainos.mod
sudo semodule -i ainos.pp

# Verify
sudo sesearch --all | grep ainos
```

---

## 8. Container Security / 容器安全

### Docker Security Configuration

```dockerfile
# Secure Dockerfile
FROM python:3.12-slim AS builder

# Stage 1: Build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Stage 2: Runtime
FROM gcr.io/distroless/python3-debian12

# Labels
LABEL maintainer="AinosOS Team <security@ainos.ai>"
LABEL security.ainos.compliance="pci-dss,hipaa,soc2"

# Non-root user
USER 1000:1000

# Read-only root filesystem
COPY --chown=1000:1000 --from=builder /app /app
WORKDIR /app

# Drop capabilities
COPY --chown=1000:1000 --from=builder /usr/bin/python3 /usr/bin/python3

# Security options
ENTRYPOINT ["python3", "-u", "api_server.py"]
```

### Docker Compose Security

```yaml
# Docker Compose with security options
version: "3.8"

services:
  ainos-api:
    image: ainosos/api-server:1.0.0
    security_opt:
      - no-new-privileges:true
      - seccomp:deploy/seccomp/ainos.json
      - apparmor:ainos-api
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
      - SYS_RESOURCE
    read_only: true
    tmpfs:
      - /tmp:size=100M
      - /var/run:size=50M
    volumes:
      - ainos-models:/opt/ainos/models
      - ainos-logs:/var/log/ainos
      - type: volume
        source: ainos-data
        target: /opt/ainos/data
        volume:
          nocopy: true
    user: "1000:1000"
    deploy:
      resources:
        limits:
          memory: 32G
          cpus: "8"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/api/status"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
```

### Container Security Scanning

```bash
#!/bin/bash
# D:/Ainos/scripts/scan-container.sh
# Container Security Scanning
# =============================

IMAGE="ainos/api-server:1.0.0"

echo "Scanning ${IMAGE}..."

# Trivy scan
trivy image --severity HIGH,CRITICAL --exit-code 1 ${IMAGE}

# Docker scan
docker scout quickview ${IMAGE}
docker scout recommendations ${IMAGE}

# Grype scan
grype ${IMAGE} --fail-on=high

# Check for secrets
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
    aquasec/trivy image --severity CRITICAL --exit-code 1 \
    ${IMAGE}

# Generate SBOM
docker buildx imagetools inspect ${IMAGE} --format "{{.Manifest.Digest}}"
syft ${IMAGE} -o spdx-json > sbom.json

echo "Scan complete"
```

### Kubernetes Pod Security

```yaml
# Pod Security Standards
apiVersion: v1
kind: Pod
metadata:
  name: ainos-api
  labels:
    app: ainos
    pod-security.kubernetes.io/enforce: restricted
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
    seccompProfile:
      type: RuntimeDefault
    supplementalGroups: [1000]
  containers:
    - name: ainos-api
      image: ainosos/api-server:1.0.0
      securityContext:
        allowPrivilegeEscalation: false
        privileged: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
          add: ["NET_BIND_SERVICE"]
        seLinuxOptions:
          level: "s0:c123,c456"
      resources:
        limits:
          memory: "32Gi"
          cpu: "8"
          nvidia.com/gpu: 1
```

---

## 9. Secrets Management / 密钥管理

### HashiCorp Vault Integration

```python
# D:/Ainos/system-services/web-panel/vault_client.py
# Vault Integration for Secrets Management
# ===========================================

import hvac
from typing import Any, Dict, Optional

class VaultClient:
    """
    HashiCorp Vault client for secrets management.
    """
    
    def __init__(self, vault_addr: str, vault_token: str):
        self.client = hvac.Client(
            url=vault_addr,
            token=vault_token,
        )
    
    def get_secret(self, path: str, key: Optional[str] = None) -> Any:
        """Get a secret from Vault."""
        try:
            secret = self.client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point="ainos",
            )
            data = secret["data"]["data"]
            return data.get(key) if key else data
        except Exception as e:
            raise RuntimeError(f"Failed to get secret: {e}")
    
    def set_secret(self, path: str, data: Dict):
        """Store a secret in Vault."""
        self.client.secrets.kv.v2.create_or_update_secret(
            path=path,
            secret=data,
            mount_point="ainos",
        )
    
    def rotate_secret(self, path: str, key: str) -> str:
        """Rotate a secret value."""
        import secrets
        new_value = secrets.token_hex(32)
        current = self.get_secret(path) or {}
        current[key] = new_value
        self.set_secret(path, current)
        return new_value


# Example usage
vault = VaultClient(
    vault_addr=os.environ["VAULT_ADDR"],
    vault_token=os.environ["VAULT_TOKEN"],
)

# Get API token
api_token = vault.get_secret("api-server", "api-token")

# Rotate database password
new_db_password = vault.rotate_secret("database", "password")
```

### Kubernetes External Secrets

```yaml
# External Secrets Operator configuration
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: ainos-secrets
  namespace: ainos
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: ainos-secrets
    creationPolicy: Owner
  data:
    - secretKey: api-token
      remoteRef:
        key: ainos/api-server
        property: api-token
    - secretKey: redis-password
      remoteRef:
        key: ainos/redis
        property: password
    - secretKey: db-password
      remoteRef:
        key: ainos/database
        property: password
```

### Secrets Rotation Policy

```yaml
# D:/Ainos/config/secrets/rotation.yaml
# Secrets Rotation Policy
# =========================

rotation:
  policies:
    - name: api-token
      type: token
      rotation_period: 90d
      length: 64
      algorithm: sha256
      notification_days: 7
    
    - name: database-password
      type: password
      rotation_period: 180d
      length: 32
      complexity: high
      notification_days: 14
    
    - name: redis-password
      type: password
      rotation_period: 180d
      length: 32
      complexity: high
      notification_days: 14
    
    - name: ssl-certificate
      type: certificate
      rotation_period: 365d
      notification_days: 30
  
  # Rotation window (maintenance window)
  maintenance_window:
    day: sunday
    time: "03:00"
    timezone: UTC
```

---

## 10. Security Checklist / 安全检查清单

### Pre-Deployment Checklist

```markdown
# AinosOS Pre-Deployment Security Checklist
# ==========================================

## Authentication and Authorization
- [ ] API token generated with sufficient entropy (min 32 bytes)
- [ ] Token-based authentication enabled in production
- [ ] Rate limiting configured for all endpoints
- [ ] MFA configured for admin access
- [ ] OAuth2/OIDC configured (if using SSO)
- [ ] Role-based access control implemented

## Network Security
- [ ] Firewall rules applied (iptables/nftables)
- [ ] Only necessary ports exposed (80, 443)
- [ ] Internal services not exposed to internet
- [ ] TLS/SSL certificates installed and valid
- [ ] HSTS headers configured
- [ ] DDoS protection enabled (Cloudflare/AWS Shield)

## Container Security
- [ ] Container runs as non-root user
- [ ] Read-only root filesystem
- [ ] All capabilities dropped except necessary
- [ ] Seccomp profile applied
- [ ] AppArmor/SELinux profile applied
- [ ] Container images scanned for vulnerabilities
- [ ] No sensitive data in image layers
- [ ] Image signing verified

## Data Security
- [ ] Data encryption at rest
- [ ] Data encryption in transit (TLS 1.2+)
- [ ] Secrets stored in vault, not in config files
- [ ] Database encrypted (TDE)
- [ ] Backup encryption enabled
- [ ] PII data masking configured
- [ ] Data retention policies implemented

## Logging and Monitoring
- [ ] Audit logging enabled
- [ ] Logs forwarded to SIEM
- [ ] Security alerts configured
- [ ] Intrusion detection enabled
- [ ] File integrity monitoring configured
- [ ] Regular log review scheduled

## Compliance
- [ ] GDPR compliance measures implemented
- [ ] SOC 2 controls verified
- [ ] HIPAA compliance (if applicable)
- [ ] PCI DSS compliance (if processing payments)
- [ ] Data residency requirements met
- [ ] Privacy policy published

## Operational Security
- [ ] Backup and disaster recovery tested
- [ ] Incident response plan documented
- [ ] Security contacts defined
- [ ] Vulnerability scanning scheduled
- [ ] Penetration testing completed
- [ ] Security training for team members
```

### Daily Security Checks

```bash
#!/bin/bash
# D:/Ainos/scripts/daily-security-check.sh
# Daily Security Checks
# ======================

echo "=== AinosOS Daily Security Check ==="
echo "Date: $(date)"
echo ""

# 1. Check service status
echo "1. Service Status:"
for service in ainos-api nginx prometheus grafana; do
    if systemctl is-active --quiet $service; then
        echo "   [OK] $service is running"
    else
        echo "   [FAIL] $service is NOT running"
    fi
done

# 2. Check certificate expiry
echo ""
echo "2. Certificate Check:"
for domain in "api.ainos.ai:443" "dashboard.ainos.ai:443"; do
    expiry=$(echo | openssl s_client -connect $domain 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null)
    if [ -n "$expiry" ]; then
        echo "   [OK] $domain - $expiry"
    else
        echo "   [FAIL] Cannot check $domain"
    fi
done

# 3. Check failed auth attempts
echo ""
echo "3. Failed Authentication Attempts (last 24h):"
grep "auth_failure\|login_failure" /var/log/ainos/audit.log | awk '{print $1}' | sort | uniq -c | sort -rn | head -5

# 4. Check rate limit hits
echo ""
echo "4. Rate Limit Exceeded (last 24h):"
grep "429\|rate_limit" /var/log/nginx/access.log | wc -l

# 5. Check disk usage
echo ""
echo "5. Disk Usage:"
df -h /opt/ainos /var/log/ainos | tail -n +2

# 6. Check for suspicious IPs
echo ""
echo "6. Top IPs accessing API:"
tail -10000 /var/log/nginx/access.log | awk '{print $1}' | sort | uniq -c | sort -rn | head -10

# 7. Check Docker security
echo ""
echo "7. Docker Security:"
docker ps --quiet | xargs docker inspect --format '{{.Name}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.Privileged}}'

echo ""
echo "=== Security check completed ==="
```

---

## 11. Incident Response / 事件响应

### Incident Response Plan

```yaml
# D:/Ainos/config/security/incident-response.yaml
# Incident Response Plan
# =======================

plan:
  name: "AinosOS Security Incident Response Plan"
  version: "1.0.0"
  
  severity_levels:
    - name: "SEV-1 (Critical)"
      examples:
        - "Active data breach"
        - "Service outage affecting all users"
        - "Unauthorized access to model data"
      response_time: "15 minutes"
      escalation: "Full team + executives"
    
    - name: "SEV-2 (High)"
      examples:
        - "Suspicious access pattern detected"
        - "Rate limit bypass"
        - "Minor data exposure"
      response_time: "1 hour"
      escalation: "Security team + on-call"
    
    - name: "SEV-3 (Medium)"
      examples:
        - "Failed login attempts spike"
        - "Certificate about to expire"
        - "Suspicious API calls"
      response_time: "4 hours"
      escalation: "Security team during business hours"
    
    - name: "SEV-4 (Low)"
      examples:
        - "Single failed login"
        - "Minor config drift"
        - "Old dependency warning"
      response_time: "Next business day"
      escalation: "Track in issue tracker"
  
  response_phases:
    - phase: "Preparation"
      activities:
        - "Maintain incident response team"
        - "Regular drills and tabletop exercises"
        - "Keep runbooks updated"
        - "Ensure tools and access are available"
    
    - phase: "Detection & Analysis"
      activities:
        - "Identify incident type and severity"
        - "Gather initial evidence"
        - "Document timeline"
        - "Determine scope and impact"
    
    - phase: "Containment & Eradication"
      activities:
        - "Isolate affected systems"
        - "Block malicious IPs/tokens"
        - "Rotate compromised credentials"
        - "Apply security patches"
    
    - phase: "Recovery"
      activities:
        - "Restore from clean backup"
        - "Verify system integrity"
        - "Gradually restore services"
        - "Monitor for recurrence"
    
    - phase: "Post-Incident"
      activities:
        - "Conduct root cause analysis"
        - "Update security controls"
        - "Document lessons learned"
        - "Update incident response plan"
```

### Incident Response Runbook

```bash
# D:/Ainos/scripts/incident-response.sh
# Incident Response Runbook
# ==========================

set -euo pipefail

SEVERITY="${1:-SEV-3}"
INCIDENT_ID="inc-$(date +%Y%m%d-%H%M%S)-$(openssl rand -hex 4)"

echo "============================================"
echo "AinosOS Incident Response"
echo "Incident ID: ${INCIDENT_ID}"
echo "Severity: ${SEVERITY}"
echo "Timestamp: $(date -u)"
echo "============================================"

# 1. Create incident channel
echo "[1/8] Creating incident channel..."
INCIDENT_LOG="/var/log/ainos/incidents/${INCIDENT_ID}.log"
mkdir -p /var/log/ainos/incidents/
exec > >(tee -a "${INCIDENT_LOG}") 2>&1

# 2. Gather initial information
echo "[2/8] Gathering incident information..."
echo "  - Service status: $(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/api/status)"
echo "  - Active connections: $(ss -tnp | grep 8080 | wc -l)"
echo "  - Recent errors: $(tail -50 /var/log/ainos/ainos.log | grep -c ERROR)"

# 3. Collect forensic data
echo "[3/8] Collecting forensic data..."
tar czf "/tmp/forensics-${INCIDENT_ID}.tar.gz" \
    /var/log/ainos/ \
    /var/log/nginx/access.log \
    /var/log/nginx/error.log \
    /opt/ainos/config/ \
    2>/dev/null || true

# 4. Isolate affected systems
echo "[4/8] Isolating affected systems..."
if [ "${SEVERITY}" = "SEV-1" ] || [ "${SEVERITY}" = "SEV-2" ]; then
    # Block all non-essential traffic
    iptables -A INPUT -p tcp --dport 8080 -j DROP
    echo "  - API port blocked"
fi

# 5. Rotate credentials
echo "[5/8] Rotating credentials..."
if [ "${SEVERITY}" = "SEV-1" ]; then
    # Rotate all tokens
    ./scripts/rotate-api-token.sh
    echo "  - API token rotated"
fi

# 6. Notify team
echo "[6/8] Notifying incident response team..."
# Slack notification
curl -s -X POST "${SLACK_WEBHOOK}" \
    -H "Content-Type: application/json" \
    -d "{
        \"text\": \"[${SEVERITY}] Incident ${INCIDENT_ID} in progress\",
        \"attachments\": [{
            \"fields\": [
                {\"title\": \"Severity\", \"value\": \"${SEVERITY}\", \"short\": true},
                {\"title\": \"Service\", \"value\": \"AinosOS API\", \"short\": true},
                {\"title\": \"Time\", \"value\": \"$(date -u)\", \"short\": true}
            ]
        }]
    }" 2>/dev/null || true

# 7. Document findings
echo "[7/8] Documenting incident..."
echo "Finding: Initial incident assessment" >> "${INCIDENT_LOG}"
echo "Actions taken:" >> "${INCIDENT_LOG}"
echo "  1. Incident logged" >> "${INCIDENT_LOG}"
echo "  2. Forensics collected" >> "${INCIDENT_LOG}"
echo "  3. Credentials rotated" >> "${INCIDENT_LOG}"

# 8. Continuous monitoring
echo "[8/8] Activating enhanced monitoring..."
# Increase monitoring frequency
# Add temporary alert rules

echo ""
echo "============================================"
echo "Incident response initiated: ${INCIDENT_ID}"
echo "Log: ${INCIDENT_LOG}"
echo "============================================"
```

---

## 12. Vulnerability Management / 漏洞管理

### Vulnerability Scanning

```bash
#!/bin/bash
# D:/Ainos/scripts/vulnerability-scan.sh
# Regular Vulnerability Scanning
# ===============================

echo "Starting vulnerability scan..."
DATE=$(date +%Y%m%d)
REPORT_DIR="/var/reports/security"

mkdir -p ${REPORT_DIR}

# 1. Scan Python dependencies
echo "1. Scanning Python dependencies..."
pip-audit --requirement requirements.txt \
    --format json \
    --output ${REPORT_DIR}/pip-audit-${DATE}.json

# 2. Scan Docker images
echo "2. Scanning Docker images..."
trivy image --severity HIGH,CRITICAL \
    --format json \
    --output ${REPORT_DIR}/trivy-${DATE}.json \
    ainosos/api-server:latest

# 3. Scan file system
echo "3. Scanning file system..."
clamscan -r /opt/ainos \
    --exclude-dir=/opt/ainos/models \
    --log=${REPORT_DIR}/clamav-${DATE}.log

# 4. Check for exposed secrets
echo "4. Scanning for secrets..."
trufflehog filesystem /opt/ainos \
    --json > ${REPORT_DIR}/trufflehog-${DATE}.json 2>/dev/null || true

# 5. Check for known CVEs
echo "5. Checking for CVEs..."
grype /opt/ainos \
    --fail-on medium \
    --output json \
    > ${REPORT_DIR}/grype-${DATE}.json 2>/dev/null || true

# 6. Generate summary
echo "6. Generating summary..."
python3 << 'PYEOF'
import json
import os

date = "${DATE}"
report_dir = "var/reports/security"

summary = {
    "date": date,
    "total_vulnerabilities": 0,
    "critical": 0,
    "high": 0,
    "medium": 0,
    "low": 0,
}

# Parse trivy results
try:
    with open(f"${report_dir}/trivy-{date}.json") as f:
        data = json.load(f)
        for result in data.get("Results", []):
            for vuln in result.get("Vulnerabilities", []):
                severity = vuln.get("Severity", "").upper()
                if severity == "CRITICAL": summary["critical"] += 1
                elif severity == "HIGH": summary["high"] += 1
                elif severity == "MEDIUM": summary["medium"] += 1
                elif severity == "LOW": summary["low"] += 1
                summary["total_vulnerabilities"] += 1
except:
    pass

print(json.dumps(summary, indent=2))
PYEOF

echo "Vulnerability scan completed"
```

### Dependency Security

```bash
# requirements.txt with pinned versions
# All dependencies should be pinned to specific versions
aiohttp==3.9.5
aiohttp-cors==0.7.0
aiohttp-sse==2.0.0
psutil==5.9.8
uvloop==0.19.0
hvac==2.1.0
redis==5.0.7
cryptography==42.0.5
pyjwt==2.8.0
python-dotenv==1.0.1
```

### Security Updates Process

```bash
#!/bin/bash
# D:/Ainos/scripts/security-update.sh
# Security Update Process
# =========================

set -euo pipefail

echo "Starting security update process..."

# 1. Create branch
BRANCH="security/update-$(date +%Y%m%d)"
git checkout -b ${BRANCH}

# 2. Update dependencies
echo "Updating dependencies..."
pip install --upgrade pip-tools
pip-compile --upgrade requirements.in
pip-compile --upgrade requirements-dev.in

# 3. Run tests
echo "Running tests..."
python -m pytest tests/ -v
python -m pytest tests/security/ -v

# 4. Run security scan
echo "Running security scan..."
pip-audit -r requirements.txt

# 5. Commit and push
git add requirements.txt requirements-dev.txt
git commit -m "security: update dependencies $(date +%Y-%m-%d)"
git push origin ${BRANCH}

# 6. Create PR
gh pr create \
    --title "Security: Update dependencies $(date +%Y-%m-%d)" \
    --body "Regular security dependency update.\n\nChanges:\n- Updated all dependencies to latest versions\n- Ran security audit\n- All tests passing" \
    --label "security"

echo "Security update PR created: ${BRANCH}"
```

---

## Quick Reference / 快速参考

### Common Security Commands

```bash
# Generate secure token
openssl rand -hex 32
python3 -c "import secrets; print(secrets.token_hex(32))"

# Hash a password
python3 -c "import hashlib; print(hashlib.sha256(b'password').hexdigest())"

# Check TLS certificate
echo | openssl s_client -connect api.ainos.ai:443 -servername api.ainos.ai 2>/dev/null | openssl x509 -noout -dates

# Scan container for vulnerabilities
docker scout quickview ainosos/api-server:latest
trivy image ainosos/api-server:latest

# Check open ports
ss -tlnp
netstat -tulpn

# Check firewall rules
iptables -L -n -v
nft list ruleset

# Monitor auth attempts
tail -f /var/log/ainos/audit.log | grep -E "auth|login|token"

# Check for suspicious processes
ps aux --sort=-%mem | head -20
lsof -i :8080
```

### Security Contacts

| Role | Contact | Response Time |
|------|---------|---------------|
| Security Lead | security@ainos.ai | 15 minutes |
| On-Call Engineer | oncall@ainos.ai | 30 minutes |
| DevSecOps | devsecops@ainos.ai | 1 hour |
| Compliance | compliance@ainos.ai | 4 hours |

---

*For security issues, please contact security@ainos.ai. For more information, visit [https://docs.ainos.ai/security](https://docs.ainos.ai/security).*

*如有安全问题，请联系 security@ainos.ai。更多信息请访问 [https://docs.ainos.ai/security](https://docs.ainos.ai/security)。*