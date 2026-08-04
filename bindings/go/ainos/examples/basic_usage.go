// Package main demonstrates the Ainos Go SDK usage.
//
// Build and run:
//
//	cd D:/Ainos/bindings/go/ainos
//	go run examples/basic_usage.go
//
// Or build first:
//
//	go build -o ainos-example ./examples
//	./ainos-example
package main

import (
	"context"
	"fmt"
	"log"
	"time"
	"ainos/ainos"
)

func main() {
	if err := run(); err != nil {
		log.Fatalf("error: %v", err)
	}
}

func run() error {
	// =========================================================================
	// Example 1: Basic setup
	// =========================================================================
	fmt.Println("=== Example 1: Basic Setup ===")

	// Create a client with default options (connects to 127.0.0.1:9500)
	client := ainos.NewClient()

	// Connect to the daemon
	if err := client.Connect(); err != nil {
		return fmt.Errorf("connect failed: %w", err)
	}
	defer client.Disconnect()

	fmt.Printf("Connected: %v\n", client.IsConnected())

	// =========================================================================
	// Example 2: Basic inference
	// =========================================================================
	fmt.Println("\n=== Example 2: Basic Inference ===")

	ctx := context.Background()

	resp, err := client.Infer(ctx, &ainos.InferenceRequest{
		Prompt: "What is the meaning of life?",
		Model:  "default",
	})
	if err != nil {
		return fmt.Errorf("inference failed: %w", err)
	}

	fmt.Printf("Response: %s\n", resp.Text)
	fmt.Printf("Tokens: %d, Time: %dms, Source: %s\n",
		resp.TokensGenerated, resp.InferenceMs, resp.Source)

	// =========================================================================
	// Example 3: Inference with options
	// =========================================================================
	fmt.Println("\n=== Example 3: Inference with Options ===")

	// Using the request option builder pattern
	req := ainos.NewRequest("Write a haiku about Go programming.",
		ainos.WithTemperature(0.8),
		ainos.WithMaxTokens(150),
		ainos.WithModel("default"),
	)

	resp, err = client.Infer(ctx, req)
	if err != nil {
		return fmt.Errorf("inference with options failed: %w", err)
	}

	fmt.Printf("Response: %s\n", resp.Text)

	// =========================================================================
	// Example 4: Streaming inference
	// =========================================================================
	fmt.Println("\n=== Example 4: Streaming Inference ===")

	chunks, err := client.InferStream(ctx, &ainos.InferenceRequest{
		Prompt: "Count from 1 to 5.",
		Model:  "default",
	})
	if err != nil {
		return fmt.Errorf("streaming inference failed: %w", err)
	}

	fmt.Print("Streaming response: ")
	for chunk := range chunks {
		fmt.Print(chunk.Text)
		if chunk.Done {
			break
		}
	}
	fmt.Println()

	// =========================================================================
	// Example 5: System status
	// =========================================================================
	fmt.Println("\n=== Example 5: System Status ===")

	status, err := client.Status()
	if err != nil {
		return fmt.Errorf("status query failed: %w", err)
	}

	fmt.Printf("Uptime: %d seconds\n", status.Uptime)
	fmt.Printf("Models loaded: %d\n", status.ModelsLoaded)
	fmt.Printf("Total requests: %d\n", status.TotalRequests)
	fmt.Printf("Network available: %v\n", status.NetworkAvailable)

	// =========================================================================
	// Example 6: Health check
	// =========================================================================
	fmt.Println("\n=== Example 6: Health Check ===")

	health, err := client.Health()
	if err != nil {
		return fmt.Errorf("health check failed: %w", err)
	}

	fmt.Printf("Status: %s\n", health.Status)
	fmt.Printf("Uptime: %d seconds\n", health.Uptime)
	fmt.Printf("Models loaded: %d\n", health.ModelsLoaded)

	// =========================================================================
	// Example 7: Model management
	// =========================================================================
	fmt.Println("\n=== Example 7: Model Management ===")

	// List models
	models, err := client.ModelList()
	if err != nil {
		return fmt.Errorf("model list failed: %w", err)
	}

	fmt.Printf("Available models (%d):\n", len(models))
	for _, m := range models {
		loaded := "unloaded"
		if m.Loaded {
			loaded = "loaded"
		}
		fmt.Printf("  - %s (%s, %s, %d MB)\n", m.ID, m.Name, loaded, m.SizeMB)
	}

	// Load a model
	info, err := client.ModelLoad("/path/to/model.gguf", nil)
	if err != nil {
		// This may fail if the model file doesn't exist; that's expected
		fmt.Printf("Model load (expected to fail without file): %v\n", err)
	} else {
		fmt.Printf("Loaded model: %s\n", info.ID)
	}

	// Unload a model
	if err := client.ModelUnload("test_model"); err != nil {
		fmt.Printf("Model unload (may fail): %v\n", err)
	}

	// =========================================================================
	// Example 8: Context storage
	// =========================================================================
	fmt.Println("\n=== Example 8: Context Storage ===")

	// Store a value
	err = client.ContextStore("", "my_key", []byte("my_value"), 3600)
	if err != nil {
		return fmt.Errorf("context store failed: %w", err)
	}
	fmt.Println("Stored context: my_key = my_value")

	// Retrieve the value
	value, err := client.ContextRetrieve("", "my_key")
	if err != nil {
		return fmt.Errorf("context retrieve failed: %w", err)
	}
	fmt.Printf("Retrieved context: my_key = %s\n", string(value))

	// =========================================================================
	// Example 9: Rate limiting
	// =========================================================================
	fmt.Println("\n=== Example 9: Rate Limit Status ===")

	rateLimit, err := client.RateLimitStatus()
	if err != nil {
		return fmt.Errorf("rate limit status failed: %w", err)
	}

	fmt.Println("Rate limits:")
	for _, l := range rateLimit.Limits {
		fmt.Printf("  %s: %d/%d remaining, resets in %ds\n",
			l.Category, l.Remaining, l.Limit, l.ResetSeconds)
	}

	// =========================================================================
	// Example 10: Authentication
	// =========================================================================
	fmt.Println("\n=== Example 10: Authentication ===")

	// Authenticate with a token
	authResp, err := client.Authenticate("your-auth-token-here")
	if err != nil {
		fmt.Printf("Authentication (may fail without valid token): %v\n", err)
	} else {
		fmt.Printf("Authenticated: %v\n", authResp.Success)
		fmt.Printf("Session token: %s\n", authResp.SessionToken[:8]+"...")
		fmt.Printf("Permissions: %v\n", authResp.Permissions)
		fmt.Printf("Session TTL: %d seconds\n", authResp.SessionTTLSeconds)
	}

	// Check session info
	session := client.Session()
	if session != nil {
		fmt.Printf("Session permissions: %v\n", session.Permissions)
		fmt.Printf("Session TTL remaining: %v\n", session.TTL)
	}

	// =========================================================================
	// Example 11: Batch inference
	// =========================================================================
	fmt.Println("\n=== Example 11: Batch Inference ===")

	reqs := []*ainos.InferenceRequest{
		{Prompt: "What is Go?", Model: "default"},
		{Prompt: "What is Rust?", Model: "default"},
		{Prompt: "What is Python?", Model: "default"},
	}

	responses, err := client.BatchInfer(ctx, reqs)
	if err != nil {
		fmt.Printf("Batch inference (may fail without pool): %v\n", err)
	} else {
		for i, resp := range responses {
			if resp != nil {
				fmt.Printf("  [%d] %s\n", i, resp.Text[:min(len(resp.Text), 60)])
			}
		}
	}

	// =========================================================================
	// Example 12: Error handling
	// =========================================================================
	fmt.Println("\n=== Example 12: Error Handling ===")

	// Try operations that might fail and handle errors gracefully
	_, err = client.Infer(ctx, &ainos.InferenceRequest{
		Prompt: "", // empty prompt will fail validation
		Model:  "default",
	})
	if err != nil {
		fmt.Printf("Expected error for empty prompt: %v\n", err)
		if ainos.IsAuthError(err) {
			fmt.Println("  -> This is an auth error")
		} else if ainos.IsConnectionError(err) {
			fmt.Println("  -> This is a connection error")
		} else if ainos.IsTimeout(err) {
			fmt.Println("  -> This is a timeout error")
		} else {
			fmt.Printf("  -> Error type: %T\n", err)
		}
	}

	// =========================================================================
	// Example 13: Custom client configuration
	// =========================================================================
	fmt.Println("\n=== Example 13: Custom Client Configuration ===")

	customClient := ainos.NewClient(
		ainos.WithHost("192.168.1.100"),
		ainos.WithPort(9500),
		ainos.WithConnectTimeout(3*time.Second),
		ainos.WithReadTimeout(60*time.Second),
		ainos.WithAuthToken("my-token"),
		ainos.WithAutoReconnect(true),
		ainos.WithReconnectDelay(2*time.Second),
		ainos.WithMaxReconnectAttempts(10),
	)

	// Attempt to connect (may fail with the custom host, which is expected)
	if err := customClient.Connect(); err != nil {
		fmt.Printf("Custom client connect (expected to fail): %v\n", err)
	} else {
		customClient.Disconnect()
	}

	// =========================================================================
	// Example 14: Timeout handling
	// =========================================================================
	fmt.Println("\n=== Example 14: Timeout Handling ===")

	ctxTimeout, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()

	// This will either succeed quickly or timeout
	_, err = client.Infer(ctxTimeout, &ainos.InferenceRequest{
		Prompt: "Hello!",
		Model:  "default",
	})
	if err != nil {
		fmt.Printf("Inference with timeout: %v\n", err)
	} else {
		fmt.Println("Inference completed within timeout")
	}

	// =========================================================================
	// Example 15: Using the function options builder
	// =========================================================================
	fmt.Println("\n=== Example 15: Function Options Builder ===")

	// Build a request with chained options
	request := ainos.NewRequest("Tell me a joke.",
		ainos.WithTemperature(0.9),
		ainos.WithTopP(0.95),
		ainos.WithTopK(50),
		ainos.WithMaxTokens(200),
		ainos.WithStop([]string{"\n", "?"}),
		ainos.WithSessionID("session-123"),
	)

	fmt.Printf("Request: prompt=%q, model=%s, temp=%v, max_tokens=%v\n",
		request.Prompt, request.Model,
		safeDerefFloat(request.Temperature),
		safeDerefInt(request.MaxTokens),
	)

	// Execute the request
	resp, err = client.Infer(ctx, request)
	if err != nil {
		fmt.Printf("Inference failed: %v\n", err)
	} else {
		fmt.Printf("Response: %s\n", resp.Text)
	}

	fmt.Println("\n=== All examples completed ===")
	return nil
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func safeDerefFloat(f *float64) float64 {
	if f == nil {
		return 0
	}
	return *f
}

func safeDerefInt(i *int) int {
	if i == nil {
		return 0
	}
	return *i
}

