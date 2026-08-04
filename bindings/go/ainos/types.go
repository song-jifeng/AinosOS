package ainos

import (
	"encoding/json"
	"fmt"
	"time"
)

// ---------------------------------------------------------------------------
// Wire protocol constants
// ---------------------------------------------------------------------------

// Message type constants that match the daemon's serde tag.
const (
	msgTypeAuth                = "Auth"
	msgTypeAuthResponse        = "AuthResponse"
	msgTypeInference           = "Inference"
	msgTypeInferenceResponse   = "InferenceResponse"
	msgTypeInferenceStream     = "InferenceStream"
	msgTypeInferenceChunk      = "InferenceChunk"
	msgTypeModelList           = "ModelList"
	msgTypeModelListResponse   = "ModelListResponse"
	msgTypeModelLoad           = "ModelLoad"
	msgTypeModelLoadResponse   = "ModelLoadResponse"
	msgTypeModelUnload         = "ModelUnload"
	msgTypeModelUnloadResponse = "ModelUnloadResponse"
	msgTypeContextStore        = "ContextStore"
	msgTypeContextRetrieve     = "ContextRetrieve"
	msgTypeStatus              = "Status"
	msgTypeStatusResponse      = "StatusResponse"
	msgTypeRateLimitStatus     = "RateLimitStatus"
	msgTypeError               = "Error"
)

// ---------------------------------------------------------------------------
// Client configuration
// ---------------------------------------------------------------------------

// ClientConfig holds all configuration for an Ainos client.
type ClientConfig struct {
	// Host is the daemon hostname or IP address (default "127.0.0.1").
	Host string
	// Port is the daemon TCP port (default 9500).
	Port int
	// ConnectTimeout is the maximum time to wait for the TCP handshake.
	ConnectTimeout time.Duration
	// ReadTimeout is the maximum time to wait for a response.
	ReadTimeout time.Duration
	// WriteTimeout is the maximum time to wait for a write to complete.
	WriteTimeout time.Duration
	// AutoReconnect controls whether the client attempts to reconnect on
	// connection loss.
	AutoReconnect bool
	// ReconnectDelay is the initial delay before reconnection.
	ReconnectDelay time.Duration
	// MaxReconnectAttempts limits reconnection attempts (0 = unlimited).
	MaxReconnectAttempts int
	// AuthToken is the bearer token for authentication.
	AuthToken string
	// AutoAuthenticate controls whether to authenticate automatically after
	// connecting when AuthToken is set.
	AutoAuthenticate bool
	// TLS enables TLS encryption for the connection.
	TLS bool
	// TLSInsecureSkipVerify controls whether TLS certificate verification is
	// skipped.
	TLSInsecureSkipVerify bool
	// RetryConfig controls automatic retry of operations.
	RetryConfig RetryConfig
}

// DefaultConfig returns a ClientConfig with sensible defaults.
func DefaultConfig() ClientConfig {
	return ClientConfig{
		Host:                  "127.0.0.1",
		Port:                  9500,
		ConnectTimeout:        5 * time.Second,
		ReadTimeout:           120 * time.Second,
		WriteTimeout:          10 * time.Second,
		AutoReconnect:         true,
		ReconnectDelay:        1 * time.Second,
		MaxReconnectAttempts:  5,
		AutoAuthenticate:      true,
		TLS:                   false,
		TLSInsecureSkipVerify: false,
		RetryConfig:           DefaultRetryConfig(),
	}
}

// ---------------------------------------------------------------------------
// Inference
// ---------------------------------------------------------------------------

// InferenceRequest represents a request to generate text with an AI model.
type InferenceRequest struct {
	// Model is the model identifier to use (default "default").
	Model string `json:"model"`
	// Prompt is the input text for the model.
	Prompt string `json:"prompt"`
	// Temperature controls sampling randomness (0.0–2.0).  Higher values
	// produce more random outputs.
	Temperature *float64 `json:"temperature,omitempty"`
	// TopP controls nucleus sampling.  Only tokens with cumulative probability
	// up to TopP are considered.
	TopP *float64 `json:"top_p,omitempty"`
	// TopK limits the number of highest-probability tokens considered at each
	// step.
	TopK *int `json:"top_k,omitempty"`
	// MaxTokens is the maximum number of tokens to generate.
	MaxTokens *int `json:"max_tokens,omitempty"`
	// Stop sequences where generation should stop.  Generation halts when any
	// of these strings is produced.
	Stop []string `json:"stop,omitempty"`
	// SessionID associates this request with a session for context tracking.
	SessionID string `json:"session_id,omitempty"`
	// Stream enables streaming response.  When true, the client should use
	// InferStream instead of Infer.
	Stream bool `json:"-"`
}

// Validate checks that the request has the minimum required fields.
func (r *InferenceRequest) Validate() error {
	if r.Prompt == "" {
		return fmt.Errorf("ainos: prompt is required")
	}
	if r.Model == "" {
		r.Model = "default"
	}
	if r.Temperature != nil && (*r.Temperature < 0.0 || *r.Temperature > 2.0) {
		return fmt.Errorf("ainos: temperature must be in [0.0, 2.0], got %f", *r.Temperature)
	}
	if r.MaxTokens != nil && *r.MaxTokens < 1 {
		return fmt.Errorf("ainos: max_tokens must be >= 1, got %d", *r.MaxTokens)
	}
	return nil
}

// InferenceResponse represents a response from a completed inference request.
type InferenceResponse struct {
	// Text is the generated output text.
	Text string `json:"output"`
	// TokensGenerated is the number of tokens produced.
	TokensGenerated int `json:"tokens_generated"`
	// InferenceMs is the wall-clock inference time in milliseconds.
	InferenceMs int64 `json:"inference_ms"`
	// Source indicates whether the inference was served locally or from the
	// cloud ("local" or "cloud").
	Source string `json:"source"`
	// TokensPerSecond is the generation throughput.
	TokensPerSecond float64 `json:"-"`
	// Model is the model that served the request.
	Model string `json:"-"`
	// Usage contains token usage information.
	Usage *UsageInfo `json:"-"`
}

// UsageInfo contains token usage statistics for a request.
type UsageInfo struct {
	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
	TotalTokens      int `json:"total_tokens"`
}

// InferenceChunk represents a single chunk from a streaming inference response.
type InferenceChunk struct {
	// Text is the text fragment produced by the model.
	Text string `json:"chunk"`
	// Index is the chunk sequence number.
	Index int `json:"-"`
	// FinishReason describes why generation stopped, if this is the final chunk.
	FinishReason string `json:"-"`
	// Done is true when this is the final chunk.
	Done bool `json:"done"`
}

// ---------------------------------------------------------------------------
// Model management
// ---------------------------------------------------------------------------

// ModelInfo represents metadata about a registered model.
type ModelInfo struct {
	// ID is the unique model identifier (e.g. "phi_3_mini_4k_instruct_q4_gguf").
	ID string `json:"id"`
	// Name is the human-readable model name (e.g. "phi-3-mini-4k-instruct-q4.gguf").
	Name string `json:"name"`
	// Path is the absolute file path on disk.
	Path string `json:"path"`
	// SizeMB is the model file size in megabytes.
	SizeMB int64 `json:"size_mb"`
	// Loaded indicates whether the model is currently loaded in memory.
	Loaded bool `json:"loaded"`
	// Architecture is the model architecture string (e.g. "auto", "phi3", "llama").
	Architecture string `json:"architecture"`
	// Quantized indicates the quantization level, if applicable.
	Quantized string `json:"-"`
}

// ModelLoadResponse is returned by the daemon after a model load request.
type ModelLoadResponse struct {
	ModelID   string     `json:"model_id"`
	Status    string     `json:"status"`
	Message   string     `json:"message"`
	ModelInfo *ModelInfo `json:"model_info,omitempty"`
}

// ModelUnloadResponse is returned by the daemon after a model unload request.
type ModelUnloadResponse struct {
	ModelID string `json:"model_id"`
	Status  string `json:"status"`
	Message string `json:"message"`
}

// ---------------------------------------------------------------------------
// System status
// ---------------------------------------------------------------------------

// SystemStatus represents the daemon's health and statistics.
type SystemStatus struct {
	// Uptime is the number of seconds since the daemon started.
	Uptime int64 `json:"uptime"`
	// ModelsLoaded is the number of models currently loaded in memory.
	ModelsLoaded int `json:"models_loaded"`
	// TotalRequests is the total number of inference requests handled.
	TotalRequests int64 `json:"total_requests"`
	// NetworkAvailable indicates whether the internet is reachable.
	NetworkAvailable bool `json:"network_available"`
	// ActiveSessions is the number of active client sessions.
	ActiveSessions int `json:"active_sessions"`
	// RateLimits contains per-category rate limit information, if available.
	RateLimits []RateLimitInfo `json:"rate_limits,omitempty"`
}

// HealthStatus is a simplified health check response.
type HealthStatus struct {
	// Status is the overall health status ("ok", "degraded", "error").
	Status string `json:"status"`
	// Uptime is the number of seconds since the daemon started.
	Uptime int64 `json:"uptime"`
	// Version is the daemon version string.
	Version string `json:"version,omitempty"`
	// ModelsLoaded is the number of loaded models.
	ModelsLoaded int `json:"models_loaded"`
	// MemoryUsage is the daemon's memory usage in MB.
	MemoryUsage float64 `json:"memory_usage,omitempty"`
	// CPUUsage is the daemon's CPU usage as a percentage.
	CPUUsage float64 `json:"cpu_usage,omitempty"`
	// PowerMode indicates the current power management mode.
	PowerMode string `json:"power_mode,omitempty"`
}

// ---------------------------------------------------------------------------
// Rate limiting
// ---------------------------------------------------------------------------

// RateLimitStatus represents the current rate limit status for the session.
type RateLimitStatus struct {
	// Limits contains per-category rate limit information.
	Limits []RateLimitInfo `json:"limits"`
}

// RateLimitInfo contains rate limit information for a single category.
type RateLimitInfo struct {
	// Category is the rate limit category (e.g. "inference", "model_ops",
	// "status", "admin").
	Category string `json:"category"`
	// Limit is the maximum number of requests allowed in the window.
	Limit int64 `json:"limit"`
	// Remaining is the number of requests remaining in the current window.
	Remaining int64 `json:"remaining"`
	// ResetSeconds is the number of seconds until the rate limit window resets.
	ResetSeconds int64 `json:"reset_seconds"`
}

// ---------------------------------------------------------------------------
// Context management
// ---------------------------------------------------------------------------

// ContextEntry represents a key-value entry in the daemon's context store.
type ContextEntry struct {
	// Key is the lookup key.
	Key string `json:"key"`
	// Value is the stored value.
	Value []byte `json:"-"`
	// StringValue is the string representation of the value.
	StringValue string `json:"value"`
	// SessionID is the session identifier.
	SessionID string `json:"session_id,omitempty"`
	// Timestamp is when the entry was stored.
	Timestamp time.Time `json:"-"`
	// TTL is the time-to-live in seconds.
	TTL int `json:"-"`
}

// ---------------------------------------------------------------------------
// Authentication
// ---------------------------------------------------------------------------

// AuthResponse is the response from an authentication request.
type AuthResponse struct {
	// Success indicates whether authentication was successful.
	Success bool `json:"success"`
	// SessionToken is the token for subsequent requests.
	SessionToken string `json:"session_token,omitempty"`
	// Message is a human-readable status message.
	Message string `json:"message"`
	// Permissions granted to the session.
	Permissions []string `json:"permissions"`
	// SessionTTLSeconds is the session TTL in seconds.
	SessionTTLSeconds int64 `json:"session_ttl_seconds"`
}

// SessionInfo contains information about the current session.
type SessionInfo struct {
	// Token is the session token.
	Token string
	// Permissions granted to this session.
	Permissions []string
	// TTL is the remaining time-to-live for the session.
	TTL time.Duration
	// Created is when the session was created.
	Created time.Time
}

// Permission constants.
const (
	PermissionInfer    = "infer"
	PermissionModelOps = "model_ops"
	PermissionStatus   = "status"
	PermissionAdmin    = "admin"
	PermissionAll      = "*"
)

// ---------------------------------------------------------------------------
// Connection pool types
// ---------------------------------------------------------------------------

// PoolConfig configures the connection pool used for batch operations.
type PoolConfig struct {
	// MaxSize is the maximum number of connections in the pool.
	MaxSize int
	// IdleTimeout is the maximum time a connection can remain idle before
	// being closed.
	IdleTimeout time.Duration
}

// DefaultPoolConfig returns a default connection pool configuration.
func DefaultPoolConfig() PoolConfig {
	return PoolConfig{
		MaxSize:     4,
		IdleTimeout: 60 * time.Second,
	}
}

// ---------------------------------------------------------------------------
// Internal wire-format helpers
// ---------------------------------------------------------------------------

// buildRequest builds a JSON-line request payload.
func buildRequest(msgType string, fields map[string]interface{}) ([]byte, error) {
	msg := make(map[string]interface{}, len(fields)+1)
	msg["type"] = msgType
	for k, v := range fields {
		if v != nil {
			msg[k] = v
		}
	}
	return json.Marshal(msg)
}

// parseResponseType extracts the "type" field from a raw JSON response
// without fully deserialising it.
func parseResponseType(data []byte) (string, error) {
	var env struct {
		Type string `json:"type"`
	}
	if err := json.Unmarshal(data, &env); err != nil {
		return "", err
	}
	return env.Type, nil
}

// extractDaemonError attempts to parse a daemon Error response.
func extractDaemonError(data []byte) *Error {
	var errResp struct {
		Code    int    `json:"code"`
		Message string `json:"message"`
	}
	if err := json.Unmarshal(data, &errResp); err != nil {
		return nil
	}
	return &Error{Code: errResp.Code, Message: errResp.Message}
}

// parseInferenceResponse parses an InferenceResponse from the daemon.
func parseInferenceResponse(data []byte) (*InferenceResponse, error) {
	var resp struct {
		Output          string `json:"output"`
		TokensGenerated int    `json:"tokens_generated"`
		InferenceMs     int64  `json:"inference_ms"`
		Source          string `json:"source"`
	}
	if err := json.Unmarshal(data, &resp); err != nil {
		return nil, fmt.Errorf("ainos: failed to parse inference response: %w", err)
	}
	r := &InferenceResponse{
		Text:            resp.Output,
		TokensGenerated: resp.TokensGenerated,
		InferenceMs:     resp.InferenceMs,
		Source:          resp.Source,
	}
	if r.InferenceMs > 0 && r.TokensGenerated > 0 {
		r.TokensPerSecond = float64(r.TokensGenerated) / (float64(r.InferenceMs) / 1000.0)
	}
	return r, nil
}

// parseInferenceChunk parses an InferenceChunk from the daemon.
func parseInferenceChunk(data []byte) (*InferenceChunk, error) {
	var chunk struct {
		Chunk string `json:"chunk"`
		Done  bool   `json:"done"`
	}
	if err := json.Unmarshal(data, &chunk); err != nil {
		return nil, fmt.Errorf("ainos: failed to parse inference chunk: %w", err)
	}
	return &InferenceChunk{
		Text: chunk.Chunk,
		Done: chunk.Done,
	}, nil
}

// parseModelListResponse parses a ModelListResponse from the daemon.
func parseModelListResponse(data []byte) ([]*ModelInfo, error) {
	var resp struct {
		Models []*ModelInfo `json:"models"`
	}
	if err := json.Unmarshal(data, &resp); err != nil {
		return nil, fmt.Errorf("ainos: failed to parse model list: %w", err)
	}
	return resp.Models, nil
}

// parseStatusResponse parses a StatusResponse from the daemon.
func parseStatusResponse(data []byte) (*SystemStatus, error) {
	var resp SystemStatus
	if err := json.Unmarshal(data, &resp); err != nil {
		return nil, fmt.Errorf("ainos: failed to parse status response: %w", err)
	}
	return &resp, nil
}

// parseAuthResponse parses an AuthResponse from the daemon.
func parseAuthResponse(data []byte) (*AuthResponse, error) {
	var resp AuthResponse
	if err := json.Unmarshal(data, &resp); err != nil {
		return nil, fmt.Errorf("ainos: failed to parse auth response: %w", err)
	}
	return &resp, nil
}

// parseModelLoadResponse parses a ModelLoadResponse from the daemon.
func parseModelLoadResponse(data []byte) (*ModelLoadResponse, error) {
	var resp ModelLoadResponse
	if err := json.Unmarshal(data, &resp); err != nil {
		return nil, fmt.Errorf("ainos: failed to parse model load response: %w", err)
	}
	return &resp, nil
}

// parseModelUnloadResponse parses a ModelUnloadResponse from the daemon.
func parseModelUnloadResponse(data []byte) (*ModelUnloadResponse, error) {
	var resp ModelUnloadResponse
	if err := json.Unmarshal(data, &resp); err != nil {
		return nil, fmt.Errorf("ainos: failed to parse model unload response: %w", err)
	}
	return &resp, nil
}

// parseRateLimitStatus parses a RateLimitStatus response from the daemon.
func parseRateLimitStatus(data []byte) (*RateLimitStatus, error) {
	var resp RateLimitStatus
	if err := json.Unmarshal(data, &resp); err != nil {
		return nil, fmt.Errorf("ainos: failed to parse rate limit status: %w", err)
	}
	return &resp, nil
}