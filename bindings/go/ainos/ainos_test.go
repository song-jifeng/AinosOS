package ainos

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"net"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// ---------------------------------------------------------------------------
// Mock server
// ---------------------------------------------------------------------------

// mockServer implements a minimal Ainos daemon for testing.
type mockServer struct {
	ln        net.Listener
	port      int
	mu        sync.Mutex
	conns     []net.Conn
	closed    atomic.Bool
	responses map[string]func([]byte) []byte // msgType -> response generator
	// For streaming
	streamChunks []string
	requireAuth  bool
	validToken   string
}

func newMockServer(t *testing.T) *mockServer {
	t.Helper()

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("failed to start mock server: %v", err)
	}

	s := &mockServer{
		ln:           ln,
		port:         ln.Addr().(*net.TCPAddr).Port,
		responses:    make(map[string]func([]byte) []byte),
		validToken:   "test-token-32-chars-minimum-length",
		streamChunks: []string{"Hello", " ", "World", "!"},
	}

	// Register default response handlers
	s.responses[msgTypeStatus] = func(req []byte) []byte {
		return mustMarshal(map[string]interface{}{
			"type":              msgTypeStatusResponse,
			"uptime":            3600,
			"models_loaded":     2,
			"total_requests":    42,
			"network_available": true,
			"active_sessions":   1,
		})
	}

	s.responses[msgTypeInference] = func(req []byte) []byte {
		return mustMarshal(map[string]interface{}{
			"type":             msgTypeInferenceResponse,
			"output":           "Hello from mock server!",
			"tokens_generated": 5,
			"inference_ms":     10,
			"source":           "local",
		})
	}

	s.responses[msgTypeModelList] = func(req []byte) []byte {
		return mustMarshal(map[string]interface{}{
			"type": msgTypeModelListResponse,
			"models": []map[string]interface{}{
				{
					"id":           "phi_3_mini_4k_instruct_q4_gguf",
					"name":         "phi-3-mini-4k-instruct-q4.gguf",
					"path":         "/models/phi-3-mini-4k-instruct-q4.gguf",
					"size_mb":      2048,
					"loaded":       true,
					"architecture": "phi3",
				},
			},
		})
	}

	s.responses[msgTypeModelLoad] = func(req []byte) []byte {
		return mustMarshal(map[string]interface{}{
			"type":    msgTypeModelLoadResponse,
			"model_id": "test_model",
			"status":  "loaded",
			"message": "Model loaded successfully",
			"model_info": map[string]interface{}{
				"id":           "test_model",
				"name":         "test.gguf",
				"path":         "/models/test.gguf",
				"size_mb":      1024,
				"loaded":       true,
				"architecture": "auto",
			},
		})
	}

	s.responses[msgTypeModelUnload] = func(req []byte) []byte {
		return mustMarshal(map[string]interface{}{
			"type":    msgTypeModelUnloadResponse,
			"model_id": "test_model",
			"status":  "unloaded",
			"message": "Model unloaded successfully",
		})
	}

	s.responses[msgTypeContextStore] = func(req []byte) []byte {
		return mustMarshal(map[string]interface{}{
			"type":             msgTypeInferenceResponse,
			"output":           "Context stored: test_key",
			"tokens_generated": 0,
			"inference_ms":     0,
			"source":           "local",
		})
	}

	s.responses[msgTypeContextRetrieve] = func(req []byte) []byte {
		return mustMarshal(map[string]interface{}{
			"type":             msgTypeInferenceResponse,
			"output":           "test_value",
			"tokens_generated": 0,
			"inference_ms":     0,
			"source":           "local",
		})
	}

	s.responses[msgTypeAuth] = func(req []byte) []byte {
		return mustMarshal(map[string]interface{}{
			"type":                msgTypeAuthResponse,
			"success":             true,
			"session_token":       "sess_" + s.validToken[:8],
			"message":             "Authentication successful",
			"permissions":         []string{"infer", "model_ops", "status", "admin"},
			"session_ttl_seconds": 3600,
		})
	}

	s.responses[msgTypeRateLimitStatus] = func(req []byte) []byte {
		return mustMarshal(map[string]interface{}{
			"type": "RateLimitStatusResponse",
			"limits": []map[string]interface{}{
				{
					"category":      "inference",
					"limit":         100,
					"remaining":     95,
					"reset_seconds": 30,
				},
			},
		})
	}

	go s.serve(t)
	return s
}

func (s *mockServer) serve(t *testing.T) {
	for {
		conn, err := s.ln.Accept()
		if err != nil {
			if s.closed.Load() {
				return
			}
			t.Logf("mock server accept error: %v", err)
			return
		}

		s.mu.Lock()
		s.conns = append(s.conns, conn)
		s.mu.Unlock()

		go s.handleConn(t, conn)
	}
}

func (s *mockServer) handleConn(t *testing.T, conn net.Conn) {
	defer conn.Close()

	reader := bufio.NewReader(conn)
	for {
		line, err := reader.ReadBytes('\n')
		if err != nil {
			return
		}

		// Parse the request to get the message type
		var req struct {
			Type string `json:"type"`
		}
		if err := json.Unmarshal(line, &req); err != nil {
			t.Logf("mock server: bad request: %v", err)
			continue
		}

		// Check auth requirement
		if s.requireAuth && req.Type != msgTypeAuth {
			conn.Write(mustMarshal(map[string]interface{}{
				"type":    msgTypeError,
				"code":    401,
				"message": "Authentication required",
			}))
			conn.Write([]byte{'\n'})
			continue
		}

		// Find response handler
		s.mu.Lock()
		handler, ok := s.responses[req.Type]
		s.mu.Unlock()

		if !ok {
			t.Logf("mock server: no handler for %q", req.Type)
			conn.Write(mustMarshal(map[string]interface{}{
				"type":    msgTypeError,
				"code":    -1,
				"message": fmt.Sprintf("unknown request type: %q", req.Type),
			}))
			conn.Write([]byte{'\n'})
			continue
		}

		response := handler(line)
		conn.Write(response)
		conn.Write([]byte{'\n'})
	}
}

func (s *mockServer) close() {
	s.closed.Store(true)
	s.ln.Close()
	s.mu.Lock()
	for _, conn := range s.conns {
		conn.Close()
	}
	s.mu.Unlock()
}

func mustMarshal(v interface{}) []byte {
	data, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	return data
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------

func setupTestClient(t *testing.T) (*Client, *mockServer) {
	t.Helper()
	s := newMockServer(t)

	client := NewClient(
		WithHost("127.0.0.1"),
		WithPort(s.port),
		WithConnectTimeout(2*time.Second),
		WithReadTimeout(5*time.Second),
		WithAutoReconnect(false),
	)

	if err := client.Connect(); err != nil {
		s.close()
		t.Fatalf("Connect failed: %v", err)
	}

	return client, s
}

func teardownTestClient(t *testing.T, client *Client, s *mockServer) {
	t.Helper()
	client.Disconnect()
	s.close()
}

func TestConnect(t *testing.T) {
	s := newMockServer(t)
	defer s.close()

	client := NewClient(
		WithHost("127.0.0.1"),
		WithPort(s.port),
		WithConnectTimeout(2*time.Second),
		WithAutoReconnect(false),
	)

	if err := client.Connect(); err != nil {
		t.Fatalf("Connect failed: %v", err)
	}

	if !client.IsConnected() {
		t.Error("expected IsConnected to be true")
	}

	client.Disconnect()
	if client.IsConnected() {
		t.Error("expected IsConnected to be false after disconnect")
	}
}

func TestConnectRefused(t *testing.T) {
	client := NewClient(
		WithHost("127.0.0.1"),
		WithPort(1), // unlikely to be open
		WithConnectTimeout(500*time.Millisecond),
		WithAutoReconnect(false),
	)

	err := client.Connect()
	if err == nil {
		t.Fatal("expected connection error")
	}

	var connErr *ConnectionError
	if !isErrorType(err, &connErr) {
		t.Errorf("expected *ConnectionError, got %T: %v", err, err)
	}
}

func TestDisconnect(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	if err := client.Disconnect(); err != nil {
		t.Fatalf("Disconnect failed: %v", err)
	}

	if client.IsConnected() {
		t.Error("expected IsConnected to be false")
	}
}

func TestInfer(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	ctx := context.Background()
	resp, err := client.Infer(ctx, &InferenceRequest{
		Prompt: "Hello",
		Model:  "default",
	})
	if err != nil {
		t.Fatalf("Infer failed: %v", err)
	}

	if resp.Text == "" {
		t.Error("expected non-empty response text")
	}
	if resp.TokensGenerated == 0 {
		t.Error("expected TokensGenerated > 0")
	}
	if resp.Source != "local" {
		t.Errorf("expected source 'local', got %q", resp.Source)
	}
}

func TestInferWithOptions(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	ctx := context.Background()
	temp := 0.5
	maxTokens := 100
	req := &InferenceRequest{
		Prompt:     "Hello",
		Model:      "default",
		Temperature: &temp,
		MaxTokens:  &maxTokens,
	}

	resp, err := client.Infer(ctx, req)
	if err != nil {
		t.Fatalf("Infer failed: %v", err)
	}

	if resp.Text == "" {
		t.Error("expected non-empty response")
	}
}

func TestInferStream(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	// For streaming, the mock server returns a regular InferenceResponse
	// (the current daemon behavior).  The stream reader should handle this
	// as a single chunk.
	ctx := context.Background()
	chunks, err := client.InferStream(ctx, &InferenceRequest{
		Prompt: "Hello",
		Model:  "default",
	})
	if err != nil {
		t.Fatalf("InferStream failed: %v", err)
	}

	var text string
	for chunk := range chunks {
		text += chunk.Text
	}

	if text == "" {
		t.Error("expected non-empty stream output")
	}
}

func TestStatus(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	status, err := client.Status()
	if err != nil {
		t.Fatalf("Status failed: %v", err)
	}

	if status.Uptime <= 0 {
		t.Errorf("expected positive uptime, got %d", status.Uptime)
	}
	if status.ModelsLoaded <= 0 {
		t.Errorf("expected ModelsLoaded > 0, got %d", status.ModelsLoaded)
	}
}

func TestHealth(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	health, err := client.Health()
	if err != nil {
		t.Fatalf("Health failed: %v", err)
	}

	if health.Status != "ok" {
		t.Errorf("expected status 'ok', got %q", health.Status)
	}
	if health.Uptime <= 0 {
		t.Errorf("expected positive uptime, got %d", health.Uptime)
	}
}

func TestModelList(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	models, err := client.ModelList()
	if err != nil {
		t.Fatalf("ModelList failed: %v", err)
	}

	if len(models) == 0 {
		t.Fatal("expected at least one model")
	}

	m := models[0]
	if m.ID == "" {
		t.Error("expected model ID to be non-empty")
	}
	if m.Name == "" {
		t.Error("expected model name to be non-empty")
	}
}

func TestModelLoad(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	info, err := client.ModelLoad("/models/test.gguf", nil)
	if err != nil {
		t.Fatalf("ModelLoad failed: %v", err)
	}

	if info == nil {
		t.Fatal("expected non-nil ModelInfo")
	}
	if info.ID != "test_model" {
		t.Errorf("expected model_id 'test_model', got %q", info.ID)
	}
	if !info.Loaded {
		t.Error("expected model to be loaded")
	}
}

func TestModelUnload(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	if err := client.ModelUnload("test_model"); err != nil {
		t.Fatalf("ModelUnload failed: %v", err)
	}
}

func TestContextStore(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	err := client.ContextStore("", "test_key", []byte("test_value"), 0)
	if err != nil {
		t.Fatalf("ContextStore failed: %v", err)
	}
}

func TestContextRetrieve(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	// Store first
	err := client.ContextStore("", "test_key", []byte("test_value"), 0)
	if err != nil {
		t.Fatalf("ContextStore failed: %v", err)
	}

	// Retrieve
	value, err := client.ContextRetrieve("", "test_key")
	if err != nil {
		t.Fatalf("ContextRetrieve failed: %v", err)
	}

	if string(value) != "test_value" {
		t.Errorf("expected 'test_value', got %q", string(value))
	}
}

func TestRateLimitStatus(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	status, err := client.RateLimitStatus()
	if err != nil {
		t.Fatalf("RateLimitStatus failed: %v", err)
	}

	if len(status.Limits) == 0 {
		t.Fatal("expected at least one rate limit")
	}

	limit := status.Limits[0]
	if limit.Category != "inference" {
		t.Errorf("expected category 'inference', got %q", limit.Category)
	}
	if limit.Limit <= 0 {
		t.Errorf("expected positive limit, got %d", limit.Limit)
	}
}

func TestBatchInfer(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	ctx := context.Background()
	reqs := []*InferenceRequest{
		{Prompt: "Hello 1", Model: "default"},
		{Prompt: "Hello 2", Model: "default"},
		{Prompt: "Hello 3", Model: "default"},
	}

	responses, err := client.BatchInfer(ctx, reqs)
	if err != nil {
		t.Fatalf("BatchInfer failed: %v", err)
	}

	if len(responses) != 3 {
		t.Fatalf("expected 3 responses, got %d", len(responses))
	}

	for i, resp := range responses {
		if resp == nil {
			t.Errorf("response %d is nil", i)
			continue
		}
		if resp.Text == "" {
			t.Errorf("response %d has empty text", i)
		}
	}
}

func TestAuthenticate(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	resp, err := client.Authenticate("test-token-32-chars-minimum-length")
	if err != nil {
		t.Fatalf("Authenticate failed: %v", err)
	}

	if !resp.Success {
		t.Error("expected successful authentication")
	}
	if resp.SessionToken == "" {
		t.Error("expected non-empty session token")
	}
}

func TestSession(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	// Authenticate
	_, err := client.Authenticate("test-token-32-chars-minimum-length")
	if err != nil {
		t.Fatalf("Authenticate failed: %v", err)
	}

	session := client.Session()
	if session == nil {
		t.Fatal("expected non-nil session info")
	}
	if session.Token == "" {
		t.Error("expected non-empty session token")
	}
	if len(session.Permissions) == 0 {
		t.Error("expected non-empty permissions")
	}
}

func TestHasPermission(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	_, err := client.Authenticate("test-token-32-chars-minimum-length")
	if err != nil {
		t.Fatalf("Authenticate failed: %v", err)
	}

	if !client.HasPermission(PermissionInfer) {
		t.Error("expected 'infer' permission")
	}
	if !client.HasPermission(PermissionAdmin) {
		t.Error("expected 'admin' permission")
	}
}

func TestNotConnected(t *testing.T) {
	client := NewClient(WithAutoReconnect(false))

	_, err := client.Status()
	if err != ErrNotConnected {
		t.Errorf("expected ErrNotConnected, got %v", err)
	}
}

func TestDoubleConnect(t *testing.T) {
	s := newMockServer(t)
	defer s.close()

	client := NewClient(
		WithHost("127.0.0.1"),
		WithPort(s.port),
		WithConnectTimeout(2*time.Second),
		WithAutoReconnect(false),
	)

	if err := client.Connect(); err != nil {
		t.Fatalf("first Connect failed: %v", err)
	}

	// Second connect should be a no-op
	if err := client.Connect(); err != nil {
		t.Fatalf("second Connect should not fail: %v", err)
	}

	client.Disconnect()
}

func TestContextCancel(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // immediately cancel

	_, err := client.Infer(ctx, &InferenceRequest{
		Prompt: "Hello",
		Model:  "default",
	})
	if err != context.Canceled {
		t.Errorf("expected context.Canceled, got %v", err)
	}
}

func TestRequestValidation(t *testing.T) {
	client, s := setupTestClient(t)
	defer teardownTestClient(t, client, s)

	// Empty prompt
	_, err := client.Infer(context.Background(), &InferenceRequest{
		Prompt: "",
		Model:  "default",
	})
	if err == nil {
		t.Error("expected error for empty prompt")
	}
}

func TestConfig(t *testing.T) {
	cfg := DefaultConfig()
	if cfg.Host != "127.0.0.1" {
		t.Errorf("expected host '127.0.0.1', got %q", cfg.Host)
	}
	if cfg.Port != 9500 {
		t.Errorf("expected port 9500, got %d", cfg.Port)
	}
}

func TestNewRequest(t *testing.T) {
	req := NewRequest("Hello", WithTemperature(0.7), WithMaxTokens(100))
	if req.Prompt != "Hello" {
		t.Errorf("expected prompt 'Hello', got %q", req.Prompt)
	}
	if req.Temperature == nil || *req.Temperature != 0.7 {
		t.Errorf("expected temperature 0.7, got %v", req.Temperature)
	}
	if req.MaxTokens == nil || *req.MaxTokens != 100 {
		t.Errorf("expected max_tokens 100, got %v", req.MaxTokens)
	}
}

func TestRetryConfig(t *testing.T) {
	rc := DefaultRetryConfig()
	if rc.MaxRetries != 3 {
		t.Errorf("expected MaxRetries 3, got %d", rc.MaxRetries)
	}

	backoff0 := rc.Backoff(0)
	if backoff0 != 100*time.Millisecond {
		t.Errorf("expected backoff(0) = 100ms, got %v", backoff0)
	}

	backoff1 := rc.Backoff(1)
	if backoff1 != 200*time.Millisecond {
		t.Errorf("expected backoff(1) = 200ms, got %v", backoff1)
	}

	backoff2 := rc.Backoff(2)
	if backoff2 != 400*time.Millisecond {
		t.Errorf("expected backoff(2) = 400ms, got %v", backoff2)
	}
}

func TestErrorClassification(t *testing.T) {
	connErr := &ConnectionError{Op: "dial", Addr: "127.0.0.1:9500", Err: fmt.Errorf("refused")}
	if !IsConnectionError(connErr) {
		t.Error("expected ConnectionError to be classified as connection error")
	}
	if IsAuthError(connErr) {
		t.Error("ConnectionError should not be an auth error")
	}

	authErr := &AuthError{Message: "bad token"}
	if !IsAuthError(authErr) {
		t.Error("expected AuthError to be classified as auth error")
	}
	if IsConnectionError(authErr) {
		t.Error("AuthError should not be a connection error")
	}

	timeoutErr := &TimeoutError{Operation: "read", Timeout: 5 * time.Second}
	if !IsTimeout(timeoutErr) {
		t.Error("expected TimeoutError to be classified as timeout")
	}

	rateLimitErr := &RateLimitError{Category: "inference", Message: "too fast"}
	if !IsRateLimited(rateLimitErr) {
		t.Error("expected RateLimitError to be classified as rate limited")
	}
}

func TestIsRetryable(t *testing.T) {
	if !IsRetryable(&ConnectionError{Op: "dial", Addr: "test", Err: fmt.Errorf("refused")}) {
		t.Error("ConnectionError should be retryable")
	}
	if !IsRetryable(&TimeoutError{Operation: "read", Timeout: 5 * time.Second}) {
		t.Error("TimeoutError should be retryable")
	}
	if IsRetryable(&AuthError{Message: "bad"}) {
		t.Error("AuthError should not be retryable")
	}
	if IsRetryable(&ProtocolError{Message: "bad"}) {
		t.Error("ProtocolError should not be retryable")
	}
}

func TestDaemonCode(t *testing.T) {
	daemonErr := &Error{Code: 429, Message: "rate limited"}
	code, ok := DaemonCode(daemonErr)
	if !ok || code != 429 {
		t.Errorf("expected code 429, got %d (ok=%v)", code, ok)
	}

	_, ok = DaemonCode(fmt.Errorf("some other error"))
	if ok {
		t.Error("expected DaemonCode to return false for non-daemon errors")
	}
}

func TestTokenAuth(t *testing.T) {
	ta := &TokenAuth{Token: "my-secret-token-here"}
	if !ta.IsValid() {
		t.Error("expected valid token")
	}

	masked := ta.Mask()
	if masked == "my-secret-token-here" {
		t.Error("Mask() should not return the full token")
	}

	short := &TokenAuth{Token: "short"}
	if short.IsValid() {
		t.Error("expected short token to be invalid")
	}
}

func TestConnPool(t *testing.T) {
	s := newMockServer(t)
	defer s.close()

	pool := NewConnPool("127.0.0.1", s.port, PoolConfig{MaxSize: 2, IdleTimeout: 5 * time.Second})
	defer pool.Close()

	// Acquire transports
	t1, err := pool.Acquire()
	if err != nil {
		t.Fatalf("Acquire 1 failed: %v", err)
	}
	if t1 == nil {
		t.Fatal("expected non-nil transport")
	}

	t2, err := pool.Acquire()
	if err != nil {
		t.Fatalf("Acquire 2 failed: %v", err)
	}

	// Release them
	pool.Release(t1)
	pool.Release(t2)

	// Re-acquire (should reuse)
	t3, err := pool.Acquire()
	if err != nil {
		t.Fatalf("Re-acquire failed: %v", err)
	}
	pool.Release(t3)

	if pool.Active() > 2 {
		t.Errorf("expected at most 2 active, got %d", pool.Active())
	}
}

func TestStreamReaderCollect(t *testing.T) {
	// Test CollectStream with direct channel input
	chunks := make(chan *InferenceChunk, 4)
	chunks <- &InferenceChunk{Text: "Hello ", Index: 1, Done: false}
	chunks <- &InferenceChunk{Text: "World", Index: 2, Done: false}
	chunks <- &InferenceChunk{Text: "!", Index: 3, Done: true}
	close(chunks)

	resp, err := CollectStream(context.Background(), chunks)
	if err != nil {
		t.Fatalf("CollectStream failed: %v", err)
	}

	if resp.Text != "Hello World!" {
		t.Errorf("expected 'Hello World!', got %q", resp.Text)
	}
}

func TestRetryKindOf(t *testing.T) {
	if RetryKindOf(nil) != RetryFatal {
		t.Error("expected RetryFatal for nil")
	}
	if RetryKindOf(ErrNotConnected) != RetryTransient {
		t.Error("expected RetryTransient for ErrNotConnected")
	}
	if RetryKindOf(ErrModelNotFound) != RetryFatal {
		t.Error("expected RetryFatal for ErrModelNotFound")
	}
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func isErrorType(err error, target interface{}) bool {
	switch target.(type) {
	case **ConnectionError:
		_, ok := err.(*ConnectionError)
		return ok
	case **AuthError:
		_, ok := err.(*AuthError)
		return ok
	case **TimeoutError:
		_, ok := err.(*TimeoutError)
		return ok
	case **ProtocolError:
		_, ok := err.(*ProtocolError)
		return ok
	case **RateLimitError:
		_, ok := err.(*RateLimitError)
		return ok
	case **InferenceError:
		_, ok := err.(*InferenceError)
		return ok
	}
	return false
}