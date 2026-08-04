# AinosOS Streaming Inference Tutorial / 流式推理教程

> **Version:** 1.0.0 | **Updated:** 2026-08-04
>
> Learn how to perform streaming inference with AinosOS using all 6 supported SDKs.
> 学习如何使用所有 6 种支持的 SDK 进行流式推理。

---

## Table of Contents / 目录

1. [Overview / 概述](#1-overview)
2. [Streaming Concepts / 流式概念](#2-streaming-concepts)
3. [Python SDK / Python SDK](#3-python-sdk)
4. [Go SDK / Go SDK](#4-go-sdk)
5. [Rust SDK / Rust SDK](#5-rust-sdk)
6. [Java SDK / Java SDK](#6-java-sdk)
7. [C# SDK / C# SDK](#7-c-sdk)
8. [Node.js SDK / Node.js SDK](#8-node-js-sdk)
9. [Backpressure Handling / 背压处理](#9-backpressure-handling)
10. [Cancellation / 取消](#10-cancellation)
11. [Error Handling / 错误处理](#11-error-handling)
12. [Best Practices / 最佳实践](#12-best-practices)

---

## 1. Overview / 概述

### What is Streaming Inference? / 什么是流式推理？

Streaming inference delivers model responses token by token as they are generated, rather than waiting for the complete response. This provides:

- **Lower latency** - See the first token faster
- **Better UX** - Real-time response display
- **Early termination** - Stop generation mid-response
- **Progressive rendering** - Show results as they arrive

流式推理逐 token 传输模型生成的响应，而不是等待完整响应生成完毕。这提供了：

- **更低的延迟** - 更快看到第一个 token
- **更好的用户体验** - 实时显示响应
- **提前终止** - 在响应中途停止生成
- **渐进式渲染** - 结果实时到达、实时显示

### Architecture / 架构

```
Client                    AinosOS Server
  |                             |
  |--- POST /api/inference ---->|  (stream: true)
  |    (or WebSocket connect)   |
  |                             |
  |<-- SSE: data: {"token": "H"}  |
  |<-- SSE: data: {"token": "e"}  |
  |<-- SSE: data: {"token": "l"}  |
  |<-- SSE: data: {"token": "l"}  |
  |<-- SSE: data: {"token": "o"}  |
  |<-- SSE: data: {"token": " "}  |
  |<-- SSE: data: {"token": "..."}|
  |<-- SSE: data: [DONE]        |
  |                             |
```

### Streaming Protocols / 流式协议

AinosOS supports two streaming protocols:

1. **Server-Sent Events (SSE)** - Simple HTTP-based streaming
2. **WebSocket** - Bidirectional streaming for advanced use cases

---

## 2. Streaming Concepts / 流式概念

### SSE vs WebSocket

| Feature | SSE | WebSocket |
|---------|-----|-----------|
| Direction | Server to client only | Bidirectional |
| Protocol | HTTP | WS/WSS |
| Auto-reconnect | Built-in | Manual |
| Binary data | Text only | Text + Binary |
| Browser support | Excellent | Excellent |
| Firewall friendly | Yes | Sometimes blocked |
| Complexity | Simple | Moderate |
| Use case | Streaming responses | Interactive chat |

### Stream Events

```json
// Token event (SSE format)
event: token
data: {"token": "Hello", "index": 0, "model": "ainos-llama-3.1-8b"}

// Done event
event: done
data: {"token_count": 150, "finish_reason": "stop"}

// Error event
event: error
data: {"error": "Model not found", "code": 404}
```

### WebSocket Message Format

```json
// Client -> Server
{
    "model": "ainos-llama-3.1-8b",
    "prompt": "Hello!",
    "max_tokens": 1024,
    "temperature": 0.7
}

// Server -> Client (token)
{
    "token": "Hello",
    "index": 0,
    "model": "ainos-llama-3.1-8b"
}

// Server -> Client (done)
{
    "done": true,
    "token_count": 150,
    "finish_reason": "stop"
}

// Server -> Client (error)
{
    "error": "Model not loaded"
}
```

---

## 3. Python SDK / Python SDK

### Installation

```bash
pip install ainos-sdk aiohttp
```

### SSE Streaming Example

```python
#!/usr/bin/env python3
"""
D:/Ainos/examples/python/streaming_inference.py
Python SDK Streaming Inference Example
=============================================
"""

import os
import sys
import json
import time
import signal
from typing import Optional, Callable

import requests
from sseclient import SSEClient


class AinosStreamingClient:
    """
    AinosOS streaming inference client.
    Supports both SSE and WebSocket streaming.
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_token: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token or os.environ.get("AINOS_API_TOKEN", "")
        self._cancelled = False
    
    def _get_headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers
    
    def stream_infer_sse(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        on_token: Callable = None,
        on_done: Callable = None,
        on_error: Callable = None,
    ) -> str:
        """
        Perform streaming inference using SSE.
        
        Args:
            model: Model ID
            prompt: Input prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            on_token: Callback for each token (token: str, index: int)
            on_done: Callback when generation is complete
            on_error: Callback for errors
        
        Returns:
            Full generated text
        """
        self._cancelled = False
        full_response = []
        
        payload = {
            "model": model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/api/inference",
                headers=self._get_headers(),
                json=payload,
                stream=True,
                timeout=300,
            )
            response.raise_for_status()
            
            client = SSEClient(response)
            
            for event in client.events():
                if self._cancelled:
                    break
                
                if event.event == "error" or event.data == "[DONE]":
                    if event.data == "[DONE]":
                        if on_done:
                            on_done({"token_count": len(full_response)})
                    elif on_error:
                        on_error({"error": event.data})
                    break
                
                try:
                    data = json.loads(event.data)
                    token = data.get("token", "")
                    index = data.get("index", len(full_response))
                    
                    full_response.append(token)
                    
                    if on_token:
                        on_token(token=token, index=index)
                        
                except json.JSONDecodeError:
                    # Plain text token
                    full_response.append(event.data)
                    if on_token:
                        on_token(token=event.data, index=len(full_response) - 1)
        
        except requests.exceptions.RequestException as e:
            if on_error:
                on_error({"error": str(e)})
        
        return "".join(full_response)
    
    async def stream_infer_websocket(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        on_token: Callable = None,
        on_done: Callable = None,
        on_error: Callable = None,
    ) -> str:
        """
        Perform streaming inference using WebSocket.
        Requires aiohttp.
        """
        import aiohttp
        
        self._cancelled = False
        full_response = []
        
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/ws/inference"
        
        headers = {}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.ws_connect(
                ws_url,
                timeout=300.0,
                max_msg_size=1024 * 1024,
            ) as ws:
                
                # Send request
                await ws.send_json({
                    "model": model,
                    "prompt": prompt,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                })
                
                # Receive tokens
                async for msg in ws:
                    if self._cancelled:
                        await ws.close()
                        break
                    
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = json.loads(msg.data)
                        except json.JSONDecodeError:
                            continue
                        
                        if "error" in data:
                            if on_error:
                                on_error(data)
                            break
                        
                        if data.get("done"):
                            if on_done:
                                on_done(data)
                            break
                        
                        token = data.get("token", "")
                        index = data.get("index", len(full_response))
                        
                        full_response.append(token)
                        
                        if on_token:
                            on_token(token=token, index=index)
                    
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        if on_error:
                            on_error({"error": str(ws.exception())})
                        break
        
        return "".join(full_response)
    
    def cancel(self):
        """Cancel ongoing streaming inference."""
        self._cancelled = True


def main():
    """Main example demonstrating streaming inference."""
    print("=" * 60)
    print("AinosOS Python SDK - Streaming Inference Example")
    print("=" * 60)
    
    client = AinosStreamingClient(
        base_url=os.environ.get("AINOS_URL", "http://localhost:8080"),
        api_token=os.environ.get("AINOS_API_TOKEN", ""),
    )
    
    # Setup signal handler for graceful cancellation
    signal.signal(signal.SIGINT, lambda sig, frame: client.cancel())
    
    # Define callbacks
    def on_token(token, index):
        print(token, end="", flush=True)
    
    def on_done(data):
        token_count = data.get("token_count", 0)
        print(f"\n\n[Generation complete: {token_count} tokens]")
    
    def on_error(error):
        print(f"\n\n[ERROR: {error.get('error', 'Unknown error')}]")
    
    # Example 1: Basic streaming
    print("\n[1] Basic SSE Streaming Inference")
    print("-" * 40)
    print("Prompt: Write a short paragraph about the future of AI.")
    print("Response: ", end="", flush=True)
    
    start_time = time.time()
    full_text = client.stream_infer_sse(
        model="ainos-llama-3.1-8b",
        prompt="Write a short paragraph about the future of AI.",
        max_tokens=200,
        temperature=0.7,
        on_token=on_token,
        on_done=on_done,
        on_error=on_error,
    )
    elapsed = time.time() - start_time
    print(f"Time: {elapsed:.2f}s | Total chars: {len(full_text)}")
    
    # Example 2: Multiple streaming requests
    print("\n\n[2] Multiple Streaming Requests")
    print("-" * 40)
    
    prompts = [
        "List three benefits of streaming inference.",
        "Explain the difference between SSE and WebSocket.",
    ]
    
    for i, prompt in enumerate(prompts, 1):
        print(f"\nPrompt {i}: {prompt}")
        print("Response: ", end="", flush=True)
        
        start_time = time.time()
        full_text = client.stream_infer_sse(
            model="ainos-llama-3.1-8b",
            prompt=prompt,
            max_tokens=100,
            temperature=0.8,
            on_token=on_token,
            on_done=on_done,
            on_error=on_error,
        )
        elapsed = time.time() - start_time
        print(f"Time: {elapsed:.2f}s")
    
    # Example 3: WebSocket streaming (if available)
    print("\n\n[3] WebSocket Streaming Inference")
    print("-" * 40)
    import asyncio
    
    async def run_ws_example():
        print("Prompt: What is the meaning of life?")
        print("Response: ", end="", flush=True)
        
        start_time = time.time()
        full_text = await client.stream_infer_websocket(
            model="ainos-llama-3.1-8b",
            prompt="What is the meaning of life?",
            max_tokens=100,
            temperature=0.7,
            on_token=on_token,
            on_done=on_done,
            on_error=on_error,
        )
        elapsed = time.time() - start_time
        print(f"\nTime: {elapsed:.2f}s | Total chars: {len(full_text)}")
    
    asyncio.run(run_ws_example())
    
    print("\n" + "=" * 60)
    print("Streaming inference example completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
```

### Streaming Response Display

```python
# Advanced: Real-time streaming with progress indicator
import sys
import threading
import itertools

def stream_with_progress(client, model, prompt, max_tokens=1024):
    """Stream with animated progress indicator."""
    done = threading.Event()
    spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    
    def show_progress():
        while not done.is_set():
            sys.stdout.write(f"\r{next(spinner)} Generating... ")
            sys.stdout.flush()
            done.wait(0.1)
    
    # Start progress thread
    progress_thread = threading.Thread(target=show_progress, daemon=True)
    progress_thread.start()
    
    # Stream
    full_text = ""
    def on_token(token, index):
        nonlocal full_text
        full_text += token
        # Clear progress line and show token
        sys.stdout.write(f"\rGenerating: {full_text[-50:]:<50}")
        sys.stdout.flush()
    
    def on_done(data):
        done.set()
        sys.stdout.write("\r" + " " * 70 + "\r")
        sys.stdout.flush()
        print(f"\nComplete! ({data.get('token_count', 0)} tokens)")
    
    client.stream_infer_sse(model, prompt, max_tokens, on_token=on_token, on_done=on_done)
    return full_text
```

---

## 4. Go SDK / Go SDK

### Installation

```bash
go get github.com/ainos-ai/ainos-sdk-go
```

### Complete Example

```go
// D:/Ainos/examples/go/streaming_inference.go
// Go SDK Streaming Inference Example
// ======================================

package main

import (
    "bufio"
    "bytes"
    "encoding/json"
    "fmt"
    "io"
    "net/http"
    "os"
    "os/signal"
    "strings"
    "syscall"
    "time"
    
    "github.com/gorilla/websocket"
)

// TokenEvent represents a streamed token
type TokenEvent struct {
    Token string `json:"token"`
    Index int    `json:"index"`
    Model string `json:"model"`
}

// DoneEvent represents completion
type DoneEvent struct {
    Done         bool   `json:"done"`
    TokenCount   int    `json:"token_count,omitempty"`
    FinishReason string `json:"finish_reason,omitempty"`
}

// ErrorEvent represents an error
type ErrorEvent struct {
    Error string `json:"error"`
    Code  int    `json:"code,omitempty"`
}

// StreamCallbacks define callbacks for streaming events
type StreamCallbacks struct {
    OnToken func(token string, index int)
    OnDone  func(data DoneEvent)
    OnError func(err error)
}

// AinosStreamingClient handles streaming inference
type AinosStreamingClient struct {
    baseURL   string
    apiToken  string
    cancelled bool
}

func NewStreamingClient(baseURL, apiToken string) *AinosStreamingClient {
    return &AinosStreamingClient{
        baseURL:  strings.TrimRight(baseURL, "/"),
        apiToken: apiToken,
    }
}

func (c *AinosStreamingClient) getHeaders() http.Header {
    headers := http.Header{}
    headers.Set("Content-Type", "application/json")
    headers.Set("Accept", "text/event-stream")
    if c.apiToken != "" {
        headers.Set("Authorization", "Bearer "+c.apiToken)
    }
    return headers
}

// StreamInferSSE performs streaming inference via SSE
func (c *AinosStreamingClient) StreamInferSSE(
    model, prompt string,
    maxTokens int,
    temperature float64,
    callbacks StreamCallbacks,
) (string, error) {
    c.cancelled = false
    
    payload := map[string]interface{}{
        "model":       model,
        "prompt":      prompt,
        "max_tokens":  maxTokens,
        "temperature": temperature,
        "stream":      true,
    }
    
    body, err := json.Marshal(payload)
    if err != nil {
        return "", fmt.Errorf("failed to marshal payload: %w", err)
    }
    
    req, err := http.NewRequest("POST", c.baseURL+"/api/inference", bytes.NewReader(body))
    if err != nil {
        return "", fmt.Errorf("failed to create request: %w", err)
    }
    req.Header = c.getHeaders()
    
    client := &http.Client{Timeout: 300 * time.Second}
    resp, err := client.Do(req)
    if err != nil {
        return "", fmt.Errorf("failed to send request: %w", err)
    }
    defer resp.Body.Close()
    
    if resp.StatusCode != http.StatusOK {
        bodyBytes, _ := io.ReadAll(resp.Body)
        return "", fmt.Errorf("server error %d: %s", resp.StatusCode, string(bodyBytes))
    }
    
    var fullResponse strings.Builder
    reader := bufio.NewReader(resp.Body)
    
    for {
        if c.cancelled {
            break
        }
        
        line, err := reader.ReadString('\n')
        if err != nil {
            if err == io.EOF {
                break
            }
            return fullResponse.String(), fmt.Errorf("read error: %w", err)
        }
        
        line = strings.TrimSpace(line)
        
        if strings.HasPrefix(line, "data: ") {
            data := strings.TrimPrefix(line, "data: ")
            
            if data == "[DONE]" {
                if callbacks.OnDone != nil {
                    callbacks.OnDone(DoneEvent{
                        Done:         true,
                        TokenCount:   strings.Count(fullResponse.String(), " "),
                        FinishReason: "stop",
                    })
                }
                break
            }
            
            var tokenEvent TokenEvent
            if err := json.Unmarshal([]byte(data), &tokenEvent); err == nil {
                fullResponse.WriteString(tokenEvent.Token)
                if callbacks.OnToken != nil {
                    callbacks.OnToken(tokenEvent.Token, tokenEvent.Index)
                }
            }
        } else if strings.HasPrefix(line, "event: error") {
            // Read next line for error data
            errorLine, _ := reader.ReadString('\n')
            errorLine = strings.TrimSpace(errorLine)
            if strings.HasPrefix(errorLine, "data: ") {
                errorData := strings.TrimPrefix(errorLine, "data: ")
                if callbacks.OnError != nil {
                    callbacks.OnError(fmt.Errorf("%s", errorData))
                }
            }
            break
        }
    }
    
    return fullResponse.String(), nil
}

// StreamInferWS performs streaming inference via WebSocket
func (c *AinosStreamingClient) StreamInferWS(
    model, prompt string,
    maxTokens int,
    temperature float64,
    callbacks StreamCallbacks,
) (string, error) {
    c.cancelled = false
    
    // Convert URL to WebSocket URL
    wsURL := strings.Replace(c.baseURL, "http://", "ws://", 1)
    wsURL = strings.Replace(wsURL, "https://", "wss://", 1)
    wsURL = wsURL + "/ws/inference"
    
    header := http.Header{}
    if c.apiToken != "" {
        header.Set("Authorization", "Bearer "+c.apiToken)
    }
    
    conn, _, err := websocket.DefaultDialer.Dial(wsURL, header)
    if err != nil {
        return "", fmt.Errorf("websocket connection failed: %w", err)
    }
    defer conn.Close()
    
    // Send request
    request := map[string]interface{}{
        "model":       model,
        "prompt":      prompt,
        "max_tokens":  maxTokens,
        "temperature": temperature,
    }
    if err := conn.WriteJSON(request); err != nil {
        return "", fmt.Errorf("failed to send request: %w", err)
    }
    
    var fullResponse strings.Builder
    
    for {
        if c.cancelled {
            conn.WriteMessage(websocket.CloseMessage, []byte{})
            break
        }
        
        _, message, err := conn.ReadMessage()
        if err != nil {
            break
        }
        
        var data map[string]interface{}
        if err := json.Unmarshal(message, &data); err != nil {
            continue
        }
        
        if errMsg, ok := data["error"]; ok {
            if callbacks.OnError != nil {
                callbacks.OnError(fmt.Errorf("%v", errMsg))
            }
            break
        }
        
        if done, ok := data["done"]; ok && done.(bool) {
            if callbacks.OnDone != nil {
                callbacks.OnDone(DoneEvent{
                    Done:       true,
                    TokenCount: data["token_count"].(int),
                })
            }
            break
        }
        
        if token, ok := data["token"]; ok {
            tokenStr := token.(string)
            fullResponse.WriteString(tokenStr)
            if callbacks.OnToken != nil {
                callbacks.OnToken(tokenStr, int(data["index"].(float64)))
            }
        }
    }
    
    return fullResponse.String(), nil
}

func (c *AinosStreamingClient) Cancel() {
    c.cancelled = true
}

func main() {
    fmt.Println("============================================")
    fmt.Println("AinosOS Go SDK - Streaming Inference Example")
    fmt.Println("============================================")
    
    baseURL := getEnv("AINOS_URL", "http://localhost:8080")
    apiToken := getEnv("AINOS_API_TOKEN", "")
    client := NewStreamingClient(baseURL, apiToken)
    
    // Handle Ctrl+C
    sigChan := make(chan os.Signal, 1)
    signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
    go func() {
        <-sigChan
        fmt.Println("\n\nCancelling...")
        client.Cancel()
    }()
    
    // Callbacks
    callbacks := StreamCallbacks{
        OnToken: func(token string, index int) {
            fmt.Print(token)
        },
        OnDone: func(data DoneEvent) {
            fmt.Printf("\n\n[Done: %d tokens, reason: %s]\n",
                data.TokenCount, data.FinishReason)
        },
        OnError: func(err error) {
            fmt.Printf("\n\n[Error: %v]\n", err)
        },
    }
    
    // Example 1: SSE Streaming
    fmt.Println("\n[1] SSE Streaming Inference")
    fmt.Println("Prompt: Tell me a short story about a robot.")
    fmt.Print("Response: ")
    
    start := time.Now()
    fullText, err := client.StreamInferSSE(
        "ainos-llama-3.1-8b",
        "Tell me a short story about a robot.",
        200, 0.7, callbacks,
    )
    elapsed := time.Since(start)
    
    if err != nil {
        fmt.Printf("Error: %v\n", err)
    } else {
        fmt.Printf("\nTime: %.2fs | Characters: %d\n",
            elapsed.Seconds(), len(fullText))
    }
    
    // Example 2: WebSocket Streaming
    fmt.Println("\n[2] WebSocket Streaming Inference")
    fmt.Println("Prompt: What is the future of AI?")
    fmt.Print("Response: ")
    
    start = time.Now()
    fullText, err = client.StreamInferWS(
        "ainos-llama-3.1-8b",
        "What is the future of AI?",
        200, 0.7, callbacks,
    )
    elapsed = time.Since(start)
    
    if err != nil {
        fmt.Printf("Error: %v\n", err)
    } else {
        fmt.Printf("\nTime: %.2fs | Characters: %d\n",
            elapsed.Seconds(), len(fullText))
    }
    
    fmt.Println("\n============================================")
    fmt.Println("Streaming example completed!")
    fmt.Println("============================================")
}

func getEnv(key, fallback string) string {
    if value, ok := os.LookupEnv(key); ok {
        return value
    }
    return fallback
}
```

---

## 5. Rust SDK / Rust SDK

### Cargo.toml

```toml
[package]
name = "ainos-streaming-inference"
version = "1.0.0"
edition = "2021"

[dependencies]
ainos-sdk = "1.0"
reqwest = { version = "0.12", features = ["json", "stream"] }
tokio = { version = "1", features = ["full"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
futures-util = "0.3"
tokio-tungstenite = { version = "0.21", features = ["native-tls"] }
url = "2"
anyhow = "1"
```

### Complete Example

```rust
// D:/Ainos/examples/rust/streaming_inference.rs
// Rust SDK Streaming Inference Example
// =======================================

use anyhow::{Context, Result};
use futures_util::StreamExt;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::env;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Instant;

#[derive(Debug, Serialize)]
struct InferenceRequest {
    model: String,
    prompt: String,
    max_tokens: u32,
    temperature: f64,
    stream: bool,
}

#[derive(Debug, Deserialize)]
struct TokenData {
    token: Option<String>,
    index: Option<u32>,
    done: Option<bool>,
    error: Option<String>,
    token_count: Option<u32>,
    finish_reason: Option<String>,
}

struct AinosStreamingClient {
    base_url: String,
    api_token: String,
    cancelled: Arc<AtomicBool>,
}

impl AinosStreamingClient {
    fn new(base_url: String, api_token: String) -> Self {
        Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            api_token,
            cancelled: Arc::new(AtomicBool::new(false)),
        }
    }

    fn get_cancelled_flag(&self) -> Arc<AtomicBool> {
        self.cancelled.clone()
    }

    fn cancel(&self) {
        self.cancelled.store(true, Ordering::SeqCst);
    }

    fn headers(&self) -> reqwest::header::HeaderMap {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert(
            reqwest::header::CONTENT_TYPE,
            "application/json".parse().unwrap(),
        );
        headers.insert(
            reqwest::header::ACCEPT,
            "text/event-stream".parse().unwrap(),
        );
        if !self.api_token.is_empty() {
            headers.insert(
                reqwest::header::AUTHORIZATION,
                format!("Bearer {}", self.api_token).parse().unwrap(),
            );
        }
        headers
    }

    async fn stream_infer_sse(
        &self,
        model: &str,
        prompt: &str,
        max_tokens: u32,
        temperature: f64,
        on_token: impl Fn(String, u32),
        on_done: impl Fn(u32, String),
        on_error: impl Fn(String),
    ) -> Result<String> {
        let request = InferenceRequest {
            model: model.to_string(),
            prompt: prompt.to_string(),
            max_tokens,
            temperature,
            stream: true,
        };

        let client = Client::builder()
            .timeout(std::time::Duration::from_secs(300))
            .build()?;

        let response = client
            .post(format!("{}/api/inference", self.base_url))
            .headers(self.headers())
            .json(&request)
            .send()
            .await
            .context("Failed to send inference request")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await?;
            anyhow::bail!("Server error {}: {}", status, body);
        }

        let mut full_response = String::new();
        let mut stream = response.bytes_stream();

        let cancelled = self.cancelled.clone();
        let mut buffer = String::new();

        while let Some(chunk) = stream.next().await {
            if cancelled.load(Ordering::SeqCst) {
                break;
            }

            let chunk = chunk.context("Failed to read stream chunk")?;
            let chunk_str = String::from_utf8_lossy(&chunk);
            buffer.push_str(&chunk_str);

            // Process complete lines
            while let Some(newline_pos) = buffer.find('\n') {
                let line = buffer[..newline_pos].trim().to_string();
                buffer = buffer[newline_pos + 1..].to_string();

                if line.starts_with("data: ") {
                    let data = line.trim_start_matches("data: ");

                    if data == "[DONE]" {
                        on_done(
                            full_response.split_whitespace().count() as u32,
                            "stop".to_string(),
                        );
                        return Ok(full_response);
                    }

                    if let Ok(token_data) =
                        serde_json::from_str::<TokenData>(data)
                    {
                        if let Some(err) = token_data.error {
                            on_error(err);
                            return Ok(full_response);
                        }

                        if let Some(token) = token_data.token {
                            full_response.push_str(&token);
                            let index = token_data.index.unwrap_or(0);
                            on_token(token, index);
                        }
                    }
                }
            }
        }

        Ok(full_response)
    }

    async fn stream_infer_ws(
        &self,
        model: &str,
        prompt: &str,
        max_tokens: u32,
        temperature: f64,
        on_token: impl Fn(String, u32),
        on_done: impl Fn(u32, String),
        on_error: impl Fn(String),
    ) -> Result<String> {
        use tokio_tungstenite::connect_async;
        use tokio_tungstenite::tungstenite::Message;
        use url::Url;

        let ws_url = self
            .base_url
            .replace("http://", "ws://")
            .replace("https://", "wss://");
        let ws_url = format!("{}/ws/inference", ws_url);

        let (ws_stream, _) = connect_async(Url::parse(&ws_url)?)
            .await
            .context("WebSocket connection failed")?;

        let (mut write, mut read) = ws_stream.split();

        // Send request
        let request = serde_json::json!({
            "model": model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        });
        write
            .send(Message::Text(request.to_string()))
            .await
            .context("Failed to send WS message")?;

        let mut full_response = String::new();
        let cancelled = self.cancelled.clone();

        while let Some(msg) = read.next().await {
            if cancelled.load(Ordering::SeqCst) {
                write
                    .send(Message::Close(None))
                    .await
                    .ok();
                break;
            }

            let msg = msg.context("WebSocket error")?;
            if let Message::Text(text) = msg {
                if let Ok(data) =
                    serde_json::from_str::<TokenData>(&text)
                {
                    if let Some(err) = data.error {
                        on_error(err);
                        break;
                    }

                    if data.done.unwrap_or(false) {
                        on_done(
                            data.token_count.unwrap_or(0),
                            data.finish_reason
                                .unwrap_or_else(|| "stop".to_string()),
                        );
                        break;
                    }

                    if let Some(token) = data.token {
                        full_response.push_str(&token);
                        on_token(token, data.index.unwrap_or(0));
                    }
                }
            }
        }

        Ok(full_response)
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    println!("============================================");
    println!("AinosOS Rust SDK - Streaming Inference Example");
    println!("============================================");

    let base_url =
        env::var("AINOS_URL").unwrap_or_else(|_| "http://localhost:8080".to_string());
    let api_token = env::var("AINOS_API_TOKEN").unwrap_or_default();
    let client = AinosStreamingClient::new(base_url, api_token);

    let cancelled = client.get_cancelled_flag();

    // Handle Ctrl+C
    tokio::spawn(async move {
        tokio::signal::ctrl_c().await.unwrap();
        println!("\n\nCancelling...");
        cancelled.store(true, Ordering::SeqCst);
    });

    // Example 1: SSE Streaming
    println!("\n[1] SSE Streaming Inference");
    println!("Prompt: What are the benefits of streaming?");
    print!("Response: ");

    let start = Instant::now();
    let full_text = client
        .stream_infer_sse(
            "ainos-llama-3.1-8b",
            "What are the benefits of streaming?",
            200,
            0.7,
            |token, _index| {
                print!("{}", token);
                use std::io::Write;
                std::io::stdout().flush().ok();
            },
            |count, reason| {
                println!("\n\n[Done: {} tokens, reason: {}]", count, reason);
            },
            |err| {
                eprintln!("\n\n[Error: {}]", err);
            },
        )
        .await?;

    let elapsed = start.elapsed();
    println!("Time: {:.2}s | Characters: {}", elapsed.as_secs_f64(), full_text.len());

    // Example 2: WebSocket Streaming
    println!("\n[2] WebSocket Streaming Inference");
    println!("Prompt: Explain the concept of backpressure.");
    print!("Response: ");

    let start = Instant::now();
    let full_text = client
        .stream_infer_ws(
            "ainos-llama-3.1-8b",
            "Explain the concept of backpressure.",
            200,
            0.7,
            |token, _index| {
                print!("{}", token);
                use std::io::Write;
                std::io::stdout().flush().ok();
            },
            |count, reason| {
                println!(
                    "\n\n[Done: {} tokens, reason: {}]",
                    count, reason
                );
            },
            |err| {
                eprintln!("\n\n[Error: {}]", err);
            },
        )
        .await?;

    let elapsed = start.elapsed();
    println!("Time: {:.2}s | Characters: {}", elapsed.as_secs_f64(), full_text.len());

    println!("\n============================================");
    println!("Streaming example completed!");
    println!("============================================");

    Ok(())
}
```

---

## 6. Java SDK / Java SDK

### Complete Example

```java
// D:/Ainos/examples/java/StreamingInference.java
// Java SDK Streaming Inference Example
// =======================================

package ai.ainos.examples;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.WebSocket;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.concurrent.*;
import java.util.function.BiConsumer;
import java.util.function.Consumer;

public class StreamingInference {
    
    private static final Gson GSON = new Gson();
    
    // Callbacks interface
    interface StreamCallbacks {
        void onToken(String token, int index);
        void onDone(int tokenCount, String finishReason);
        void onError(String error);
    }
    
    static class AinosStreamingClient {
        private final String baseUrl;
        private final String apiToken;
        private final HttpClient httpClient;
        private volatile boolean cancelled = false;
        
        AinosStreamingClient(String baseUrl, String apiToken) {
            this.baseUrl = baseUrl.replaceAll("/+$", "");
            this.apiToken = apiToken;
            this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();
        }
        
        void cancel() {
            this.cancelled = true;
        }
        
        HttpRequest.Builder requestBuilder(String path) {
            HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + path))
                .header("Content-Type", "application/json")
                .header("Accept", "text/event-stream")
                .timeout(Duration.ofSeconds(300));
            
            if (apiToken != null && !apiToken.isEmpty()) {
                builder.header("Authorization", "Bearer " + apiToken);
            }
            
            return builder;
        }
        
        String streamInferSSE(
            String model,
            String prompt,
            int maxTokens,
            double temperature,
            StreamCallbacks callbacks
        ) throws Exception {
            cancelled = false;
            
            JsonObject payload = new JsonObject();
            payload.addProperty("model", model);
            payload.addProperty("prompt", prompt);
            payload.addProperty("max_tokens", maxTokens);
            payload.addProperty("temperature", temperature);
            payload.addProperty("stream", true);
            
            HttpRequest request = requestBuilder("/api/inference")
                .POST(HttpRequest.BodyPublishers.ofString(GSON.toJson(payload)))
                .build();
            
            HttpResponse<InputStreamReader> response = httpClient.send(
                request, HttpResponse.BodyHandlers.ofInputStream()
            );
            
            if (response.statusCode() != 200) {
                String errorBody = new BufferedReader(
                    new InputStreamReader(response.body()))
                    .lines().reduce("", (a, b) -> a + b);
                throw new RuntimeException("Server error " + 
                    response.statusCode() + ": " + errorBody);
            }
            
            StringBuilder fullResponse = new StringBuilder();
            BufferedReader reader = new BufferedReader(
                new InputStreamReader(response.body()));
            
            String line;
            while ((line = reader.readLine()) != null) {
                if (cancelled) break;
                
                if (line.startsWith("data: ")) {
                    String data = line.substring(6).trim();
                    
                    if ("[DONE]".equals(data)) {
                        if (callbacks != null) {
                            callbacks.onDone(
                                fullResponse.toString().split("\\s+").length,
                                "stop"
                            );
                        }
                        break;
                    }
                    
                    try {
                        JsonObject tokenData = JsonParser.parseString(data)
                            .getAsJsonObject();
                        
                        if (tokenData.has("error")) {
                            if (callbacks != null) {
                                callbacks.onError(
                                    tokenData.get("error").getAsString());
                            }
                            break;
                        }
                        
                        if (tokenData.has("token")) {
                            String token = tokenData.get("token").getAsString();
                            int index = tokenData.has("index") ? 
                                tokenData.get("index").getAsInt() : 
                                fullResponse.length();
                            
                            fullResponse.append(token);
                            
                            if (callbacks != null) {
                                callbacks.onToken(token, index);
                            }
                        }
                    } catch (Exception e) {
                        // Plain text token
                        fullResponse.append(data);
                        if (callbacks != null) {
                            callbacks.onToken(data, fullResponse.length());
                        }
                    }
                }
            }
            
            return fullResponse.toString();
        }
        
        // WebSocket streaming (Java 11+)
        CompletableFuture<String> streamInferWS(
            String model,
            String prompt,
            int maxTokens,
            double temperature,
            StreamCallbacks callbacks
        ) {
            cancelled = false;
            StringBuilder fullResponse = new StringBuilder();
            CompletableFuture<String> future = new CompletableFuture<>();
            
            String wsUrl = baseUrl
                .replace("http://", "ws://")
                .replace("https://", "wss://") + "/ws/inference";
            
            WebSocket.Builder wsBuilder = httpClient.newWebSocketBuilder();
            if (apiToken != null && !apiToken.isEmpty()) {
                wsBuilder.header("Authorization", "Bearer " + apiToken);
            }
            
            JsonObject requestPayload = new JsonObject();
            requestPayload.addProperty("model", model);
            requestPayload.addProperty("prompt", prompt);
            requestPayload.addProperty("max_tokens", maxTokens);
            requestPayload.addProperty("temperature", temperature);
            
            wsBuilder.buildAsync(URI.create(wsUrl), new WebSocket.Listener() {
                @Override
                public CompletionStage<?> onText(
                    WebSocket webSocket, 
                    CharSequence data, 
                    boolean last
                ) {
                    if (cancelled) {
                        webSocket.sendClose(1000, "Cancelled");
                        return CompletableFuture.completedFuture(null);
                    }
                    
                    try {
                        JsonObject json = JsonParser.parseString(
                            data.toString()).getAsJsonObject();
                        
                        if (json.has("error")) {
                            if (callbacks != null) {
                                callbacks.onError(json.get("error").getAsString());
                            }
                            future.complete(fullResponse.toString());
                            return CompletableFuture.completedFuture(null);
                        }
                        
                        if (json.has("done") && json.get("done").getAsBoolean()) {
                            if (callbacks != null) {
                                callbacks.onDone(
                                    json.has("token_count") ? 
                                        json.get("token_count").getAsInt() : 0,
                                    json.has("finish_reason") ? 
                                        json.get("finish_reason").getAsString() : "stop"
                                );
                            }
                            future.complete(fullResponse.toString());
                            return CompletableFuture.completedFuture(null);
                        }
                        
                        if (json.has("token")) {
                            String token = json.get("token").getAsString();
                            int index = json.has("index") ? 
                                json.get("index").getAsInt() : fullResponse.length();
                            
                            fullResponse.append(token);
                            
                            if (callbacks != null) {
                                callbacks.onToken(token, index);
                            }
                        }
                    } catch (Exception e) {
                        // Ignore parse errors
                    }
                    
                    return CompletableFuture.completedFuture(null);
                }
                
                @Override
                public void onError(WebSocket webSocket, Throwable error) {
                    if (callbacks != null) {
                        callbacks.onError(error.getMessage());
                    }
                    future.completeExceptionally(error);
                }
            });
            
            return future;
        }
    }
    
    public static void main(String[] args) throws Exception {
        System.out.println("============================================");
        System.out.println("AinosOS Java SDK - Streaming Inference Example");
        System.out.println("============================================");
        
        String baseUrl = System.getenv().getOrDefault("AINOS_URL", 
            "http://localhost:8080");
        String apiToken = System.getenv().getOrDefault("AINOS_API_TOKEN", "");
        
        AinosStreamingClient client = new AinosStreamingClient(baseUrl, apiToken);
        
        // Setup shutdown hook
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            System.out.println("\n\nCancelling...");
            client.cancel();
        }));
        
        // Callbacks
        StreamCallbacks callbacks = new StreamCallbacks() {
            @Override
            public void onToken(String token, int index) {
                System.out.print(token);
                System.out.flush();
            }
            
            @Override
            public void onDone(int tokenCount, String finishReason) {
                System.out.printf(
                    "\n\n[Done: %d tokens, reason: %s]%n", 
                    tokenCount, finishReason);
            }
            
            @Override
            public void onError(String error) {
                System.out.printf("\n\n[Error: %s]%n", error);
            }
        };
        
        // Example 1: SSE Streaming
        System.out.println("\n[1] SSE Streaming Inference");
        System.out.println("Prompt: Write a poem about coding.");
        System.out.print("Response: ");
        
        long start = System.currentTimeMillis();
        String fullText = client.streamInferSSE(
            "ainos-llama-3.1-8b",
            "Write a poem about coding.",
            200, 0.7, callbacks
        );
        long elapsed = System.currentTimeMillis() - start;
        System.out.printf("\nTime: %.2fs | Characters: %d%n", 
            elapsed / 1000.0, fullText.length());
        
        // Example 2: WebSocket Streaming
        System.out.println("\n[2] WebSocket Streaming Inference");
        System.out.println("Prompt: Explain REST API in simple terms.");
        System.out.print("Response: ");
        
        start = System.currentTimeMillis();
        fullText = client.streamInferWS(
            "ainos-llama-3.1-8b",
            "Explain REST API in simple terms.",
            200, 0.7, callbacks
        ).get(300, TimeUnit.SECONDS);
        elapsed = System.currentTimeMillis() - start;
        System.out.printf("\nTime: %.2fs | Characters: %d%n", 
            elapsed / 1000.0, fullText.length());
        
        System.out.println("\n============================================");
        System.out.println("Streaming example completed!");
        System.out.println("============================================");
    }
}
```

---

## 7. C# SDK / C# SDK

### Complete Example

```csharp
// D:/Ainos/examples/csharp/StreamingInference.cs
// C# SDK Streaming Inference Example
// ======================================

using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;
using System.Net.WebSockets;

namespace AinosStreamingExamples
{
    // Data classes
    public class TokenData
    {
        [JsonPropertyName("token")]
        public string? Token { get; set; }
        
        [JsonPropertyName("index")]
        public int? Index { get; set; }
        
        [JsonPropertyName("done")]
        public bool? Done { get; set; }
        
        [JsonPropertyName("error")]
        public string? Error { get; set; }
        
        [JsonPropertyName("token_count")]
        public int? TokenCount { get; set; }
        
        [JsonPropertyName("finish_reason")]
        public string? FinishReason { get; set; }
    }
    
    public class StreamCallbacks
    {
        public Action<string, int>? OnToken { get; set; }
        public Action<int, string>? OnDone { get; set; }
        public Action<string>? OnError { get; set; }
    }
    
    class AinosStreamingClient : IDisposable
    {
        private readonly HttpClient _httpClient;
        private readonly string _baseUrl;
        private readonly string _apiToken;
        private volatile bool _cancelled;
        private ClientWebSocket? _ws;
        
        private static readonly JsonSerializerOptions _jsonOptions = new()
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        };
        
        public AinosStreamingClient(string baseUrl, string apiToken)
        {
            _baseUrl = baseUrl.TrimEnd('/');
            _apiToken = apiToken;
            _httpClient = new HttpClient
            {
                Timeout = TimeSpan.FromMinutes(5)
            };
        }
        
        public void Cancel()
        {
            _cancelled = true;
            _ws?.Abort();
        }
        
        private void AddHeaders(HttpRequestMessage request)
        {
            request.Headers.Add("Content-Type", "application/json");
            request.Headers.Add("Accept", "text/event-stream");
            if (!string.IsNullOrEmpty(_apiToken))
            {
                request.Headers.Add("Authorization", $"Bearer {_apiToken}");
            }
        }
        
        public async Task<string> StreamInferSSE(
            string model,
            string prompt,
            int maxTokens = 1024,
            double temperature = 0.7,
            StreamCallbacks? callbacks = null,
            CancellationToken cancellationToken = default)
        {
            _cancelled = false;
            var fullResponse = new StringBuilder();
            
            var payload = new
            {
                model = model,
                prompt = prompt,
                max_tokens = maxTokens,
                temperature = temperature,
                stream = true
            };
            
            var content = new StringContent(
                JsonSerializer.Serialize(payload, _jsonOptions),
                Encoding.UTF8,
                "application/json");
            
            var request = new HttpRequestMessage(HttpMethod.Post, 
                $"{_baseUrl}/api/inference")
            {
                Content = content
            };
            AddHeaders(request);
            
            using var response = await _httpClient.SendAsync(
                request, 
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken);
            
            response.EnsureSuccessStatusCode();
            
            using var stream = await response.Content.ReadAsStreamAsync();
            using var reader = new System.IO.StreamReader(stream);
            
            string? line;
            while ((line = await reader.ReadLineAsync()) != null)
            {
                if (_cancelled || cancellationToken.IsCancellationRequested)
                    break;
                
                if (line.StartsWith("data: "))
                {
                    var data = line[6..].Trim();
                    
                    if (data == "[DONE]")
                    {
                        callbacks?.OnDone?.Invoke(
                            fullResponse.ToString().Split(' ').Length,
                            "stop");
                        break;
                    }
                    
                    try
                    {
                        var tokenData = JsonSerializer.Deserialize<TokenData>(
                            data, _jsonOptions);
                        
                        if (tokenData?.Error != null)
                        {
                            callbacks?.OnError?.Invoke(tokenData.Error);
                            break;
                        }
                        
                        if (tokenData?.Token != null)
                        {
                            fullResponse.Append(tokenData.Token);
                            callbacks?.OnToken?.Invoke(
                                tokenData.Token, 
                                tokenData.Index ?? fullResponse.Length);
                        }
                    }
                    catch (JsonException)
                    {
                        // Plain text token
                        fullResponse.Append(data);
                        callbacks?.OnToken?.Invoke(data, fullResponse.Length);
                    }
                }
            }
            
            return fullResponse.ToString();
        }
        
        public async Task<string> StreamInferWS(
            string model,
            string prompt,
            int maxTokens = 1024,
            double temperature = 0.7,
            StreamCallbacks? callbacks = null,
            CancellationToken cancellationToken = default)
        {
            _cancelled = false;
            var fullResponse = new StringBuilder();
            
            var wsUrl = _baseUrl
                .Replace("http://", "ws://")
                .Replace("https://", "wss://") + "/ws/inference";
            
            _ws = new ClientWebSocket();
            if (!string.IsNullOrEmpty(_apiToken))
            {
                _ws.Options.SetRequestHeader("Authorization", 
                    $"Bearer {_apiToken}");
            }
            
            await _ws.ConnectAsync(new Uri(wsUrl), cancellationToken);
            
            // Send request
            var requestPayload = JsonSerializer.Serialize(new
            {
                model = model,
                prompt = prompt,
                max_tokens = maxTokens,
                temperature = temperature
            }, _jsonOptions);
            
            var requestBytes = Encoding.UTF8.GetBytes(requestPayload);
            await _ws.SendAsync(
                new ArraySegment<byte>(requestBytes),
                WebSocketMessageType.Text,
                true,
                cancellationToken);
            
            // Receive tokens
            var buffer = new byte[1024 * 64];
            
            while (_ws.State == WebSocketState.Open && !_cancelled)
            {
                var result = await _ws.ReceiveAsync(
                    new ArraySegment<byte>(buffer),
                    cancellationToken);
                
                if (result.MessageType == WebSocketMessageType.Close)
                    break;
                
                var text = Encoding.UTF8.GetString(buffer, 0, result.Count);
                
                try
                {
                    var tokenData = JsonSerializer.Deserialize<TokenData>(
                        text, _jsonOptions);
                    
                    if (tokenData?.Error != null)
                    {
                        callbacks?.OnError?.Invoke(tokenData.Error);
                        break;
                    }
                    
                    if (tokenData?.Done == true)
                    {
                        callbacks?.OnDone?.Invoke(
                            tokenData.TokenCount ?? 0,
                            tokenData.FinishReason ?? "stop");
                        break;
                    }
                    
                    if (tokenData?.Token != null)
                    {
                        fullResponse.Append(tokenData.Token);
                        callbacks?.OnToken?.Invoke(
                            tokenData.Token, 
                            tokenData.Index ?? fullResponse.Length);
                    }
                }
                catch (JsonException) { }
            }
            
            return fullResponse.ToString();
        }
        
        public void Dispose()
        {
            _httpClient.Dispose();
            _ws?.Dispose();
        }
    }
    
    class Program
    {
        static async Task Main(string[] args)
        {
            Console.WriteLine("============================================");
            Console.WriteLine("AinosOS C# SDK - Streaming Inference Example");
            Console.WriteLine("============================================");
            
            var baseUrl = Environment.GetEnvironmentVariable("AINOS_URL") 
                ?? "http://localhost:8080";
            var apiToken = Environment.GetEnvironmentVariable("AINOS_API_TOKEN") 
                ?? "";
            
            using var cts = new CancellationTokenSource();
            Console.CancelKeyPress += (sender, e) =>
            {
                Console.WriteLine("\n\nCancelling...");
                cts.Cancel();
                e.Cancel = true;
            };
            
            using var client = new AinosStreamingClient(baseUrl, apiToken);
            
            var callbacks = new StreamCallbacks
            {
                OnToken = (token, index) =>
                {
                    Console.Write(token);
                    Console.Out.Flush();
                },
                OnDone = (count, reason) =>
                {
                    Console.Write($"\n\n[Done: {count} tokens, reason: {reason}]");
                },
                OnError = (error) =>
                {
                    Console.Write($"\n\n[Error: {error}]");
                }
            };
            
            // Example 1: SSE Streaming
            Console.WriteLine("\n[1] SSE Streaming Inference");
            Console.WriteLine("Prompt: What is the meaning of life?");
            Console.Write("Response: ");
            
            var start = DateTime.Now;
            var fullText = await client.StreamInferSSE(
                "ainos-llama-3.1-8b",
                "What is the meaning of life?",
                200, 0.7, callbacks, cts.Token);
            var elapsed = DateTime.Now - start;
            Console.WriteLine($"\nTime: {elapsed.TotalSeconds:F2}s | " +
                $"Characters: {fullText.Length}");
            
            // Example 2: WebSocket Streaming
            Console.WriteLine("\n[2] WebSocket Streaming Inference");
            Console.WriteLine("Prompt: Explain the concept of streaming.");
            Console.Write("Response: ");
            
            start = DateTime.Now;
            fullText = await client.StreamInferWS(
                "ainos-llama-3.1-8b",
                "Explain the concept of streaming.",
                200, 0.7, callbacks, cts.Token);
            elapsed = DateTime.Now - start;
            Console.WriteLine($"\nTime: {elapsed.TotalSeconds:F2}s | " +
                $"Characters: {fullText.Length}");
            
            Console.WriteLine("\n============================================");
            Console.WriteLine("Streaming example completed!");
            Console.WriteLine("============================================");
        }
    }
}
```

---

## 8. Node.js SDK / Node.js SDK

### Complete Example

```javascript
// D:/Ainos/examples/nodejs/streaming_inference.js
// Node.js SDK Streaming Inference Example
// ==========================================

import fetch from 'node-fetch';
import { EventSource } from 'eventsource';
import WebSocket from 'ws';
import readline from 'readline';

class AinosStreamingClient {
    constructor(baseUrl, apiToken) {
        this.baseUrl = baseUrl.replace(/\/+$/, '');
        this.apiToken = apiToken || '';
        this.cancelled = false;
    }

    getHeaders() {
        const headers = {
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream',
        };
        if (this.apiToken) {
            headers['Authorization'] = `Bearer ${this.apiToken}`;
        }
        return headers;
    }

    cancel() {
        this.cancelled = true;
    }

    /**
     * SSE Streaming Inference
     */
    async streamInferSSE(model, prompt, maxTokens = 1024, temperature = 0.7, callbacks = {}) {
        this.cancelled = false;
        const { onToken, onDone, onError } = callbacks;
        let fullResponse = '';
        let tokenCount = 0;

        return new Promise((resolve, reject) => {
            const url = `${this.baseUrl}/api/inference`;
            
            fetch(url, {
                method: 'POST',
                headers: this.getHeaders(),
                body: JSON.stringify({
                    model,
                    prompt,
                    max_tokens: maxTokens,
                    temperature,
                    stream: true,
                }),
            }).then(async (response) => {
                if (!response.ok) {
                    const error = await response.text();
                    reject(new Error(`Server error ${response.status}: ${error}`));
                    return;
                }

                const es = new EventSource(response);
                
                es.addEventListener('message', (event) => {
                    if (this.cancelled) {
                        es.close();
                        resolve(fullResponse);
                        return;
                    }

                    const data = event.data;
                    
                    if (data === '[DONE]') {
                        es.close();
                        if (onDone) onDone(tokenCount, 'stop');
                        resolve(fullResponse);
                        return;
                    }

                    try {
                        const parsed = JSON.parse(data);
                        if (parsed.error) {
                            if (onError) onError(parsed.error);
                            es.close();
                            resolve(fullResponse);
                            return;
                        }
                        if (parsed.token) {
                            fullResponse += parsed.token;
                            tokenCount++;
                            if (onToken) onToken(parsed.token, parsed.index || tokenCount);
                        }
                    } catch (e) {
                        // Plain text
                        fullResponse += data;
                        tokenCount++;
                        if (onToken) onToken(data, tokenCount);
                    }
                });

                es.addEventListener('error', (event) => {
                    es.close();
                    if (event.message && onError) onError(event.message);
                    resolve(fullResponse);
                });
            }).catch(reject);
        });
    }

    /**
     * WebSocket Streaming Inference
     */
    async streamInferWS(model, prompt, maxTokens = 1024, temperature = 0.7, callbacks = {}) {
        this.cancelled = false;
        const { onToken, onDone, onError } = callbacks;
        let fullResponse = '';
        let tokenCount = 0;

        const wsUrl = this.baseUrl
            .replace('http://', 'ws://')
            .replace('https://', 'wss://') + '/ws/inference';

        return new Promise((resolve, reject) => {
            const ws = new WebSocket(wsUrl, {
                headers: this.apiToken ? {
                    'Authorization': `Bearer ${this.apiToken}`
                } : undefined
            });

            ws.on('open', () => {
                // Send request
                ws.send(JSON.stringify({
                    model,
                    prompt,
                    max_tokens: maxTokens,
                    temperature,
                }));
            });

            ws.on('message', (data) => {
                if (this.cancelled) {
                    ws.close();
                    resolve(fullResponse);
                    return;
                }

                try {
                    const parsed = JSON.parse(data.toString());
                    
                    if (parsed.error) {
                        if (onError) onError(parsed.error);
                        ws.close();
                        resolve(fullResponse);
                        return;
                    }

                    if (parsed.done) {
                        if (onDone) onDone(parsed.token_count || tokenCount, parsed.finish_reason || 'stop');
                        ws.close();
                        resolve(fullResponse);
                        return;
                    }

                    if (parsed.token) {
                        fullResponse += parsed.token;
                        tokenCount++;
                        if (onToken) onToken(parsed.token, parsed.index || tokenCount);
                    }
                } catch (e) {
                    if (onError) onError(`Parse error: ${e.message}`);
                }
            });

            ws.on('error', (error) => {
                if (onError) onError(error.message);
                resolve(fullResponse);
            });

            ws.on('close', () => {
                resolve(fullResponse);
            });
        });
    }
}

// Main function
async function main() {
    console.log('============================================');
    console.log('AinosOS Node.js SDK - Streaming Inference Example');
    console.log('============================================');

    const baseUrl = process.env.AINOS_URL || 'http://localhost:8080';
    const apiToken = process.env.AINOS_API_TOKEN || '';
    const client = new AinosStreamingClient(baseUrl, apiToken);

    // Handle Ctrl+C
    process.on('SIGINT', () => {
        console.log('\n\nCancelling...');
        client.cancel();
    });

    // Callbacks
    const callbacks = {
        onToken: (token, index) => {
            process.stdout.write(token);
        },
        onDone: (count, reason) => {
            console.log(`\n\n[Done: ${count} tokens, reason: ${reason}]`);
        },
        onError: (error) => {
            console.error(`\n\n[Error: ${error}]`);
        },
    };

    // Example 1: SSE Streaming
    console.log('\n[1] SSE Streaming Inference');
    console.log('Prompt: Write a story about a magical forest.');
    process.stdout.write('Response: ');

    let start = Date.now();
    let fullText = await client.streamInferSSE(
        'ainos-llama-3.1-8b',
        'Write a story about a magical forest.',
        200, 0.7, callbacks
    );
    let elapsed = (Date.now() - start) / 1000;
    console.log(`\nTime: ${elapsed.toFixed(2)}s | Characters: ${fullText.length}`);

    // Example 2: WebSocket Streaming
    console.log('\n[2] WebSocket Streaming Inference');
    console.log('Prompt: Compare SSE and WebSocket protocols.');
    process.stdout.write('Response: ');

    start = Date.now();
    fullText = await client.streamInferWS(
        'ainos-llama-3.1-8b',
        'Compare SSE and WebSocket protocols.',
        200, 0.7, callbacks
    );
    elapsed = (Date.now() - start) / 1000;
    console.log(`\nTime: ${elapsed.toFixed(2)}s | Characters: ${fullText.length}`);

    // Example 3: Real-time chat simulation
    console.log('\n[3] Real-time Chat Simulation');
    const readline = require('readline').createInterface({
        input: process.stdin,
        output: process.stdout
    });

    const chat = async () => {
        while (true) {
            const prompt = await new Promise(resolve => 
                readline.question('\nYou: ', resolve));
            
            if (prompt.toLowerCase() === 'exit' || prompt.toLowerCase() === 'quit') {
                break;
            }

            process.stdout.write('AI: ');
            await client.streamInferSSE(
                'ainos-llama-3.1-8b',
                prompt,
                200, 0.7, callbacks
            );
            console.log();
        }
        readline.close();
    };

    console.log('Type "exit" to quit.');
    await chat();

    console.log('\n============================================');
    console.log('Streaming example completed!');
    console.log('============================================');
}

main().catch(console.error);
```

---

## 9. Backpressure Handling / 背压处理

### What is Backpressure? / 什么是背压？

Backpressure is a mechanism to handle situations where the producer (model) generates tokens faster than the consumer (client) can process them. Proper backpressure handling prevents buffer overflow and memory issues.

背压是一种处理生产者（模型）生成 token 速度快于消费者（客户端）处理速度的机制。正确的背压处理可以防止缓冲区溢出和内存问题。

### Python Backpressure Example

```python
import asyncio
from collections import deque

class BackpressureBuffer:
    """
    Token buffer with backpressure control.
    """
    
    def __init__(self, max_size: int = 100):
        self.buffer = deque(maxlen=max_size)
        self.max_size = max_size
        self._paused = False
    
    async def add_token(self, token: str):
        """Add token with backpressure."""
        while len(self.buffer) >= self.max_size:
            self._paused = True
            await asyncio.sleep(0.01)  # Wait for consumer
        self.buffer.append(token)
        self._paused = False
    
    async def get_tokens(self, batch_size: int = 10) -> list:
        """Get batch of tokens."""
        tokens = []
        while len(tokens) < batch_size and self.buffer:
            tokens.append(self.buffer.popleft())
        return tokens
    
    @property
    def is_paused(self) -> bool:
        return self._paused


# Usage with streaming
async def stream_with_backpressure(client, model, prompt):
    buffer = BackpressureBuffer(max_size=50)
    
    # Producer
    async def producer():
        async for token in client.stream_infer(model, prompt):
            await buffer.add_token(token)
    
    # Consumer
    async def consumer():
        while True:
            tokens = await buffer.get_tokens(batch_size=5)
            if not tokens:
                break
            # Process tokens
            for token in tokens:
                print(token, end="", flush=True)
    
    await asyncio.gather(producer(), consumer())
```

---

## 10. Cancellation / 取消

### Python Cancellation

```python
import signal
import sys

def setup_cancellation(client):
    """Setup graceful cancellation."""
    def handler(signum, frame):
        print("\nCancelling inference...")
        client.cancel()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


# Timeout-based cancellation
import asyncio

async def infer_with_timeout(client, model, prompt, timeout=30):
    """Run inference with timeout."""
    try:
        result = await asyncio.wait_for(
            client.stream_infer_async(model, prompt),
            timeout=timeout
        )
        return result
    except asyncio.TimeoutError:
        client.cancel()
        print(f"\nInference timed out after {timeout}s")
        return None
```

### Go Cancellation

```go
// Context-based cancellation
ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
defer cancel()

// Pass context to streaming request
req, err := http.NewRequestWithContext(ctx, "POST", url, body)
```

### Rust Cancellation

```rust
// Tokio select-based cancellation
tokio::select! {
    result = stream_infer() => {
        // Handle result
    }
    _ = tokio::time::sleep(Duration::from_secs(30)) => {
        println!("Timeout");
        client.cancel();
    }
}
```

---

## 11. Error Handling / 错误处理

### SSE Error Handling

```python
def stream_with_error_handling(client, model, prompt):
    """Streaming with comprehensive error handling."""
    retries = 3
    backoff = 1.0
    
    for attempt in range(retries):
        try:
            result = client.stream_infer_sse(model, prompt)
            return result
        except ConnectionError as e:
            print(f"Connection error (attempt {attempt + 1}): {e}")
            if attempt < retries - 1:
                time.sleep(backoff)
                backoff *= 2
            else:
                raise
        except TimeoutError as e:
            print(f"Timeout: {e}")
            client.cancel()
            raise
        except Exception as e:
            print(f"Unexpected error: {e}")
            raise
```

### WebSocket Error Handling

```python
async def ws_with_reconnection(client, model, prompt):
    """WebSocket with automatic reconnection."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            result = await client.stream_infer_websocket(model, prompt)
            return result
        except (ConnectionError, WebSocketError) as e:
            print(f"WS error (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                raise
```

---

## 12. Best Practices / 最佳实践

### Performance Tips

```python
# 1. Use appropriate buffer sizes
BUFFER_SIZE = 64 * 1024  # 64KB for streaming

# 2. Batch small tokens
async def batch_tokens(stream, batch_size=10):
    batch = []
    async for token in stream:
        batch.append(token)
        if len(batch) >= batch_size:
            yield ''.join(batch)
            batch = []
    if batch:
        yield ''.join(batch)

# 3. Use async/await for non-blocking I/O
# 4. Implement proper backpressure
# 5. Set reasonable timeouts
# 6. Handle partial responses gracefully
```

### Streaming Checklist

```markdown
## Streaming Implementation Checklist

- [ ] Choose appropriate protocol (SSE vs WebSocket)
- [ ] Implement token-level callbacks
- [ ] Handle completion signal ([DONE])
- [ ] Implement cancellation mechanism
- [ ] Add timeout handling
- [ ] Handle reconnection (WebSocket)
- [ ] Implement backpressure
- [ ] Add error recovery
- [ ] Monitor streaming performance
- [ ] Log streaming events
- [ ] Test with various network conditions
- [ ] Verify memory usage with long streams
```

### Common Pitfalls

| Issue | Cause | Solution |
|-------|-------|----------|
| Missing tokens | Buffer not flushed | Call `flush()` after write |
| Memory leak | Buffering entire response | Process tokens incrementally |
| Connection timeout | No keepalive | Set longer timeout, use heartbeat |
| Partial response | Connection lost | Implement reconnection logic |
| High latency | Blocking main thread | Use async/await, worker threads |
| Rate limiting | Too many requests | Implement client-side throttling |
| WebSocket failure | Proxy not configured | Check proxy upgrade headers |

---

*For more streaming examples, visit [https://github.com/ainos-ai/examples](https://github.com/ainos-ai/examples).*

*更多流式示例请访问 [https://github.com/ainos-ai/examples](https://github.com/ainos-ai/examples)。*