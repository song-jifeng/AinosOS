# AinosOS Basic Inference Tutorial / 基础推理教程

> **Version:** 1.0.0 | **Updated:** 2026-08-04
>
> Learn how to perform basic inference with AinosOS using all 6 supported SDKs.
> 学习如何使用所有 6 种支持的 SDK 进行基础推理。

---

## Table of Contents / 目录

1. [Overview / 概述](#1-overview)
2. [Python SDK / Python SDK](#2-python-sdk)
3. [Go SDK / Go SDK](#3-go-sdk)
4. [Rust SDK / Rust SDK](#4-rust-sdk)
5. [Java SDK / Java SDK](#5-java-sdk)
6. [C# SDK / C# SDK](#6-c-sdk)
7. [Node.js SDK / Node.js SDK](#7-node-js-sdk)
8. [Error Handling / 错误处理](#8-error-handling)
9. [Running the Examples / 运行示例](#9-running-the-examples)
10. [Best Practices / 最佳实践](#10-best-practices)
11. [Troubleshooting / 故障排除](#11-troubleshooting)

---

## 1. Overview / 概述

### What is Inference? / 什么是推理？

Inference is the process of running a trained AI model to generate predictions or responses based on input data. In AinosOS, inference means sending a prompt to a loaded model and receiving a generated text response.

推理是运行已训练的 AI 模型以根据输入数据生成预测或响应的过程。在 AinosOS 中，推理意味着向已加载的模型发送提示词并接收生成的文本响应。

### Prerequisites / 前提条件

Before starting, ensure you have:

```bash
# 1. AinosOS server running
curl http://localhost:8080/api/status
# Expected: {"status":"online","cpu":...}

# 2. At least one model loaded
curl http://localhost:8080/api/models
# Expected: {"models":[{"id":"ainos-llama-3.1-8b","status":"loaded",...}]}

# 3. API token (if auth enabled)
export AINOS_API_TOKEN="your-token-here"
```

### API Reference / API 参考

```
POST /api/inference
Content-Type: application/json
Authorization: Bearer <token>

{
    "model": "ainos-llama-3.1-8b",
    "prompt": "Your prompt text here",
    "max_tokens": 1024,
    "temperature": 0.7,
    "stream": false
}

Response:
{
    "model": "ainos-llama-3.1-8b",
    "text": "Generated response text...",
    "tokens": 150,
    "finish_reason": "stop"
}
```

---

## 2. Python SDK / Python SDK

### Installation

```bash
pip install ainos-sdk
# or
pip install aiosdk
```

### Complete Example

```python
#!/usr/bin/env python3
"""
D:/Ainos/examples/python/basic_inference.py
Python SDK Basic Inference Example
======================================
"""

import os
import sys
import json
import time
from typing import Optional, Dict, Any

# Try importing the SDK, fall back to direct HTTP
try:
    from ainos import AinosClient, AinosError
    HAS_SDK = True
except ImportError:
    HAS_SDK = False
    import requests


class AinosInference:
    """
    AinosOS inference client.
    Demonstrates basic inference using the AinosOS API.
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_token: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token or os.environ.get("AINOS_API_TOKEN", "")
        
        if HAS_SDK:
            self.client = AinosClient(
                base_url=self.base_url,
                api_token=self.api_token,
            )
    
    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers
    
    def check_status(self) -> Dict[str, Any]:
        """Check server status."""
        if HAS_SDK:
            return self.client.get_status()
        
        resp = requests.get(
            f"{self.base_url}/api/status",
            headers=self._get_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    
    def list_models(self) -> list:
        """List available models."""
        if HAS_SDK:
            return self.client.list_models()
        
        resp = requests.get(
            f"{self.base_url}/api/models",
            headers=self._get_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("models", data)
    
    def infer(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        """
        Run inference on a model.
        
        Args:
            model: Model ID to use for inference
            prompt: Input prompt text
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0 - 2.0)
        
        Returns:
            Dict containing the response text and metadata
        """
        if HAS_SDK:
            response = self.client.infer(
                model=model,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,
            )
            return {
                "text": response.text,
                "tokens": response.tokens,
                "finish_reason": response.finish_reason,
                "model": response.model,
            }
        
        # Direct HTTP request
        payload = {
            "model": model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        
        resp = requests.post(
            f"{self.base_url}/api/inference",
            headers=self._get_headers(),
            json=payload,
            timeout=300,  # 5 minute timeout for long generations
        )
        resp.raise_for_status()
        return resp.json()


def main():
    """Main example demonstrating basic inference."""
    print("=" * 60)
    print("AinosOS Python SDK - Basic Inference Example")
    print("=" * 60)
    
    # Initialize client
    client = AinosInference(
        base_url=os.environ.get("AINOS_URL", "http://localhost:8080"),
        api_token=os.environ.get("AINOS_API_TOKEN", ""),
    )
    
    # Step 1: Check server status
    print("\n[1] Checking server status...")
    try:
        status = client.check_status()
        print(f"    Status: {status.get('status', 'unknown')}")
        print(f"    CPU: {status.get('cpu', 'N/A')}%")
        print(f"    Memory: {status.get('memory', 'N/A')}%")
        print(f"    Uptime: {status.get('uptime', 'N/A')}s")
    except Exception as e:
        print(f"    ERROR: Could not connect to server: {e}")
        sys.exit(1)
    
    # Step 2: List available models
    print("\n[2] Listing available models...")
    try:
        models = client.list_models()
        if not models:
            print("    No models found. Load a model first.")
            sys.exit(1)
        
        for i, model in enumerate(models):
            name = model.get("name", model.get("id", "unknown"))
            status = model.get("status", "unknown")
            print(f"    {i+1}. {name} [{status}]")
        
        # Select first loaded model
        loaded_models = [m for m in models if m.get("status") == "loaded"]
        if not loaded_models:
            print("    No loaded models available.")
            sys.exit(1)
        
        selected_model = loaded_models[0]
        model_id = selected_model.get("id") or selected_model.get("model_id", "")
        print(f"\n    Using model: {model_id}")
    except Exception as e:
        print(f"    ERROR: Could not list models: {e}")
        sys.exit(1)
    
    # Step 3: Run inference
    print("\n[3] Running inference...")
    prompt = "Explain what artificial intelligence is in simple terms."
    print(f"    Prompt: {prompt}")
    
    start_time = time.time()
    try:
        result = client.infer(
            model=model_id,
            prompt=prompt,
            max_tokens=200,
            temperature=0.7,
        )
        elapsed = time.time() - start_time
        
        response_text = result.get("text", result.get("response", ""))
        tokens = result.get("tokens", 0)
        finish_reason = result.get("finish_reason", "unknown")
        
        print(f"\n    Response ({elapsed:.2f}s, {tokens} tokens):")
        print(f"    {response_text}")
        print(f"\n    Finish reason: {finish_reason}")
    except Exception as e:
        print(f"    ERROR: Inference failed: {e}")
        sys.exit(1)
    
    # Step 4: Multiple prompts
    print("\n[4] Running multiple prompts...")
    prompts = [
        "What is machine learning?",
        "List three programming languages and their uses.",
        "Write a short poem about technology.",
    ]
    
    for i, prompt in enumerate(prompts, 1):
        print(f"\n    Prompt {i}: {prompt}")
        start_time = time.time()
        try:
            result = client.infer(
                model=model_id,
                prompt=prompt,
                max_tokens=100,
                temperature=0.8,
            )
            elapsed = time.time() - start_time
            response_text = result.get("text", result.get("response", ""))
            print(f"    Response ({elapsed:.2f}s): {response_text[:100]}...")
        except Exception as e:
            print(f"    ERROR: {e}")
    
    print("\n" + "=" * 60)
    print("Inference example completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
```

### Output Example

```bash
$ python basic_inference.py

============================================================
AinosOS Python SDK - Basic Inference Example
============================================================

[1] Checking server status...
    Status: online
    CPU: 23.5%
    Memory: 45.2%
    Uptime: 12345s

[2] Listing available models...
    1. Ainos Llama 3.1 8B [loaded]
    2. Ainos Qwen 2.5 7B [loaded]
    3. Ainos Mistral 7B [unloaded]
    
    Using model: ainos-llama-3.1-8b

[3] Running inference...
    Prompt: Explain what artificial intelligence is in simple terms.
    
    Response (1.23s, 156 tokens):
    Artificial Intelligence (AI) is a branch of computer science that
    creates machines capable of performing tasks that typically require
    human intelligence. These tasks include learning from experience,
    understanding natural language, recognizing patterns, and making
    decisions. In simple terms, AI is like giving computers the ability
    to think and learn, similar to how humans do, but at a much faster
    scale...
    
    Finish reason: stop

[4] Running multiple prompts...

    Prompt 1: What is machine learning?
    Response (0.89s): Machine learning is a subset of artificial
    intelligence that enables systems to learn and improve from
    experience without being explicitly programmed...

    Prompt 2: List three programming languages and their uses.
    Response (0.92s): 1. Python - Data science, web development,
    automation. 2. JavaScript - Web development, mobile apps...

    Prompt 3: Write a short poem about technology.
    Response (1.01s): In circuits deep and codes so bright,
    Technology brings forth the light...

============================================================
Inference example completed successfully!
============================================================
```

---

## 3. Go SDK / Go SDK

### Installation

```bash
go get github.com/ainos-ai/ainos-sdk-go
```

### Complete Example

```go
// D:/Ainos/examples/go/basic_inference.go
// Go SDK Basic Inference Example
// ================================

package main

import (
    "bytes"
    "encoding/json"
    "fmt"
    "io"
    "net/http"
    "os"
    "time"
)

// AinosClient handles communication with AinosOS API
type AinosClient struct {
    baseURL   string
    apiToken  string
    httpClient *http.Client
}

// Status represents system status
type Status struct {
    Status    string  `json:"status"`
    CPU       float64 `json:"cpu"`
    Memory    float64 `json:"memory"`
    Uptime    float64 `json:"uptime"`
}

// Model represents a model entry
type Model struct {
    ID     string `json:"id"`
    Name   string `json:"name"`
    Status string `json:"status"`
    VRAM   int64  `json:"vram"`
}

// InferenceRequest is the request body
type InferenceRequest struct {
    Model       string  `json:"model"`
    Prompt      string  `json:"prompt"`
    MaxTokens   int     `json:"max_tokens"`
    Temperature float64 `json:"temperature"`
    Stream      bool    `json:"stream"`
}

// InferenceResponse is the response body
type InferenceResponse struct {
    Model        string `json:"model"`
    Text         string `json:"text"`
    Tokens       int    `json:"tokens"`
    FinishReason string `json:"finish_reason"`
}

// NewClient creates a new AinosOS client
func NewClient(baseURL, apiToken string) *AinosClient {
    return &AinosClient{
        baseURL:  baseURL,
        apiToken: apiToken,
        httpClient: &http.Client{
            Timeout: 300 * time.Second,
        },
    }
}

func (c *AinosClient) getHeaders() http.Header {
    headers := http.Header{}
    headers.Set("Content-Type", "application/json")
    if c.apiToken != "" {
        headers.Set("Authorization", "Bearer "+c.apiToken)
    }
    return headers
}

// GetStatus checks server status
func (c *AinosClient) GetStatus() (*Status, error) {
    req, err := http.NewRequest("GET", c.baseURL+"/api/status", nil)
    if err != nil {
        return nil, fmt.Errorf("failed to create request: %w", err)
    }
    req.Header = c.getHeaders()
    
    resp, err := c.httpClient.Do(req)
    if err != nil {
        return nil, fmt.Errorf("failed to get status: %w", err)
    }
    defer resp.Body.Close()
    
    if resp.StatusCode != http.StatusOK {
        return nil, fmt.Errorf("unexpected status: %d", resp.StatusCode)
    }
    
    var status Status
    if err := json.NewDecoder(resp.Body).Decode(&status); err != nil {
        return nil, fmt.Errorf("failed to decode response: %w", err)
    }
    
    return &status, nil
}

// ListModels gets available models
func (c *AinosClient) ListModels() ([]Model, error) {
    req, err := http.NewRequest("GET", c.baseURL+"/api/models", nil)
    if err != nil {
        return nil, fmt.Errorf("failed to create request: %w", err)
    }
    req.Header = c.getHeaders()
    
    resp, err := c.httpClient.Do(req)
    if err != nil {
        return nil, fmt.Errorf("failed to list models: %w", err)
    }
    defer resp.Body.Close()
    
    var result struct {
        Models []Model `json:"models"`
    }
    if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
        return nil, fmt.Errorf("failed to decode response: %w", err)
    }
    
    return result.Models, nil
}

// Infer runs inference on a model
func (c *AinosClient) Infer(model, prompt string, maxTokens int, temperature float64) (*InferenceResponse, error) {
    payload := InferenceRequest{
        Model:       model,
        Prompt:      prompt,
        MaxTokens:   maxTokens,
        Temperature: temperature,
        Stream:      false,
    }
    
    body, err := json.Marshal(payload)
    if err != nil {
        return nil, fmt.Errorf("failed to marshal request: %w", err)
    }
    
    req, err := http.NewRequest("POST", c.baseURL+"/api/inference", bytes.NewReader(body))
    if err != nil {
        return nil, fmt.Errorf("failed to create request: %w", err)
    }
    req.Header = c.getHeaders()
    
    resp, err := c.httpClient.Do(req)
    if err != nil {
        return nil, fmt.Errorf("failed to run inference: %w", err)
    }
    defer resp.Body.Close()
    
    respBody, err := io.ReadAll(resp.Body)
    if err != nil {
        return nil, fmt.Errorf("failed to read response: %w", err)
    }
    
    if resp.StatusCode != http.StatusOK {
        return nil, fmt.Errorf("inference failed (status %d): %s", resp.StatusCode, string(respBody))
    }
    
    var result InferenceResponse
    if err := json.Unmarshal(respBody, &result); err != nil {
        return nil, fmt.Errorf("failed to decode response: %w", err)
    }
    
    return &result, nil
}

func main() {
    fmt.Println("============================================")
    fmt.Println("AinosOS Go SDK - Basic Inference Example")
    fmt.Println("============================================")
    
    // Initialize client
    baseURL := getEnv("AINOS_URL", "http://localhost:8080")
    apiToken := getEnv("AINOS_API_TOKEN", "")
    client := NewClient(baseURL, apiToken)
    
    // Step 1: Check status
    fmt.Println("\n[1] Checking server status...")
    status, err := client.GetStatus()
    if err != nil {
        fmt.Printf("    ERROR: %v\n", err)
        os.Exit(1)
    }
    fmt.Printf("    Status: %s\n", status.Status)
    fmt.Printf("    CPU: %.1f%%\n", status.CPU)
    fmt.Printf("    Memory: %.1f%%\n", status.Memory)
    
    // Step 2: List models
    fmt.Println("\n[2] Listing available models...")
    models, err := client.ListModels()
    if err != nil {
        fmt.Printf("    ERROR: %v\n", err)
        os.Exit(1)
    }
    
    var selectedModel string
    for _, model := range models {
        fmt.Printf("    - %s [%s]\n", model.Name, model.Status)
        if model.Status == "loaded" && selectedModel == "" {
            selectedModel = model.ID
        }
    }
    
    if selectedModel == "" {
        fmt.Println("    No loaded models available.")
        os.Exit(1)
    }
    fmt.Printf("\n    Using model: %s\n", selectedModel)
    
    // Step 3: Run inference
    fmt.Println("\n[3] Running inference...")
    prompt := "Explain what artificial intelligence is in simple terms."
    fmt.Printf("    Prompt: %s\n", prompt)
    
    start := time.Now()
    result, err := client.Infer(selectedModel, prompt, 200, 0.7)
    elapsed := time.Since(start)
    
    if err != nil {
        fmt.Printf("    ERROR: %v\n", err)
        os.Exit(1)
    }
    
    fmt.Printf("\n    Response (%v, %d tokens):\n", elapsed, result.Tokens)
    fmt.Printf("    %s\n", result.Text)
    fmt.Printf("\n    Finish reason: %s\n", result.FinishReason)
    
    fmt.Println("\n============================================")
    fmt.Println("Inference example completed successfully!")
    fmt.Println("============================================")
}

func getEnv(key, fallback string) string {
    if value, ok := os.LookupEnv(key); ok {
        return value
    }
    return fallback
}
```

### Build and Run

```bash
# Run the Go example
cd examples/go
go run basic_inference.go

# Build binary
go build -o ainos-infer basic_inference.go
./ainos-infer
```

---

## 4. Rust SDK / Rust SDK

### Cargo.toml

```toml
[package]
name = "ainos-basic-inference"
version = "1.0.0"
edition = "2021"

[dependencies]
ainos-sdk = "1.0"
reqwest = { version = "0.12", features = ["json"] }
tokio = { version = "1", features = ["full"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
anyhow = "1"
```

### Complete Example

```rust
// D:/Ainos/examples/rust/basic_inference.rs
// Rust SDK Basic Inference Example
// ==================================

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::env;
use std::time::Instant;

#[derive(Debug, Deserialize)]
struct Status {
    status: String,
    cpu: f64,
    memory: f64,
    uptime: f64,
}

#[derive(Debug, Deserialize)]
struct Model {
    #[serde(rename = "id")]
    id: String,
    name: String,
    status: String,
    vram: Option<i64>,
}

#[derive(Debug, Deserialize)]
struct ModelsResponse {
    models: Vec<Model>,
}

#[derive(Debug, Serialize)]
struct InferenceRequest {
    model: String,
    prompt: String,
    max_tokens: u32,
    temperature: f64,
    stream: bool,
}

#[derive(Debug, Deserialize)]
struct InferenceResponse {
    model: String,
    text: String,
    tokens: u32,
    finish_reason: String,
}

struct AinosClient {
    base_url: String,
    api_token: String,
    client: reqwest::Client,
}

impl AinosClient {
    fn new(base_url: String, api_token: String) -> Self {
        Self {
            base_url,
            api_token,
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(300))
                .build()
                .expect("Failed to create HTTP client"),
        }
    }

    fn headers(&self) -> reqwest::header::HeaderMap {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert(
            reqwest::header::CONTENT_TYPE,
            "application/json".parse().unwrap(),
        );
        if !self.api_token.is_empty() {
            headers.insert(
                reqwest::header::AUTHORIZATION,
                format!("Bearer {}", self.api_token).parse().unwrap(),
            );
        }
        headers
    }

    async fn get_status(&self) -> Result<Status> {
        let url = format!("{}/api/status", self.base_url);
        let response = self
            .client
            .get(&url)
            .headers(self.headers())
            .send()
            .await
            .context("Failed to send status request")?;
        
        let status: Status = response
            .json()
            .await
            .context("Failed to parse status response")?;
        
        Ok(status)
    }

    async fn list_models(&self) -> Result<Vec<Model>> {
        let url = format!("{}/api/models", self.base_url);
        let response = self
            .client
            .get(&url)
            .headers(self.headers())
            .send()
            .await
            .context("Failed to send models request")?;
        
        let models_response: ModelsResponse = response
            .json()
            .await
            .context("Failed to parse models response")?;
        
        Ok(models_response.models)
    }

    async fn infer(
        &self,
        model: &str,
        prompt: &str,
        max_tokens: u32,
        temperature: f64,
    ) -> Result<InferenceResponse> {
        let url = format!("{}/api/inference", self.base_url);
        
        let request = InferenceRequest {
            model: model.to_string(),
            prompt: prompt.to_string(),
            max_tokens,
            temperature,
            stream: false,
        };
        
        let response = self
            .client
            .post(&url)
            .headers(self.headers())
            .json(&request)
            .send()
            .await
            .context("Failed to send inference request")?;
        
        let inference_response: InferenceResponse = response
            .json()
            .await
            .context("Failed to parse inference response")?;
        
        Ok(inference_response)
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    println!("============================================");
    println!("AinosOS Rust SDK - Basic Inference Example");
    println!("============================================");

    let base_url = env::var("AINOS_URL").unwrap_or_else(|_| "http://localhost:8080".to_string());
    let api_token = env::var("AINOS_API_TOKEN").unwrap_or_default();
    
    let client = AinosClient::new(base_url, api_token);

    // Step 1: Check status
    println!("\n[1] Checking server status...");
    let status = client.get_status().await?;
    println!("    Status: {}", status.status);
    println!("    CPU: {:.1}%", status.cpu);
    println!("    Memory: {:.1}%", status.memory);

    // Step 2: List models
    println!("\n[2] Listing available models...");
    let models = client.list_models().await?;
    
    let mut selected_model = String::new();
    for model in &models {
        println!("    - {} [{}]", model.name, model.status);
        if model.status == "loaded" && selected_model.is_empty() {
            selected_model = model.id.clone();
        }
    }
    
    if selected_model.is_empty() {
        println!("    No loaded models available.");
        return Ok(());
    }
    println!("\n    Using model: {}", selected_model);

    // Step 3: Run inference
    println!("\n[3] Running inference...");
    let prompt = "Explain what artificial intelligence is in simple terms.";
    println!("    Prompt: {}", prompt);
    
    let start = Instant::now();
    let result = client.infer(&selected_model, prompt, 200, 0.7).await?;
    let elapsed = start.elapsed();
    
    println!("\n    Response ({:?}, {} tokens):", elapsed, result.tokens);
    println!("    {}", result.text);
    println!("\n    Finish reason: {}", result.finish_reason);

    println!("\n============================================");
    println!("Inference example completed successfully!");
    println!("============================================");

    Ok(())
}
```

### Build and Run

```bash
cd examples/rust
cargo build --release
./target/release/ainos-basic-inference
```

---

## 5. Java SDK / Java SDK

### Maven POM

```xml
<!-- D:/Ainos/examples/java/pom.xml -->
<project>
    <modelVersion>4.0.0</modelVersion>
    <groupId>ai.ainos</groupId>
    <artifactId>basic-inference</artifactId>
    <version>1.0.0</version>
    
    <dependencies>
        <dependency>
            <groupId>ai.ainos</groupId>
            <artifactId>ainos-sdk</artifactId>
            <version>1.0.0</version>
        </dependency>
        <dependency>
            <groupId>com.google.code.gson</groupId>
            <artifactId>gson</artifactId>
            <version>2.10.1</version>
        </dependency>
    </dependencies>
    
    <build>
        <plugins>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-compiler-plugin</artifactId>
                <configuration>
                    <source>21</source>
                    <target>21</target>
                </configuration>
            </plugin>
        </plugins>
    </build>
</project>
```

### Complete Example

```java
// D:/Ainos/examples/java/BasicInference.java
// Java SDK Basic Inference Example
// ==================================

package ai.ainos.examples;

import ai.ainos.*;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.annotations.SerializedName;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;

public class BasicInference {
    
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();
    
    // Data classes
    static class Status {
        String status;
        double cpu;
        double memory;
        double uptime;
    }
    
    static class Model {
        String id;
        String name;
        String status;
        Long vram;
    }
    
    static class ModelsResponse {
        List<Model> models;
    }
    
    static class InferenceRequest {
        String model;
        String prompt;
        @SerializedName("max_tokens")
        int maxTokens;
        double temperature;
        boolean stream;
        
        InferenceRequest(String model, String prompt, int maxTokens, double temperature) {
            this.model = model;
            this.prompt = prompt;
            this.maxTokens = maxTokens;
            this.temperature = temperature;
            this.stream = false;
        }
    }
    
    static class InferenceResponse {
        String model;
        String text;
        int tokens;
        @SerializedName("finish_reason")
        String finishReason;
    }
    
    static class AinosClient {
        private final String baseUrl;
        private final String apiToken;
        private final HttpClient httpClient;
        
        AinosClient(String baseUrl, String apiToken) {
            this.baseUrl = baseUrl;
            this.apiToken = apiToken;
            this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();
        }
        
        private HttpRequest.Builder requestBuilder(String path) {
            HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + path))
                .header("Content-Type", "application/json")
                .timeout(Duration.ofSeconds(300));
            
            if (apiToken != null && !apiToken.isEmpty()) {
                builder.header("Authorization", "Bearer " + apiToken);
            }
            
            return builder;
        }
        
        Status getStatus() throws Exception {
            HttpRequest request = requestBuilder("/api/status")
                .GET()
                .build();
            
            HttpResponse<String> response = httpClient.send(request, 
                HttpResponse.BodyHandlers.ofString());
            
            if (response.statusCode() != 200) {
                throw new RuntimeException("Status check failed: " + response.statusCode());
            }
            
            return GSON.fromJson(response.body(), Status.class);
        }
        
        List<Model> listModels() throws Exception {
            HttpRequest request = requestBuilder("/api/models")
                .GET()
                .build();
            
            HttpResponse<String> response = httpClient.send(request, 
                HttpResponse.BodyHandlers.ofString());
            
            if (response.statusCode() != 200) {
                throw new RuntimeException("List models failed: " + response.statusCode());
            }
            
            ModelsResponse modelsResponse = GSON.fromJson(response.body(), ModelsResponse.class);
            return modelsResponse.models;
        }
        
        InferenceResponse infer(String model, String prompt, int maxTokens, double temperature) 
                throws Exception {
            InferenceRequest inferenceRequest = new InferenceRequest(
                model, prompt, maxTokens, temperature);
            
            String requestBody = GSON.toJson(inferenceRequest);
            
            HttpRequest request = requestBuilder("/api/inference")
                .POST(HttpRequest.BodyPublishers.ofString(requestBody))
                .build();
            
            HttpResponse<String> response = httpClient.send(request, 
                HttpResponse.BodyHandlers.ofString());
            
            if (response.statusCode() != 200) {
                throw new RuntimeException("Inference failed: " + response.statusCode() + 
                    " " + response.body());
            }
            
            return GSON.fromJson(response.body(), InferenceResponse.class);
        }
    }
    
    public static void main(String[] args) {
        System.out.println("============================================");
        System.out.println("AinosOS Java SDK - Basic Inference Example");
        System.out.println("============================================");
        
        String baseUrl = System.getenv().getOrDefault("AINOS_URL", "http://localhost:8080");
        String apiToken = System.getenv().getOrDefault("AINOS_API_TOKEN", "");
        
        AinosClient client = new AinosClient(baseUrl, apiToken);
        
        try {
            // Step 1: Check status
            System.out.println("\n[1] Checking server status...");
            Status status = client.getStatus();
            System.out.println("    Status: " + status.status);
            System.out.printf("    CPU: %.1f%%\n", status.cpu);
            System.out.printf("    Memory: %.1f%%\n", status.memory);
            
            // Step 2: List models
            System.out.println("\n[2] Listing available models...");
            List<Model> models = client.listModels();
            
            String selectedModel = null;
            for (Model model : models) {
                System.out.println("    - " + model.name + " [" + model.status + "]");
                if ("loaded".equals(model.status) && selectedModel == null) {
                    selectedModel = model.id;
                }
            }
            
            if (selectedModel == null) {
                System.out.println("    No loaded models available.");
                return;
            }
            System.out.println("\n    Using model: " + selectedModel);
            
            // Step 3: Run inference
            System.out.println("\n[3] Running inference...");
            String prompt = "Explain what artificial intelligence is in simple terms.";
            System.out.println("    Prompt: " + prompt);
            
            long start = System.currentTimeMillis();
            InferenceResponse result = client.infer(selectedModel, prompt, 200, 0.7);
            long elapsed = System.currentTimeMillis() - start;
            
            System.out.printf("\n    Response (%dms, %d tokens):\n", elapsed, result.tokens);
            System.out.println("    " + result.text);
            System.out.println("\n    Finish reason: " + result.finishReason);
            
            System.out.println("\n============================================");
            System.out.println("Inference example completed successfully!");
            System.out.println("============================================");
            
        } catch (Exception e) {
            System.err.println("ERROR: " + e.getMessage());
            e.printStackTrace();
            System.exit(1);
        }
    }
}
```

### Build and Run

```bash
cd examples/java
mvn compile
mvn exec:java -Dexec.mainClass="ai.ainos.examples.BasicInference"
# or
mvn package
java -cp target/basic-inference-1.0.0.jar ai.ainos.examples.BasicInference
```

---

## 6. C# SDK / C# SDK

### Project File

```xml
<!-- D:/Ainos/examples/csharp/BasicInference.csproj -->
<Project Sdk="Microsoft.NET.Sdk">
    <PropertyGroup>
        <OutputType>Exe</OutputType>
        <TargetFramework>net8.0</TargetFramework>
        <Nullable>enable</Nullable>
    </PropertyGroup>
    
    <ItemGroup>
        <PackageReference Include="Ainos.Sdk" Version="1.0.0" />
        <PackageReference Include="System.Text.Json" Version="8.0.0" />
    </ItemGroup>
</Project>
```

### Complete Example

```csharp
// D:/Ainos/examples/csharp/BasicInference.cs
// C# SDK Basic Inference Example
// ================================

using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;

namespace AinosExamples
{
    // Data classes
    public class SystemStatus
    {
        [JsonPropertyName("status")]
        public string Status { get; set; } = "";
        
        [JsonPropertyName("cpu")]
        public double Cpu { get; set; }
        
        [JsonPropertyName("memory")]
        public double Memory { get; set; }
        
        [JsonPropertyName("uptime")]
        public double Uptime { get; set; }
    }
    
    public class ModelInfo
    {
        [JsonPropertyName("id")]
        public string Id { get; set; } = "";
        
        [JsonPropertyName("name")]
        public string Name { get; set; } = "";
        
        [JsonPropertyName("status")]
        public string Status { get; set; } = "";
    }
    
    public class ModelsResponse
    {
        [JsonPropertyName("models")]
        public List<ModelInfo> Models { get; set; } = new();
    }
    
    public class InferenceRequest
    {
        [JsonPropertyName("model")]
        public string Model { get; set; } = "";
        
        [JsonPropertyName("prompt")]
        public string Prompt { get; set; } = "";
        
        [JsonPropertyName("max_tokens")]
        public int MaxTokens { get; set; } = 1024;
        
        [JsonPropertyName("temperature")]
        public double Temperature { get; set; } = 0.7;
        
        [JsonPropertyName("stream")]
        public bool Stream { get; set; } = false;
    }
    
    public class InferenceResponse
    {
        [JsonPropertyName("model")]
        public string Model { get; set; } = "";
        
        [JsonPropertyName("text")]
        public string Text { get; set; } = "";
        
        [JsonPropertyName("tokens")]
        public int Tokens { get; set; }
        
        [JsonPropertyName("finish_reason")]
        public string FinishReason { get; set; } = "";
    }
    
    public class AinosClient
    {
        private readonly HttpClient _httpClient;
        private readonly string _baseUrl;
        private readonly string _apiToken;
        private static readonly JsonSerializerOptions _jsonOptions = new()
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            WriteIndented = true,
        };
        
        public AinosClient(string baseUrl, string apiToken)
        {
            _baseUrl = baseUrl.TrimEnd('/');
            _apiToken = apiToken;
            _httpClient = new HttpClient
            {
                Timeout = TimeSpan.FromMinutes(5)
            };
        }
        
        private void AddHeaders(HttpRequestMessage request)
        {
            request.Headers.Add("Content-Type", "application/json");
            if (!string.IsNullOrEmpty(_apiToken))
            {
                request.Headers.Add("Authorization", $"Bearer {_apiToken}");
            }
        }
        
        public async Task<SystemStatus> GetStatusAsync()
        {
            var request = new HttpRequestMessage(HttpMethod.Get, $"{_baseUrl}/api/status");
            AddHeaders(request);
            
            var response = await _httpClient.SendAsync(request);
            response.EnsureSuccessStatusCode();
            
            var json = await response.Content.ReadAsStringAsync();
            return JsonSerializer.Deserialize<SystemStatus>(json, _jsonOptions)
                ?? throw new Exception("Failed to parse status");
        }
        
        public async Task<List<ModelInfo>> ListModelsAsync()
        {
            var request = new HttpRequestMessage(HttpMethod.Get, $"{_baseUrl}/api/models");
            AddHeaders(request);
            
            var response = await _httpClient.SendAsync(request);
            response.EnsureSuccessStatusCode();
            
            var json = await response.Content.ReadAsStringAsync();
            var modelsResponse = JsonSerializer.Deserialize<ModelsResponse>(json, _jsonOptions);
            return modelsResponse?.Models ?? new List<ModelInfo>();
        }
        
        public async Task<InferenceResponse> InferAsync(
            string model, string prompt, int maxTokens = 1024, double temperature = 0.7)
        {
            var inferenceRequest = new InferenceRequest
            {
                Model = model,
                Prompt = prompt,
                MaxTokens = maxTokens,
                Temperature = temperature,
                Stream = false,
            };
            
            var content = new StringContent(
                JsonSerializer.Serialize(inferenceRequest, _jsonOptions),
                Encoding.UTF8,
                "application/json");
            
            var request = new HttpRequestMessage(HttpMethod.Post, $"{_baseUrl}/api/inference")
            {
                Content = content
            };
            AddHeaders(request);
            
            var response = await _httpClient.SendAsync(request);
            var responseBody = await response.Content.ReadAsStringAsync();
            
            if (!response.IsSuccessStatusCode)
            {
                throw new Exception($"Inference failed ({response.StatusCode}): {responseBody}");
            }
            
            return JsonSerializer.Deserialize<InferenceResponse>(responseBody, _jsonOptions)
                ?? throw new Exception("Failed to parse inference response");
        }
    }
    
    class Program
    {
        static async Task Main(string[] args)
        {
            Console.WriteLine("============================================");
            Console.WriteLine("AinosOS C# SDK - Basic Inference Example");
            Console.WriteLine("============================================");
            
            var baseUrl = Environment.GetEnvironmentVariable("AINOS_URL") ?? "http://localhost:8080";
            var apiToken = Environment.GetEnvironmentVariable("AINOS_API_TOKEN") ?? "";
            
            var client = new AinosClient(baseUrl, apiToken);
            
            try
            {
                // Step 1: Check status
                Console.WriteLine("\n[1] Checking server status...");
                var status = await client.GetStatusAsync();
                Console.WriteLine($"    Status: {status.Status}");
                Console.WriteLine($"    CPU: {status.Cpu:F1}%");
                Console.WriteLine($"    Memory: {status.Memory:F1}%");
                
                // Step 2: List models
                Console.WriteLine("\n[2] Listing available models...");
                var models = await client.ListModelsAsync();
                
                string? selectedModel = null;
                foreach (var model in models)
                {
                    Console.WriteLine($"    - {model.Name} [{model.Status}]");
                    if (model.Status == "loaded" && selectedModel == null)
                    {
                        selectedModel = model.Id;
                    }
                }
                
                if (selectedModel == null)
                {
                    Console.WriteLine("    No loaded models available.");
                    return;
                }
                Console.WriteLine($"\n    Using model: {selectedModel}");
                
                // Step 3: Run inference
                Console.WriteLine("\n[3] Running inference...");
                string prompt = "Explain what artificial intelligence is in simple terms.";
                Console.WriteLine($"    Prompt: {prompt}");
                
                var start = DateTime.Now;
                var result = await client.InferAsync(selectedModel, prompt, 200, 0.7);
                var elapsed = DateTime.Now - start;
                
                Console.WriteLine($"\n    Response ({elapsed.TotalSeconds:F2}s, {result.Tokens} tokens):");
                Console.WriteLine($"    {result.Text}");
                Console.WriteLine($"\n    Finish reason: {result.FinishReason}");
                
                Console.WriteLine("\n============================================");
                Console.WriteLine("Inference example completed successfully!");
                Console.WriteLine("============================================");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"ERROR: {ex.Message}");
                Environment.Exit(1);
            }
        }
    }
}
```

### Build and Run

```bash
cd examples/csharp
dotnet restore
dotnet run
```

---

## 7. Node.js SDK / Node.js SDK

### Package.json

```json
{
    "name": "ainos-basic-inference",
    "version": "1.0.0",
    "description": "AinosOS Node.js SDK Basic Inference Example",
    "main": "basic_inference.js",
    "dependencies": {
        "ainos-sdk": "^1.0.0",
        "node-fetch": "^3.3.2"
    },
    "type": "module"
}
```

### Complete Example

```javascript
// D:/Ainos/examples/nodejs/basic_inference.js
// Node.js SDK Basic Inference Example
// =====================================

import fetch from 'node-fetch';

class AinosClient {
    constructor(baseUrl, apiToken) {
        this.baseUrl = baseUrl.replace(/\/+$/, '');
        this.apiToken = apiToken || '';
        this.headers = {
            'Content-Type': 'application/json',
        };
        if (this.apiToken) {
            this.headers['Authorization'] = `Bearer ${this.apiToken}`;
        }
    }

    async getStatus() {
        const response = await fetch(`${this.baseUrl}/api/status`, {
            headers: this.headers,
        });
        if (!response.ok) {
            throw new Error(`Status check failed: ${response.status}`);
        }
        return response.json();
    }

    async listModels() {
        const response = await fetch(`${this.baseUrl}/api/models`, {
            headers: this.headers,
        });
        if (!response.ok) {
            throw new Error(`List models failed: ${response.status}`);
        }
        const data = await response.json();
        return data.models || data;
    }

    async infer(model, prompt, maxTokens = 1024, temperature = 0.7) {
        const response = await fetch(`${this.baseUrl}/api/inference`, {
            method: 'POST',
            headers: this.headers,
            body: JSON.stringify({
                model,
                prompt,
                max_tokens: maxTokens,
                temperature,
                stream: false,
            }),
        });
        
        if (!response.ok) {
            const error = await response.text();
            throw new Error(`Inference failed: ${response.status} - ${error}`);
        }
        
        return response.json();
    }
}

// Main function
async function main() {
    console.log('============================================');
    console.log('AinosOS Node.js SDK - Basic Inference Example');
    console.log('============================================');

    const baseUrl = process.env.AINOS_URL || 'http://localhost:8080';
    const apiToken = process.env.AINOS_API_TOKEN || '';
    const client = new AinosClient(baseUrl, apiToken);

    try {
        // Step 1: Check status
        console.log('\n[1] Checking server status...');
        const status = await client.getStatus();
        console.log(`    Status: ${status.status}`);
        console.log(`    CPU: ${status.cpu}%`);
        console.log(`    Memory: ${status.memory}%`);

        // Step 2: List models
        console.log('\n[2] Listing available models...');
        const models = await client.listModels();
        
        let selectedModel = null;
        for (const model of models) {
            console.log(`    - ${model.name} [${model.status}]`);
            if (model.status === 'loaded' && !selectedModel) {
                selectedModel = model.id || model.model_id;
            }
        }
        
        if (!selectedModel) {
            console.log('    No loaded models available.');
            return;
        }
        console.log(`\n    Using model: ${selectedModel}`);

        // Step 3: Run inference
        console.log('\n[3] Running inference...');
        const prompt = 'Explain what artificial intelligence is in simple terms.';
        console.log(`    Prompt: ${prompt}`);

        const start = Date.now();
        const result = await client.infer(selectedModel, prompt, 200, 0.7);
        const elapsed = ((Date.now() - start) / 1000).toFixed(2);
        
        console.log(`\n    Response (${elapsed}s, ${result.tokens} tokens):`);
        console.log(`    ${result.text}`);
        console.log(`\n    Finish reason: ${result.finish_reason}`);

        console.log('\n============================================');
        console.log('Inference example completed successfully!');
        console.log('============================================');
    } catch (error) {
        console.error(`ERROR: ${error.message}`);
        process.exit(1);
    }
}

main();
```

### Run

```bash
cd examples/nodejs
npm install
node basic_inference.js
```

---

## 8. Error Handling / 错误处理

### Common Error Types

```python
# Python example: comprehensive error handling
import requests
from requests.exceptions import (
    RequestException,
    ConnectionError,
    Timeout,
    HTTPError,
)

try:
    response = requests.post(
        f"{BASE_URL}/api/inference",
        headers=headers,
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    
except ConnectionError:
    print("ERROR: Could not connect to AinosOS server.")
    print("  - Is the server running?")
    print("  - Check the URL and port.")
    
except Timeout:
    print("ERROR: Request timed out.")
    print("  - The model may be busy.")
    print("  - Try increasing the timeout.")
    print("  - Check if the model is still loading.")

except HTTPError as e:
    if e.response.status_code == 401:
        print("ERROR: Authentication failed.")
        print("  - Check your API token.")
        print("  - Ensure auth is configured correctly.")
    elif e.response.status_code == 429:
        print("ERROR: Rate limit exceeded.")
        print("  - Wait and retry.")
        print("  - Check your rate limit tier.")
    elif e.response.status_code == 400:
        error_detail = e.response.json().get("detail", "Bad request")
        print(f"ERROR: {error_detail}")
    else:
        print(f"ERROR: HTTP {e.response.status_code}")

except Exception as e:
    print(f"ERROR: Unexpected error: {e}")
```

### Error Handling by SDK

| Error Type | Python | Go | Rust | Java | C# | Node.js |
|-----------|--------|----|------|------|----|---------|
| Connection | `ConnectionError` | `net.ErrClosed` | `reqwest::Error` | `ConnectException` | `HttpRequestException` | `FetchError` |
| Timeout | `Timeout` | `context.DeadlineExceeded` | `tokio::time::error::Elapsed` | `SocketTimeoutException` | `TaskCanceledException` | `AbortError` |
| Auth | HTTP 401 | HTTP 401 | HTTP 401 | HTTP 401 | HTTP 401 | HTTP 401 |
| Rate Limit | HTTP 429 | HTTP 429 | HTTP 429 | HTTP 429 | HTTP 429 | HTTP 429 |
| Model | HTTP 400 | HTTP 400 | HTTP 400 | HTTP 400 | HTTP 400 | HTTP 400 |
| Server | HTTP 500 | HTTP 500 | HTTP 500 | HTTP 500 | HTTP 500 | HTTP 500 |

---

## 9. Running the Examples / 运行示例

### Quick Start Script

```bash
#!/bin/bash
# D:/Ainos/examples/run_all.sh
# Run all SDK examples
# ======================

set -euo pipefail

echo "AinosOS SDK Examples Runner"
echo "=========================="

# Check server
echo "Checking server connection..."
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/api/status || {
    echo "Server not running! Start with: python api_server.py"
    exit 1
}

# Python
echo ""
echo "1. Python SDK Example"
cd python
python basic_inference.py
cd ..

# Go
echo ""
echo "2. Go SDK Example"
cd go
go run basic_inference.go
cd ..

# Rust
echo ""
echo "3. Rust SDK Example"
cd rust
cargo run --release
cd ..

# Java
echo ""
echo "4. Java SDK Example"
cd java
mvn -q compile exec:java -Dexec.mainClass="ai.ainos.examples.BasicInference"
cd ..

# C#
echo ""
echo "5. C# SDK Example"
cd csharp
dotnet run
cd ..

# Node.js
echo ""
echo "6. Node.js SDK Example"
cd nodejs
npm install --silent
node basic_inference.js
cd ..

echo ""
echo "All examples completed!"
```

---

## 10. Best Practices / 最佳实践

### For Production Use

1. **Connection Pooling**: Reuse HTTP connections for multiple requests
2. **Timeout Handling**: Set appropriate timeouts (30s-300s depending on task)
3. **Retry Logic**: Implement exponential backoff for transient failures
4. **Batching**: Batch multiple prompts when possible
5. **Monitoring**: Track inference latency and error rates
6. **Rate Limiting**: Respect API rate limits
7. **Token Management**: Keep API tokens secure, rotate regularly
8. **Error Handling**: Handle all error types gracefully

### Performance Tips

```python
# 1. Connection pooling
import requests
session = requests.Session()
session.headers.update(headers)

# 2. Async requests
import asyncio
import aiohttp

async def batch_infer(prompts):
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = []
        for prompt in prompts:
            tasks.append(session.post(
                f"{BASE_URL}/api/inference",
                json={"model": model, "prompt": prompt},
            ))
        return await asyncio.gather(*tasks)

# 3. Streaming for long responses
# Use stream=True for better UX with long generations

# 4. Cache responses
import hashlib
cache = {}
def get_cached(prompt):
    key = hashlib.md5(prompt.encode()).hexdigest()
    return cache.get(key)
```

---

## 11. Troubleshooting / 故障排除

### Common Issues

| Issue | Likely Cause | Solution |
|-------|-------------|----------|
| Connection refused | Server not running | Start the server: `python api_server.py` |
| 401 Unauthorized | Invalid/missing token | Set `AINOS_API_TOKEN` environment variable |
| 404 Not Found | Wrong URL | Check `AINOS_URL` or base URL |
| Model not found | Wrong model ID | Check `GET /api/models` for available models |
| Model not loaded | Model not initialized | Load model via API or dashboard |
| Slow response | Model busy or GPU contention | Check GPU utilization, consider scaling |
| Out of memory | Too many concurrent requests | Reduce concurrency, unload unused models |
| Streaming not working | WebSocket not supported | Fall back to SSE, check proxy config |

### Debug Checklist

```bash
# 1. Is the server running?
curl http://localhost:8080/api/status

# 2. Are models loaded?
curl http://localhost:8080/api/models | python3 -m json.tool

# 3. Is the API token correct?
curl -H "Authorization: Bearer $AINOS_API_TOKEN" \
    http://localhost:8080/api/status

# 4. Can you run a simple inference?
curl -X POST http://localhost:8080/api/inference \
    -H "Content-Type: application/json" \
    -d '{"model":"ainos-llama-3.1-8b","prompt":"Hello","max_tokens":50}'

# 5. Check server logs
tail -50 /var/log/ainos/ainos.log

# 6. Check GPU status
nvidia-smi
```

---

*For more examples, visit [https://github.com/ainos-ai/examples](https://github.com/ainos-ai/examples).*

*更多示例请访问 [https://github.com/ainos-ai/examples](https://github.com/ainos-ai/examples)。*