# AinosOS Deployment Guide / 部署指南

> **Version:** 1.0.0 | **Updated:** 2026-08-04
>
> This guide covers production deployment of AinosOS inference platform.
> 本指南涵盖 AinosOS 推理平台的生产环境部署。

---

## Table of Contents / 目录

1. [Prerequisites / 前提条件](#1-prerequisites)
2. [Docker Deployment / Docker 部署](#2-docker-deployment)
3. [Kubernetes Deployment / Kubernetes 部署](#3-kubernetes-deployment)
4. [Configuration Management / 配置管理](#4-configuration-management)
5. [Monitoring / 监控](#5-monitoring)
6. [Backup and Recovery / 备份与恢复](#6-backup-and-recovery)
7. [Scaling / 扩展](#7-scaling)
8. [High Availability / 高可用性](#8-high-availability)
9. [Disaster Recovery / 灾难恢复](#9-disaster-recovery)
10. [Security Hardening / 安全加固](#10-security-hardening)
11. [Performance Tuning / 性能调优](#11-performance-tuning)
12. [Troubleshooting / 故障排除](#12-troubleshooting)

---

## 1. Prerequisites / 前提条件

### System Requirements / 系统要求

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 4 cores | 16+ cores |
| RAM | 16 GB | 64+ GB |
| GPU | NVIDIA T4 (16GB) | NVIDIA A100 (80GB) |
| Disk | 50 GB SSD | 500 GB NVMe |
| OS | Ubuntu 22.04 | Ubuntu 24.04 LTS |
| Docker | 24.0+ | 26.0+ |
| Python | 3.12+ | 3.12+ |
| CUDA | 12.1+ | 12.4+ |

### Software Dependencies / 软件依赖

```bash
# System packages
sudo apt-get update && sudo apt-get install -y \
    build-essential \
    curl \
    git \
    nvidia-driver-550 \
    nvidia-container-toolkit \
    python3.12 \
    python3.12-venv \
    python3.12-dev

# NVIDIA Container Toolkit setup
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Python virtual environment
python3.12 -m venv /opt/ainos/venv
source /opt/ainos/venv/bin/activate
pip install --upgrade pip setuptools wheel
```

### Verify Installation / 验证安装

```bash
# Check CUDA
nvidia-smi
# Expected: CUDA Version: 12.4

# Check Docker
docker --version
# Expected: Docker version 26.0.0+

# Check NVIDIA Docker runtime
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

---

## 2. Docker Deployment / Docker 部署

### Dockerfile

```dockerfile
# D:/Ainos/deploy/Dockerfile
# ============================
# AinosOS Production Docker Image
# ============================

# Stage 1: Build stage
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime stage
FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04

LABEL maintainer="AinosOS Team <dev@ainos.ai>"
LABEL description="AinosOS Inference Platform"
LABEL version="1.0.0"

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3-pip \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r ainos && useradd -r -g ainos -m -d /opt/ainos ainos

# Set up application
WORKDIR /opt/ainos

# Copy Python dependencies from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=ainos:ainos system-services/ system-services/
COPY --chown=ainos:ainos config/ config/
COPY --chown=ainos:ainos entrypoint.sh .

RUN chmod +x entrypoint.sh

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AINOS_HOST=0.0.0.0 \
    AINOS_PORT=8080 \
    AINOS_LOG_LEVEL=INFO

# Expose ports
EXPOSE 8080 9090 9091

# Switch to non-root user
USER ainos

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/api/status || exit 1

ENTRYPOINT ["./entrypoint.sh"]
```

### docker-compose.yml

```yaml
# D:/Ainos/deploy/docker-compose.yml
# ====================================
# AinosOS Production Docker Compose
# ====================================

version: "3.8"

networks:
  ainos-net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16

volumes:
  ainos-data:
    driver: local
  ainos-models:
    driver: local
  ainos-logs:
    driver: local
  prometheus-data:
    driver: local
  grafana-data:
    driver: local

services:
  # ==========================================
  # AinosOS Main API Server
  # ==========================================
  ainos-api:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    image: ainosos/api-server:1.0.0
    container_name: ainos-api
    restart: unless-stopped
    networks:
      - ainos-net
    ports:
      - "8080:8080"   # API + Dashboard
      - "9090:9090"   # Metrics (if enabled)
    volumes:
      - ainos-models:/opt/ainos/models
      - ainos-logs:/var/log/ainos
      - ainos-data:/opt/ainos/data
      - ./config:/opt/ainos/config:ro
    environment:
      - AINOS_HOST=0.0.0.0
      - AINOS_PORT=8080
      - AINOS_LOG_LEVEL=INFO
      - AINOS_ENABLE_AUTH=true
      - AINOS_API_TOKEN=${AINOS_API_TOKEN:-changeme}
      - AINOS_CORS_ORIGINS=*
      - AINOS_MAX_LOG_ENTRIES=10000
      - CUDA_VISIBLE_DEVICES=0
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/api/status"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "5"

  # ==========================================
  # Prometheus Monitoring
  # ==========================================
  prometheus:
    image: prom/prometheus:v2.52.0
    container_name: ainos-prometheus
    restart: unless-stopped
    networks:
      - ainos-net
    ports:
      - "9091:9090"
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--storage.tsdb.retention.time=30d"
      - "--web.console.libraries=/usr/share/prometheus/console_libraries"
      - "--web.console.templates=/usr/share/prometheus/consoles"

  # ==========================================
  # Grafana Visualization
  # ==========================================
  grafana:
    image: grafana/grafana:11.0.0
    container_name: ainos-grafana
    restart: unless-stopped
    networks:
      - ainos-net
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana
      - ./grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
      - ./grafana/datasources:/etc/grafana/provisioning/datasources:ro
    environment:
      - GF_SECURITY_ADMIN_USER=${GRAFANA_ADMIN_USER:-admin}
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:-admin}
      - GF_INSTALL_PLUGINS=grafana-piechart-panel

  # ==========================================
  # Nginx Reverse Proxy (Optional)
  # ==========================================
  nginx:
    image: nginx:1.26-alpine
    container_name: ainos-nginx
    restart: unless-stopped
    networks:
      - ainos-net
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
      - ./nginx/htpasswd:/etc/nginx/htpasswd:ro
    depends_on:
      - ainos-api
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "3"
```

### Docker Compose Deployment Steps

```bash
# 1. Clone and prepare
git clone https://github.com/ainos-ai/ainos.git
cd ainos/deploy

# 2. Configure environment
cp .env.example .env
# Edit .env with your settings
nano .env

# 3. Create necessary directories
mkdir -p prometheus grafana/dashboards grafana/datasources nginx/ssl config

# 4. Start services
docker compose pull
docker compose up -d

# 5. Verify deployment
docker compose ps
docker compose logs ainos-api

# 6. Check health
curl http://localhost:8080/api/status

# 7. View logs
docker compose logs -f ainos-api
```

### Docker Management Commands

```bash
# Update services
docker compose pull
docker compose up -d --force-recreate

# Scale inference workers
docker compose up -d --scale ainos-inference=3

# Backup volumes
docker run --rm -v ainos-data:/data -v $(pwd)/backup:/backup \
    alpine tar czf /backup/ainos-data-$(date +%Y%m%d).tar.gz -C /data .

# Restore volumes
docker run --rm -v ainos-data:/data -v $(pwd)/backup:/backup \
    alpine tar xzf /backup/ainos-data-20260804.tar.gz -C /data

# Clean up old images
docker image prune -af --filter "until=168h"
```

---

## 3. Kubernetes Deployment / Kubernetes 部署

### deployment.yaml

```yaml
# D:/Ainos/deploy/k8s/deployment.yaml
# ====================================
# AinosOS Kubernetes Deployment
# ====================================

apiVersion: apps/v1
kind: Deployment
metadata:
  name: ainos-api
  namespace: ainos
  labels:
    app: ainos
    component: api
    version: "1.0.0"
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: ainos
      component: api
  template:
    metadata:
      labels:
        app: ainos
        component: api
        version: "1.0.0"
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9090"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: ainos-sa
      terminationGracePeriodSeconds: 60
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchExpressions:
                    - key: component
                      operator: In
                      values:
                        - api
                topologyKey: kubernetes.io/hostname
      containers:
        - name: ainos-api
          image: ainosos/api-server:1.0.0
          imagePullPolicy: Always
          ports:
            - containerPort: 8080
              name: http
            - containerPort: 9090
              name: metrics
          env:
            - name: AINOS_HOST
              value: "0.0.0.0"
            - name: AINOS_PORT
              value: "8080"
            - name: AINOS_LOG_LEVEL
              value: "INFO"
            - name: AINOS_ENABLE_AUTH
              value: "true"
            - name: AINOS_API_TOKEN
              valueFrom:
                secretKeyRef:
                  name: ainos-secrets
                  key: api-token
            - name: AINOS_CORS_ORIGINS
              value: "https://dashboard.ainos.ai"
            - name: CUDA_VISIBLE_DEVICES
              value: "0"
          resources:
            requests:
              memory: "4Gi"
              cpu: "2"
            limits:
              memory: "32Gi"
              cpu: "8"
              nvidia.com/gpu: 1
          livenessProbe:
            httpGet:
              path: /api/status
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 30
            timeoutSeconds: 10
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /api/status
              port: 8080
            initialDelaySeconds: 15
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 2
          volumeMounts:
            - name: models
              mountPath: /opt/ainos/models
            - name: logs
              mountPath: /var/log/ainos
            - name: data
              mountPath: /opt/ainos/data
            - name: config
              mountPath: /opt/ainos/config
              readOnly: true
      volumes:
        - name: models
          persistentVolumeClaim:
            claimName: ainos-models-pvc
        - name: logs
          emptyDir: {}
        - name: data
          persistentVolumeClaim:
            claimName: ainos-data-pvc
        - name: config
          configMap:
            name: ainos-config
```

### service.yaml

```yaml
# D:/Ainos/deploy/k8s/service.yaml
# ==================================
# AinosOS Kubernetes Service
# ==================================

---
# Internal service
apiVersion: v1
kind: Service
metadata:
  name: ainos-api
  namespace: ainos
  labels:
    app: ainos
    component: api
spec:
  type: ClusterIP
  ports:
    - name: http
      port: 8080
      targetPort: 8080
    - name: metrics
      port: 9090
      targetPort: 9090
  selector:
    app: ainos
    component: api

---
# Load balancer for external access
apiVersion: v1
kind: Service
metadata:
  name: ainos-api-lb
  namespace: ainos
  labels:
    app: ainos
    component: api
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
    service.beta.kubernetes.io/aws-load-balancer-ssl-cert: "arn:aws:acm:...:certificate/..."
    service.beta.kubernetes.io/aws-load-balancer-ssl-ports: "443"
spec:
  type: LoadBalancer
  ports:
    - name: https
      port: 443
      targetPort: 8080
  selector:
    app: ainos
    component: api
```

### ingress.yaml

```yaml
# D:/Ainos/deploy/k8s/ingress.yaml
# =================================
# AinosOS Kubernetes Ingress
# =================================

apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ainos-ingress
  namespace: ainos
  annotations:
    kubernetes.io/ingress.class: "nginx"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/proxy-body-size: "100m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  tls:
    - hosts:
        - api.ainos.ai
        - dashboard.ainos.ai
      secretName: ainos-tls
  rules:
    - host: api.ainos.ai
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: ainos-api
                port:
                  number: 8080
    - host: dashboard.ainos.ai
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: ainos-api
                port:
                  number: 8080
```

### Kubernetes Deployment Commands

```bash
# Create namespace
kubectl create namespace ainos

# Deploy secrets
kubectl create secret generic ainos-secrets \
    --namespace ainos \
    --from-literal=api-token=$(openssl rand -hex 32)

# Deploy config
kubectl create configmap ainos-config \
    --namespace ainos \
    --from-file=../config/

# Deploy storage
kubectl apply -f pvc.yaml

# Deploy application
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
kubectl apply -f ingress.yaml

# Check deployment status
kubectl get all -n ainos
kubectl describe deployment ainos-api -n ainos
kubectl logs -n ainos -l app=ainos --tail=100

# Scale deployment
kubectl scale deployment ainos-api -n ainos --replicas=5

# Rolling update
kubectl set image deployment/ainos-api -n ainos \
    ainos-api=ainos/api-server:1.1.0

# Rollback
kubectl rollout undo deployment/ainos-api -n ainos

# Monitor resources
kubectl top pods -n ainos
kubectl top nodes
```

### Helm Chart (Coming Soon)

```bash
# Add repository
helm repo add ainos https://charts.ainos.ai

# Install
helm install ainos ainos/ainos \
    --namespace ainos \
    --create-namespace \
    --set api.replicas=3 \
    --set api.token=$(openssl rand -hex 32) \
    --set ingress.enabled=true \
    --set ingress.hostname=api.ainos.ai

# Upgrade
helm upgrade ainos ainos/ainos \
    --set api.image.tag=1.1.0

# Uninstall
helm uninstall ainos -n ainos
```

---

## 4. Configuration Management / 配置管理

### Environment Variables / 环境变量

```bash
# D:/Ainos/deploy/.env.example
# =============================
# AinosOS Configuration
# =============================

# Server
AINOS_HOST=0.0.0.0
AINOS_PORT=8080
AINOS_LOG_LEVEL=INFO

# Authentication
AINOS_ENABLE_AUTH=true
AINOS_API_TOKEN=your-secure-token-here

# CORS
AINOS_CORS_ORIGINS=https://dashboard.ainos.ai,https://app.ainos.ai

# Model Configuration
AINOS_MODEL_DIR=/opt/ainos/models
AINOS_DEFAULT_MODEL=ainos-llama-3.1-8b
AINOS_MAX_MODEL_LOAD=4

# Inference
AINOS_MAX_TOKENS=8192
AINOS_DEFAULT_TEMPERATURE=0.7
AINOS_MAX_CONCURRENT_REQUESTS=16
AINOS_REQUEST_TIMEOUT=300

# Memory
AINOS_MAX_LOG_ENTRIES=10000
AINOS_CONTEXT_TTL=3600

# GPU
CUDA_VISIBLE_DEVICES=0,1
AINOS_GPU_MEMORY_FRACTION=0.9

# Monitoring
AINOS_ENABLE_METRICS=true
AINOS_METRICS_PORT=9090
```

### Configuration File (YAML)

```yaml
# D:/Ainos/config/ainos.yaml
# ==========================
# AinosOS YAML Configuration
# ==========================

server:
  host: "0.0.0.0"
  port: 8080
  workers: 4
  backlog: 1024
  graceful_shutdown_timeout: 30

auth:
  enabled: true
  token: ${AINOS_API_TOKEN}
  rate_limit: 100  # requests per minute per IP

models:
  directory: /opt/ainos/models
  default: ainos-llama-3.1-8b
  max_loaded: 4
  supported:
    - id: ainos-llama-3.1-8b
      name: "Ainos Llama 3.1 8B"
      provider: llama.cpp
      parameters:
        context_length: 8192
        gpu_layers: 32
    - id: ainos-qwen-2.5-7b
      name: "Ainos Qwen 2.5 7B"
      provider: vllm
      parameters:
        context_length: 32768
        tensor_parallel: 1
  preload: []
  download:
    base_url: "https://models.ainos.ai/v1/"
    retry_attempts: 3
    timeout: 3600

inference:
  max_tokens: 8192
  default_temperature: 0.7
  top_p: 0.9
  top_k: 40
  repetition_penalty: 1.1
  max_concurrent: 16
  timeout: 300
  streaming:
    enabled: true
    chunk_size: 1
    max_queue_size: 128

logging:
  level: INFO
  format: "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
  file: /var/log/ainos/ainos.log
  max_size: 100MB
  backups: 5
  json_format: true

monitoring:
  enabled: true
  metrics_port: 9090
  prometheus:
    enabled: true
    path: /metrics
  sentry:
    enabled: false
    dsn: ""

context:
  ttl: 3600
  max_entries: 10000
  storage: memory  # memory | redis
  redis:
    host: localhost
    port: 6379
    db: 0
    password: ""

plugins:
  directory: /opt/ainos/plugins
  auto_load: true
  blacklist: []
```

### Config Management Best Practices

```bash
# 1. Use environment-specific configs
cp config/ainos.yaml config/ainos.production.yaml
cp config/ainos.yaml config/ainos.staging.yaml

# 2. Validate config before applying
python scripts/validate_config.py config/ainos.yaml

# 3. Encrypt sensitive values
# Using sops
sops --encrypt config/secrets.yaml > config/secrets.enc.yaml
sops --decrypt config/secrets.enc.yaml > config/secrets.yaml

# 4. Version control for configs
git add config/
git commit -m "chore: update production config"
```

---

## 5. Monitoring / 监控

### Prometheus Configuration

```yaml
# D:/Ainos/deploy/prometheus/prometheus.yml
# =========================================
# Prometheus Configuration
# =========================================

global:
  scrape_interval: 15s
  evaluation_interval: 15s
  scrape_timeout: 10s

alerting:
  alertmanagers:
    - static_configs:
        - targets:
          # - alertmanager:9093

rule_files:
  - "alerts.yml"

scrape_configs:
  - job_name: "ainos-api"
    metrics_path: /metrics
    static_configs:
      - targets:
          - "ainos-api:9090"
        labels:
          service: "ainos-api"
          environment: "production"

  - job_name: "node"
    static_configs:
      - targets:
          - "node-exporter:9100"

  - job_name: "docker"
    static_configs:
      - targets:
          - "cadvisor:8080"
```

### Prometheus Alert Rules

```yaml
# D:/Ainos/deploy/prometheus/alerts.yml
# =====================================
# Prometheus Alert Rules
# =====================================

groups:
  - name: ainos-alerts
    interval: 30s
    rules:
      - alert: HighCPUUsage
        expr: avg(rate(process_cpu_seconds_total[5m])) * 100 > 90
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage on {{ $labels.instance }}"
          description: "CPU usage is above 90% for 5 minutes"

      - alert: HighMemoryUsage
        expr: (process_resident_memory_bytes / 1073741824) > 28
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage on {{ $labels.instance }}"
          description: "Memory usage is above 28GB"

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(request_duration_seconds_bucket[5m])) > 5
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High p95 latency on {{ $labels.instance }}"
          description: "p95 latency is above 5 seconds"

      - alert: ErrorRateHigh
        expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate on {{ $labels.instance }}"
          description: "Error rate is above 5%"

      - alert: ServiceDown
        expr: up{job="ainos-api"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Service {{ $labels.instance }} is down"
          description: "Service has been down for over 1 minute"

      - alert: ModelUnloaded
        expr: ainos_loaded_models < 1
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "No models loaded"
          description: "All models have been unloaded"

      - alert: GPUHighTemperature
        expr: nvidia_gpu_temperature_celsius > 85
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "GPU temperature high"
          description: "GPU temperature is above 85C"

      - alert: DiskSpaceLow
        expr: (node_filesystem_avail_bytes / node_filesystem_size_bytes) * 100 < 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Low disk space on {{ $labels.instance }}"
          description: "Disk space is below 10%"
```

### Grafana Dashboard

```json
{
  "D:/Ainos/deploy/grafana/dashboards/ainos-overview.json": {
    "title": "AinosOS Overview",
    "panels": [
      {
        "title": "API Request Rate",
        "type": "graph",
        "targets": [{"expr": "rate(http_requests_total[5m])"}]
      },
      {
        "title": "Latency (p50/p95/p99)",
        "type": "graph",
        "targets": [
          {"expr": "histogram_quantile(0.50, rate(request_duration_seconds_bucket[5m]))"},
          {"expr": "histogram_quantile(0.95, rate(request_duration_seconds_bucket[5m]))"},
          {"expr": "histogram_quantile(0.99, rate(request_duration_seconds_bucket[5m]))"}
        ]
      },
      {
        "title": "GPU Utilization",
        "type": "gauge",
        "targets": [{"expr": "nvidia_gpu_utilization"}]
      },
      {
        "title": "Active Models",
        "type": "stat",
        "targets": [{"expr": "ainos_loaded_models"}]
      }
    ]
  }
}
```

### Grafana Datasource Config

```yaml
# D:/Ainos/deploy/grafana/datasources/datasource.yml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

---

## 6. Backup and Recovery / 备份与恢复

### Backup Strategy

```bash
#!/bin/bash
# D:/Ainos/scripts/backup.sh
# AinosOS Backup Script
# =======================

set -euo pipefail

BACKUP_DIR="/backup/ainos"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

echo "[$(date)] Starting AinosOS backup..."

# Create backup directory
mkdir -p "${BACKUP_DIR}/${DATE}"

# 1. Backup configuration
echo "Backing up configuration..."
tar czf "${BACKUP_DIR}/${DATE}/config.tar.gz" -C /opt/ainos config/

# 2. Backup models (skip if using Git LFS)
echo "Backing up model metadata..."
find /opt/ainos/models -name "*.json" -exec tar czf "${BACKUP_DIR}/${DATE}/models-metadata.tar.gz" {} +

# 3. Backup context data
echo "Backing up context data..."
# API call to export context
curl -s -X GET "http://localhost:8080/api/context" \
    -H "Authorization: Bearer ${AINOS_API_TOKEN}" \
    -o "${BACKUP_DIR}/${DATE}/context.json"

# 4. Backup logs
echo "Backing up logs..."
tar czf "${BACKUP_DIR}/${DATE}/logs.tar.gz" -C /var/log/ainos .

# 5. Backup database (if using persistent storage)
echo "Backing up database..."
# pg_dump -h localhost -U ainos ainos > "${BACKUP_DIR}/${DATE}/database.sql"

# 6. Create backup manifest
cat > "${BACKUP_DIR}/${DATE}/manifest.json" << EOF
{
  "backup_date": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "version": "1.0.0",
  "contents": [
    "config.tar.gz",
    "models-metadata.tar.gz",
    "context.json",
    "logs.tar.gz"
  ],
  "checksums": {}
}
EOF

# Generate checksums
for f in "${BACKUP_DIR}/${DATE}"/*.tar.gz "${BACKUP_DIR}/${DATE}"/*.json; do
    sha256sum "$f" >> "${BACKUP_DIR}/${DATE}/checksums.sha256"
done

# 7. Upload to remote storage (S3-compatible)
if [[ -n "${S3_BUCKET:-}" ]]; then
    echo "Uploading to S3..."
    aws s3 sync "${BACKUP_DIR}/${DATE}" "s3://${S3_BUCKET}/backups/${DATE}/"
fi

# 8. Cleanup old backups
echo "Cleaning backups older than ${RETENTION_DAYS} days..."
find "${BACKUP_DIR}" -mindepth 1 -maxdepth 1 -type d -mtime +${RETENTION_DAYS} -exec rm -rf {} \;

echo "[$(date)] Backup completed successfully"

# Backup log
echo "${DATE}: Backup completed (${BACKUP_DIR}/${DATE})" >> "${BACKUP_DIR}/backup.log"
```

### Recovery Procedure

```bash
#!/bin/bash
# D:/Ainos/scripts/restore.sh
# AinosOS Restore Script
# =======================

set -euo pipefail

RESTORE_DATE="${1:-}"
if [[ -z "${RESTORE_DATE}" ]]; then
    echo "Usage: $0 <backup-date>"
    echo "Available backups:"
    ls -1 /backup/ainos/
    exit 1
fi

BACKUP_PATH="/backup/ainos/${RESTORE_DATE}"

if [[ ! -d "${BACKUP_PATH}" ]]; then
    echo "Backup not found: ${BACKUP_PATH}"
    exit 1
fi

echo "[$(date)] Starting AinosOS restore from ${RESTORE_DATE}..."

# Verify checksums
echo "Verifying backup integrity..."
cd "${BACKUP_PATH}"
sha256sum -c checksums.sha256 || {
    echo "Checksum verification failed!"
    exit 1
}

# 1. Stop services
echo "Stopping services..."
docker compose -f /opt/ainos/deploy/docker-compose.yml down

# 2. Restore configuration
echo "Restoring configuration..."
tar xzf "${BACKUP_PATH}/config.tar.gz" -C /opt/ainos/

# 3. Restore context
echo "Restoring context data..."
if [[ -f "${BACKUP_PATH}/context.json" ]]; then
    curl -s -X POST "http://localhost:8080/api/context/import" \
        -H "Content-Type: application/json" \
        -d @"${BACKUP_PATH}/context.json"
fi

# 4. Restore model metadata
echo "Restoring model metadata..."
if [[ -f "${BACKUP_PATH}/models-metadata.tar.gz" ]]; then
    tar xzf "${BACKUP_PATH}/models-metadata.tar.gz" -C /opt/ainos/
fi

# 5. Restore database (if applicable)
echo "Restoring database..."
# psql -h localhost -U ainos ainos < "${BACKUP_PATH}/database.sql"

# 6. Start services
echo "Starting services..."
docker compose -f /opt/ainos/deploy/docker-compose.yml up -d

# 7. Verify
echo "Verifying restore..."
sleep 10
curl -s "http://localhost:8080/api/status" | python3 -m json.tool

echo "[$(date)] Restore completed successfully"
```

### Automated Backup Cron

```bash
# Add to crontab (sudo crontab -e)
# Daily backup at 2 AM
0 2 * * * /opt/ainos/scripts/backup.sh >> /var/log/ainos/backup.log 2>&1

# Weekly full backup (Sunday at 3 AM)
0 3 * * 0 /opt/ainos/scripts/backup.sh --full >> /var/log/ainos/backup.log 2>&1
```

---

## 7. Scaling / 扩展

### Horizontal Scaling (API Layer)

```yaml
# docker-compose scaling
docker compose up -d --scale ainos-api=5

# Kubernetes HPA
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ainos-api-hpa
  namespace: ainos
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ainos-api
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
    - type: Pods
      pods:
        metric:
          name: ainos_requests_in_flight
        target:
          type: AverageValue
          averageValue: 50
```

### Vertical Scaling (GPU/Model Layer)

```bash
# Increase GPU memory fraction
export AINOS_GPU_MEMORY_FRACTION=0.95

# Use multiple GPUs for tensor parallelism
export CUDA_VISIBLE_DEVICES=0,1,2,3

# Increase model batch size
export AINOS_MAX_BATCH_SIZE=64

# Increase inference workers
export AINOS_INFERENCE_WORKERS=4
```

### Load Balancing

```nginx
# D:/Ainos/deploy/nginx/nginx.conf
# ================================
# Nginx Load Balancer Configuration
# ================================

upstream ainos_backend {
    least_conn;
    server ainos-api-1:8080 max_fails=3 fail_timeout=30s;
    server ainos-api-2:8080 max_fails=3 fail_timeout=30s;
    server ainos-api-3:8080 max_fails=3 fail_timeout=30s;
    keepalive 64;
}

server {
    listen 80;
    server_name api.ainos.ai;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.ainos.ai;

    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;

    # Request buffering
    client_max_body_size 100m;
    client_body_buffer_size 128k;
    proxy_buffering off;
    proxy_request_buffering off;

    # Timeouts
    proxy_connect_timeout 10s;
    proxy_send_timeout 600s;
    proxy_read_timeout 600s;

    location / {
        proxy_pass http://ainos_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
    }

    location /ws/ {
        proxy_pass http://ainos_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
    }

    location /api/events {
        proxy_pass http://ainos_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
    }
}
```

---

## 8. High Availability / 高可用性

### Multi-Region Architecture

```
                    ┌───────────────┐
                    │  Global LB    │
                    │  (DNS Route53)│
                    └───────┬───────┘
                            │
            ┌───────────────┼───────────────┐
            │               │               │
    ┌───────▼───────┐ ┌───────▼───────┐ ┌───────▼───────┐
    │  us-east-1    │ │  eu-west-1    │ │  ap-southeast-1│
    │  ┌─────────┐  │ │  ┌─────────┐  │ │  ┌─────────┐  │
    │  │ Ainos   │  │ │  │ Ainos   │  │ │  │ Ainos   │  │
    │  │ API x3  │  │ │  │ API x3  │  │ │  │ API x3  │  │
    │  └─────────┘  │ │  └─────────┘  │ │  └─────────┘  │
    │  ┌─────────┐  │ │  ┌─────────┐  │ │  ┌─────────┐  │
    │  │ Redis   │  │ │  │ Redis   │  │ │  │ Redis   │  │
    │  │ (Active)│  │ │  │(Replica)│  │ │  │(Replica)│  │
    │  └─────────┘  │ │  └─────────┘  │ │  └─────────┘  │
    └───────────────┘ └───────────────┘ └───────────────┘
```

### Redis Configuration for HA

```yaml
# docker-compose.redis.yml
version: "3.8"

services:
  redis-master:
    image: redis:7.2-alpine
    command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis-master-data:/data
    networks:
      - ainos-net

  redis-replica:
    image: redis:7.2-alpine
    command: redis-server --appendonly yes --replicaof redis-master 6379 --requirepass ${REDIS_PASSWORD} --masterauth ${REDIS_PASSWORD}
    volumes:
      - redis-replica-data:/data
    depends_on:
      - redis-master
    networks:
      - ainos-net

  redis-sentinel:
    image: redis:7.2-alpine
    command: redis-sentinel /etc/redis/sentinel.conf
    volumes:
      - ./redis/sentinel.conf:/etc/redis/sentinel.conf:ro
    depends_on:
      - redis-master
      - redis-replica
    networks:
      - ainos-net
```

### Database HA Configuration

```yaml
# PostgreSQL with Patroni for HA
apiVersion: v1
kind: Service
metadata:
  name: ainos-db-ha
spec:
  selector:
    app: postgres
    cluster: ainos
  ports:
    - port: 5432
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres-ainos
spec:
  serviceName: postgres-ainos
  replicas: 3
  selector:
    matchLabels:
      app: postgres
      cluster: ainos
  template:
    metadata:
      labels:
        app: postgres
        cluster: ainos
    spec:
      containers:
        - name: postgres
          image: postgres:16
          env:
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: ainos-db-secrets
                  key: password
            - name: POSTGRES_DB
              value: ainos
          ports:
            - containerPort: 5432
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 100Gi
```

---

## 9. Disaster Recovery / 灾难恢复

### RPO and RTO Targets

| Tier | RPO (Recovery Point Objective) | RTO (Recovery Time Objective) |
|------|-------------------------------|-------------------------------|
| Platinum | 1 minute | 5 minutes |
| Gold | 15 minutes | 1 hour |
| Silver | 1 hour | 4 hours |
| Bronze | 24 hours | 24 hours |

### Disaster Recovery Plan

```yaml
# D:/Ainos/deploy/disaster-recovery/plan.yaml
# ==========================================
# Disaster Recovery Plan
# ==========================================

scenarios:
  - name: "Single Node Failure"
    impact: "Loss of one API server"
    response: "Auto-heal via Kubernetes/Docker Swarm"
    rto: "1 minute"
    rpo: "0 (stateless)"
  
  - name: "Multi-Node Failure"
    impact: "Loss of multiple API servers"
    response: "Scale up replacement nodes"
    rto: "5 minutes"
    rpo: "0 (stateless)"
  
  - name: "Data Corruption"
    impact: "Corrupted models or context data"
    response: "Restore from last backup"
    rto: "1 hour"
    rpo: "24 hours"
  
  - name: "Region Outage"
    impact: "Complete region failure"
    response: "Failover to secondary region"
    rto: "15 minutes"
    rpo: "5 minutes"
  
  - name: "Security Breach"
    impact: "Unauthorized access detected"
    response: "Isolate, rotate credentials, restore from clean backup"
    rto: "4 hours"
    rpo: "1 hour"
```

### DR Runbook

```bash
# Scenario: Complete region failure
# ==================================

# 1. Verify disaster
./scripts/check-region-health.sh us-east-1

# 2. Update DNS to secondary region
aws route53 change-resource-record-sets \
    --hosted-zone-id ZONEID \
    --change-batch '{
        "Changes": [{
            "Action": "UPSERT",
            "ResourceRecordSet": {
                "Name": "api.ainos.ai",
                "Type": "A",
                "SetIdentifier": "secondary",
                "Failover": "SECONDARY",
                "TTL": 60,
                "AliasTarget": {
                    "HostedZoneId": "ZONEID2",
                    "DNSName": "secondary-lb.ainos.ai",
                    "EvaluateTargetHealth": true
                }
            }
        }]
    }'

# 3. Start services in secondary region
kubectl config use-context ainos-secondary
kubectl apply -f deploy/k8s/

# 4. Restore latest data
./scripts/restore.sh $(aws s3 ls s3://ainos-backups/ | sort | tail -1 | awk '{print $2}' | tr -d '/')

# 5. Verify
curl -s "https://api.ainos.ai/api/status"
echo "Failover complete"
```

---

## 10. Security Hardening / 安全加固

### OS Hardening

```bash
# 1. Minimal base image
FROM alpine:3.19 AS runtime
# Or use distroless
FROM gcr.io/distroless/python3-debian12

# 2. Run as non-root
RUN adduser -D -h /opt/ainos ainos
USER ainos

# 3. Read-only root filesystem
securityContext:
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 1000
  capabilities:
    drop: ["ALL"]
  allowPrivilegeEscalation: false

# 4. AppArmor profile
apiVersion: v1
kind: Pod
metadata:
  annotations:
    container.apparmor.security.beta.kubernetes.io/ainos-api: localhost/ainos-api-profile
```

### Network Security

```yaml
# Kubernetes Network Policy
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: ainos-network-policy
  namespace: ainos
spec:
  podSelector:
    matchLabels:
      app: ainos
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: ingress-nginx
      ports:
        - port: 8080
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: redis
      ports:
        - port: 6379
    - to:
        - namespaceSelector:
            matchLabels:
              name: kube-system
        - podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - port: 53
          protocol: UDP
```

### Secrets Management

```bash
# Using Kubernetes Secrets
kubectl create secret generic ainos-secrets \
    --from-literal=api-token=$(openssl rand -hex 32) \
    --from-literal=redis-password=$(openssl rand -hex 16) \
    --from-literal=db-password=$(openssl rand -hex 16)

# Using HashiCorp Vault
vault kv put ainos/production/api-token=@token.txt
vault kv put ainos/production/redis-password=@password.txt

# Using AWS Secrets Manager
aws secretsmanager create-secret \
    --name ainos/production/api-token \
    --secret-string "$(openssl rand -hex 32)"
```

---

## 11. Performance Tuning / 性能调优

### System Tuning

```bash
# /etc/sysctl.d/99-ainos.conf
# ============================

# Network
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65535
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_intvl = 60
net.ipv4.tcp_keepalive_probes = 5
net.ipv4.tcp_max_syn_backlog = 65535
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.ipv4.tcp_rmem = 4096 87380 134217728
net.ipv4.tcp_wmem = 4096 65536 134217728

# Memory
vm.swappiness = 10
vm.dirty_ratio = 60
vm.dirty_background_ratio = 2
vm.vfs_cache_pressure = 50

# File system
fs.file-max = 2097152
fs.nr_open = 2097152
```

### Kernel Parameters

```bash
# Apply immediately
sudo sysctl -w net.core.somaxconn=65535
sudo sysctl -w vm.swappiness=10
sudo sysctl -w fs.file-max=2097152

# Set ulimits
echo "ainos soft nofile 1048576" | sudo tee /etc/security/limits.d/ainos.conf
echo "ainos hard nofile 1048576" | sudo tee -a /etc/security/limits.d/ainos.conf
```

### Application Tuning

```python
# Python: Use uvloop for async performance
import uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# Python: Set garbage collection tuning
import gc
gc.set_threshold(70000, 10, 10)

# AinosOS server tuning
AINOS_WORKERS=4
AINOS_BACKLOG=1024
AINOS_MAX_CONCURRENT=64
AINOS_KEEPALIVE_TIMEOUT=75
```

### GPU Tuning

```bash
# NVIDIA GPU tuning
nvidia-smi -pm 1  # Enable persistent mode
nvidia-smi -ac 1215,1410  # Set clock rates (A100)
nvidia-smi -pl 400  # Set power limit

# CUDA optimization
export CUDA_LAUNCH_BLOCKING=0
export CUDA_CACHE_DISABLE=0
export CUDA_CACHE_MAXSIZE=1073741824  # 1GB cache
export CUDA_DEVICE_ORDER=PCI_BUS_ID

# NCCL tuning
export NCCL_DEBUG=WARN
export NCCL_IB_DISABLE=0
export NCCL_IB_HCA=mlx5_0
export NCCL_SOCKET_IFNAME=eth0
```

---

## 12. Troubleshooting / 故障排除

### Common Issues

| Issue | Symptom | Solution |
|-------|---------|----------|
| GPU out of memory | CUDA OOM error | Reduce batch size, unload unused models |
| High latency | Slow responses | Check GPU utilization, scale horizontally |
| Connection refused | Server not starting | Check port availability, logs |
| Authentication failure | 401 errors | Verify API token, check auth config |
| Model load failure | Model not found | Check model path, permissions |
| WebSocket disconnects | Stream interruptions | Check proxy timeout configs |
| Disk full | Write errors | Clean logs, expand storage |
| SSL errors | Certificate issues | Renew certificates, check chain |

### Debugging Commands

```bash
# Check service status
docker compose ps
kubectl get pods -n ainos -o wide

# View logs
docker compose logs -f --tail=100 ainos-api
kubectl logs -n ainos -l app=ainos --tail=100 -f

# Check resource usage
docker stats
kubectl top pods -n ainos
nvidia-smi

# Test API
curl -s http://localhost:8080/api/status | jq .
curl -s -X POST http://localhost:8080/api/inference \
    -H "Content-Type: application/json" \
    -d '{"model":"ainos-llama-3.1-8b","prompt":"Hello","max_tokens":50}'

# Network diagnostics
curl -v http://localhost:8080/api/status
telnet localhost 8080
ss -tlnp | grep 8080

# Performance profiling
python -m cProfile -o profile.pstats scripts/benchmark.py
python -m pstats profile.pstats

# Memory profiling
pip install memory-profiler
python -m memory_profiler scripts/benchmark.py
```

---

## Quick Reference / 快速参考

### Useful Commands

```bash
# Start
docker compose up -d
kubectl apply -f deploy/k8s/

# Stop
docker compose down
kubectl delete -f deploy/k8s/

# Restart
docker compose restart ainos-api
kubectl rollout restart deployment ainos-api -n ainos

# Scale
docker compose up -d --scale ainos-api=5
kubectl scale deployment ainos-api -n ainos --replicas=5

# Update
docker compose pull && docker compose up -d
kubectl set image deployment/ainos-api ainos-api=ainos/api-server:1.1.0

# Logs
docker compose logs -f ainos-api
kubectl logs -n ainos -l app=ainos -f

# Backup
./scripts/backup.sh

# Restore
./scripts/restore.sh 20260804_020000
```

---

*For more information, visit [https://docs.ainos.ai](https://docs.ainos.ai) or contact the AinosOS team at dev@ainos.ai.*

*更多信息请访问 [https://docs.ainos.ai](https://docs.ainos.ai) 或联系 AinosOS 团队 dev@ainos.ai。*