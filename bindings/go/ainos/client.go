package ainos

import (
	"context"
	"fmt"
	"log"
	"math"
	"sync"
	"time"
)

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

// Client is the main entry point for interacting with the Ainos AI Daemon.
//
// It manages a TCP connection to the daemon and provides methods for
// inference, model management, context storage, and system monitoring.
// All public methods are thread-safe.
//
// Basic usage:
//
//	client := ainos.NewClient()
//	if err := client.Connect(); err != nil {
//	    log.Fatal(err)
//	}
//	defer client.Disconnect()
//
//	resp, err := client.Infer(context.Background(), &ainos.InferenceRequest{
//	    Prompt: "Hello, world!",
//	})
type Client struct {
	mu sync.RWMutex

	config ClientConfig

	// transport is the underlying TCP connection.
	transport *Transport

	// auth manages authentication state.
	auth *Authenticator

	// pool is the connection pool for batch operations.
	pool *ConnPool

	// heartbeat controls the keepalive goroutine.
	heartbeatStop chan struct{}

	// connected guards.
	connected bool

	// reconnectAttempts tracks the current reconnect backoff.
	reconnectAttempts int

	// logger for client-side logging.
	logger *log.Logger
}

// NewClient creates a new Client with the given options.
//
// If no options are provided, the default configuration is used, which
// connects to 127.0.0.1:9500 with a 5-second connect timeout.
//
//	client := ainos.NewClient(ainos.WithHost("192.168.1.100"), ainos.WithPort(9500))
func NewClient(opts ...ClientOption) *Client {
	c := &Client{
		config:        DefaultConfig(),
		heartbeatStop: make(chan struct{}),
		logger:        log.Default(),
	}

	for _, opt := range opts {
		opt.apply(c)
	}

	return c
}

// ---------------------------------------------------------------------------
// Connection management
// ---------------------------------------------------------------------------

// Connect establishes a TCP connection to the Ainos daemon.
//
// If AuthToken is configured and AutoAuthenticate is true, this also
// performs authentication.
func (c *Client) Connect() error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.connected {
		return nil
	}

	// Create transport
	transport := NewTransport(
		c.config.Host,
		c.config.Port,
		c.config.ConnectTimeout,
	)
	transport.SetReadTimeout(c.config.ReadTimeout)
	transport.SetWriteTimeout(c.config.WriteTimeout)

	if c.config.TLS {
		transport.EnableTLS(c.config.TLSInsecureSkipVerify)
	}

	// Dial
	if err := transport.Dial(); err != nil {
		return err
	}

	c.transport = transport

	// Create authenticator
	if c.config.AuthToken != "" {
		c.auth = NewAuthenticator(transport, c.config.AuthToken)
	}

	c.connected = true
	c.reconnectAttempts = 0

	// Start heartbeat
	c.heartbeatStop = make(chan struct{})
	go c.heartbeatLoop()

	// Auto-authenticate
	if c.auth != nil && c.config.AutoAuthenticate {
		if _, err := c.auth.Authenticate(); err != nil {
			// Authentication failed, but we're still connected
			c.logger.Printf("ainos: auto-authentication failed: %v", err)
			return err
		}
		c.logger.Printf("ainos: authenticated successfully")
	}

	c.logger.Printf("ainos: connected to %s:%d", c.config.Host, c.config.Port)
	return nil
}

// Disconnect closes the connection to the daemon.
func (c *Client) Disconnect() error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if !c.connected {
		return nil
	}

	// Stop heartbeat
	select {
	case <-c.heartbeatStop:
		// already closed
	default:
		close(c.heartbeatStop)
	}

	// Close pool if open
	if c.pool != nil {
		c.pool.Close()
		c.pool = nil
	}

	// Clear auth state
	if c.auth != nil {
		c.auth.Clear()
	}

	// Close transport
	var err error
	if c.transport != nil {
		err = c.transport.Close()
	}

	c.transport = nil
	c.connected = false
	c.logger.Printf("ainos: disconnected")
	return err
}

// Reconnect closes the current connection and establishes a new one.
func (c *Client) Reconnect() error {
	c.Disconnect()
	return c.Connect()
}

// IsConnected returns whether the client is currently connected.
func (c *Client) IsConnected() bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.connected && c.transport != nil && c.transport.IsConnected()
}

// heartbeatLoop periodically sends keepalive pings to the daemon.
// It uses the Status message as a lightweight health check.
func (c *Client) heartbeatLoop() {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			c.mu.RLock()
			connected := c.connected
			c.mu.RUnlock()

			if !connected {
				return
			}

			// Send a lightweight status request as heartbeat
			if _, err := c.statusInternal(); err != nil {
				c.mu.Lock()
				c.connected = false
				c.mu.Unlock()
				c.logger.Printf("ainos: heartbeat failed: %v", err)

				if c.config.AutoReconnect {
					go c.attemptReconnect()
				}
				return
			}

		case <-c.heartbeatStop:
			return
		}
	}
}

// attemptReconnect tries to reconnect with exponential backoff.
func (c *Client) attemptReconnect() {
	c.mu.Lock()
	attempts := c.reconnectAttempts
	c.reconnectAttempts++
	maxAttempts := c.config.MaxReconnectAttempts
	delay := c.config.ReconnectDelay
	backoff := time.Duration(math.Pow(2, float64(attempts))) * delay
	if backoff > 30*time.Second {
		backoff = 30 * time.Second
	}
	c.mu.Unlock()

	if maxAttempts > 0 && attempts >= maxAttempts {
		c.logger.Printf("ainos: max reconnect attempts (%d) reached", maxAttempts)
		return
	}

	c.logger.Printf("ainos: reconnecting in %v (attempt %d)", backoff, attempts+1)
	time.Sleep(backoff)

	if err := c.Reconnect(); err != nil {
		c.logger.Printf("ainos: reconnect failed: %v", err)
		go c.attemptReconnect()
	} else {
		c.logger.Printf("ainos: reconnected successfully")
	}
}

// ---------------------------------------------------------------------------
// Auth methods
// ---------------------------------------------------------------------------

// Authenticate performs authentication with the daemon.
//
// This is only needed if the client was created without an auth token, or
// if the session has expired.
func (c *Client) Authenticate(token string) (*AuthResponse, error) {
	c.mu.Lock()
	auth := c.auth
	c.mu.Unlock()

	if auth == nil {
		c.mu.Lock()
		if c.transport == nil {
			c.mu.Unlock()
			return nil, ErrNotConnected
		}
		auth = NewAuthenticator(c.transport, token)
		c.auth = auth
		c.mu.Unlock()
	} else {
		auth.SetToken(token)
	}

	return auth.Authenticate()
}

// Session returns information about the current authenticated session.
func (c *Client) Session() *SessionInfo {
	c.mu.RLock()
	auth := c.auth
	c.mu.RUnlock()

	if auth == nil {
		return nil
	}
	return auth.SessionInfo()
}

// IsAuthenticated returns whether the client has been authenticated.
func (c *Client) IsAuthenticated() bool {
	c.mu.RLock()
	auth := c.auth
	c.mu.RUnlock()

	if auth == nil {
		// If no auth token configured, we're considered "authenticated"
		// (the daemon may not require authentication).
		return true
	}
	return auth.IsAuthenticated()
}

// HasPermission checks whether the current session has a specific permission.
func (c *Client) HasPermission(perm string) bool {
	c.mu.RLock()
	auth := c.auth
	c.mu.RUnlock()

	if auth == nil {
		return true
	}
	return auth.HasPermission(perm)
}

// ---------------------------------------------------------------------------
// Transport access (internal)
// ---------------------------------------------------------------------------

// getTransport returns the current transport, attempting reconnection if
// configured and the transport is nil.
func (c *Client) getTransport() (*Transport, error) {
	c.mu.RLock()
	t := c.transport
	connected := c.connected
	c.mu.RUnlock()

	if t != nil && connected {
		return t, nil
	}

	// Auto-reconnect
	if c.config.AutoReconnect {
		c.mu.Lock()
		// Double-check
		if !c.connected || c.transport == nil {
			c.logger.Printf("ainos: reconnecting...")
			// Create a new transport and connect
			transport := NewTransport(
				c.config.Host,
				c.config.Port,
				c.config.ConnectTimeout,
			)
			transport.SetReadTimeout(c.config.ReadTimeout)
			transport.SetWriteTimeout(c.config.WriteTimeout)
			if c.config.TLS {
				transport.EnableTLS(c.config.TLSInsecureSkipVerify)
			}
			if err := transport.Dial(); err != nil {
				c.mu.Unlock()
				return nil, err
			}
			c.transport = transport
			c.connected = true

			// Re-authenticate if needed
			if c.auth != nil && c.config.AutoAuthenticate {
				if _, err := c.auth.Authenticate(); err != nil {
					c.mu.Unlock()
					c.logger.Printf("ainos: re-authentication failed: %v", err)
					return transport, nil // return transport anyway, auth may not be required
				}
			}
			t = transport
		}
		c.mu.Unlock()
		return t, nil
	}

	return nil, ErrNotConnected
}

// ---------------------------------------------------------------------------
// Core RPC methods
// ---------------------------------------------------------------------------

// sendRequest is a helper that sends a request, reads the response, and
// checks the response type.  It handles retries and authentication.
func (c *Client) sendRequest(ctx context.Context, msgType, expectedType string, fields map[string]interface{}) ([]byte, error) {
	var lastErr error

	rc := c.config.RetryConfig
	maxRetries := rc.MaxRetries
	if maxRetries < 0 {
		maxRetries = 0
	}

	for attempt := 0; attempt <= maxRetries; attempt++ {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
		}

		transport, err := c.getTransport()
		if err != nil {
			return nil, err
		}

		data, err := transport.RoundTripTyped(msgType, expectedType, fields)
		if err == nil {
			return data, nil
		}

		lastErr = err

		// Check if we should retry
		if attempt < maxRetries && IsRetryable(err) {
			backoff := rc.Backoff(attempt)
			c.logger.Printf("ainos: retrying %s (attempt %d/%d) after %v: %v",
				msgType, attempt+1, maxRetries, backoff, err)

			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-time.After(backoff):
			}
			continue
		}

		break
	}

	return nil, lastErr
}

// statusInternal sends a Status request and returns the raw response.
// Used internally by the heartbeat.
func (c *Client) statusInternal() (*SystemStatus, error) {
	transport, err := c.getTransport()
	if err != nil {
		return nil, err
	}

	data, err := transport.RoundTripTyped(msgTypeStatus, msgTypeStatusResponse, nil)
	if err != nil {
		return nil, err
	}

	return parseStatusResponse(data)
}

// ---------------------------------------------------------------------------
// Public API: Inference
// ---------------------------------------------------------------------------

// Infer sends an inference request and returns the complete response.
//
//	req := &ainos.InferenceRequest{
//	    Prompt: "What is the meaning of life?",
//	    Model:  "default",
//	}
//	resp, err := client.Infer(ctx, req)
func (c *Client) Infer(ctx context.Context, req *InferenceRequest) (*InferenceResponse, error) {
	if err := req.Validate(); err != nil {
		return nil, err
	}

	fields := map[string]interface{}{
		"model":  req.Model,
		"prompt": req.Prompt,
	}
	if req.Temperature != nil {
		fields["temperature"] = *req.Temperature
	}
	if req.MaxTokens != nil {
		fields["max_tokens"] = *req.MaxTokens
	}
	if req.SessionID != "" {
		fields["session_id"] = req.SessionID
	}

	data, err := c.sendRequest(ctx, msgTypeInference, msgTypeInferenceResponse, fields)
	if err != nil {
		// Wrap daemon errors as InferenceError
		if daemonErr, ok := err.(*Error); ok {
			return nil, &InferenceError{
				Message: daemonErr.Message,
				Code:    daemonErr.Code,
			}
		}
		return nil, err
	}

	resp, err := parseInferenceResponse(data)
	if err != nil {
		return nil, err
	}
	resp.Model = req.Model
	return resp, nil
}

// InferStream sends a streaming inference request and returns a channel of
// chunks.  The caller MUST consume chunks from the channel until it is
// closed, otherwise a goroutine leak will occur.
//
//	chunks, err := client.InferStream(ctx, req)
//	if err != nil { ... }
//	for chunk := range chunks {
//	    fmt.Print(chunk.Text)
//	}
func (c *Client) InferStream(ctx context.Context, req *InferenceRequest) (<-chan *InferenceChunk, error) {
	if err := req.Validate(); err != nil {
		return nil, err
	}

	transport, err := c.getTransport()
	if err != nil {
		return nil, err
	}

	reader, err := startInferStream(ctx, transport, req)
	if err != nil {
		return nil, err
	}

	return reader.Chunks(), nil
}

// ---------------------------------------------------------------------------
// Public API: System status
// ---------------------------------------------------------------------------

// Status queries the daemon's health and statistics.
func (c *Client) Status() (*SystemStatus, error) {
	transport, err := c.getTransport()
	if err != nil {
		return nil, err
	}

	data, err := transport.RoundTripTyped(msgTypeStatus, msgTypeStatusResponse, nil)
	if err != nil {
		return nil, err
	}

	return parseStatusResponse(data)
}

// Health performs a simplified health check.
func (c *Client) Health() (*HealthStatus, error) {
	status, err := c.Status()
	if err != nil {
		return nil, err
	}

	health := &HealthStatus{
		Status:       "ok",
		Uptime:       status.Uptime,
		ModelsLoaded: status.ModelsLoaded,
	}

	if status.TotalRequests < 0 {
		health.Status = "degraded"
	}

	return health, nil
}

// ---------------------------------------------------------------------------
// Public API: Model management
// ---------------------------------------------------------------------------

// ModelList returns a list of all registered models.
func (c *Client) ModelList() ([]*ModelInfo, error) {
	transport, err := c.getTransport()
	if err != nil {
		return nil, err
	}

	data, err := transport.RoundTripTyped(msgTypeModelList, msgTypeModelListResponse, nil)
	if err != nil {
		return nil, err
	}

	return parseModelListResponse(data)
}

// ModelLoad loads a model from the given file path.
//
// opts can be used to pass additional options such as architecture hints.
func (c *Client) ModelLoad(path string, opts map[string]interface{}) (*ModelInfo, error) {
	transport, err := c.getTransport()
	if err != nil {
		return nil, err
	}

	fields := map[string]interface{}{
		"path": path,
	}
	for k, v := range opts {
		fields[k] = v
	}

	data, err := transport.RoundTripTyped(msgTypeModelLoad, msgTypeModelLoadResponse, fields)
	if err != nil {
		return nil, err
	}

	resp, err := parseModelLoadResponse(data)
	if err != nil {
		return nil, err
	}

	if resp.Status == "error" {
		return nil, &Error{
			Code:    -1,
			Message: fmt.Sprintf("model load failed: %s", resp.Message),
		}
	}

	return resp.ModelInfo, nil
}

// ModelUnload unloads a model by its ID.
func (c *Client) ModelUnload(id string) error {
	transport, err := c.getTransport()
	if err != nil {
		return err
	}

	data, err := transport.RoundTripTyped(msgTypeModelUnload, msgTypeModelUnloadResponse, map[string]interface{}{
		"model_id": id,
	})
	if err != nil {
		return err
	}

	resp, err := parseModelUnloadResponse(data)
	if err != nil {
		return err
	}

	if resp.Status == "error" {
		return &Error{
			Code:    -1,
			Message: fmt.Sprintf("model unload failed: %s", resp.Message),
		}
	}

	return nil
}

// ---------------------------------------------------------------------------
// Public API: Context management
// ---------------------------------------------------------------------------

// ContextStore stores a key-value pair in the daemon's context store.
//
// sessionID is optional (can be empty).  ttl is the time-to-live in seconds
// (0 means no expiry).
func (c *Client) ContextStore(sessionID, key string, value []byte, ttl int) error {
	transport, err := c.getTransport()
	if err != nil {
		return err
	}

	fields := map[string]interface{}{
		"key":   key,
		"value": string(value),
	}
	if sessionID != "" {
		fields["session_id"] = sessionID
	}
	if ttl > 0 {
		fields["ttl"] = ttl
	}

	data, err := transport.RoundTripTyped(msgTypeContextStore, msgTypeInferenceResponse, fields)
	if err != nil {
		return err
	}

	// Parse the response (it's an InferenceResponse with output message)
	resp, err := parseInferenceResponse(data)
	if err != nil {
		return err
	}
	_ = resp // success confirmation
	return nil
}

// ContextRetrieve retrieves a value by key from the daemon's context store.
func (c *Client) ContextRetrieve(sessionID, key string) ([]byte, error) {
	transport, err := c.getTransport()
	if err != nil {
		return nil, err
	}

	fields := map[string]interface{}{
		"key": key,
	}
	if sessionID != "" {
		fields["session_id"] = sessionID
	}

	data, err := transport.RoundTrip(msgTypeContextRetrieve, fields)
	if err != nil {
		return nil, err
	}

	// Check response type
	respType, err := parseResponseType(data)
	if err != nil {
		return nil, &ProtocolError{Message: fmt.Sprintf("invalid response: %v", err)}
	}

	switch respType {
	case msgTypeInferenceResponse:
		resp, err := parseInferenceResponse(data)
		if err != nil {
			return nil, err
		}
		return []byte(resp.Text), nil

	case msgTypeError:
		daemonErr := extractDaemonError(data)
		if daemonErr != nil {
			return nil, daemonErr
		}
		return nil, &Error{Code: -1, Message: "unknown daemon error"}

	default:
		return nil, &ProtocolError{
			Message: fmt.Sprintf("unexpected response type for context retrieve: %q", respType),
		}
	}
}

// ---------------------------------------------------------------------------
// Public API: Batch operations
// ---------------------------------------------------------------------------

// BatchInfer sends multiple inference requests concurrently.
//
// This uses a connection pool for parallel execution.  Results are returned
// in the same order as the requests.  If any request fails, the error is
// returned at the corresponding index; other requests continue.
func (c *Client) BatchInfer(ctx context.Context, reqs []*InferenceRequest) ([]*InferenceResponse, error) {
	if len(reqs) == 0 {
		return nil, nil
	}

	// Initialize connection pool
	c.mu.Lock()
	if c.pool == nil {
		c.pool = NewConnPool(c.config.Host, c.config.Port, DefaultPoolConfig())
	}
	pool := c.pool
	c.mu.Unlock()

	type result struct {
		index int
		resp  *InferenceResponse
		err   error
	}

	results := make(chan result, len(reqs))

	for i, req := range reqs {
		go func(idx int, r *InferenceRequest) {
			// Get a transport from the pool
			t, err := pool.Acquire()
			if err != nil {
				results <- result{idx, nil, err}
				return
			}
			defer pool.Release(t)

			// Build the request
			fields := map[string]interface{}{
				"model":  r.Model,
				"prompt": r.Prompt,
			}
			if r.Temperature != nil {
				fields["temperature"] = *r.Temperature
			}
			if r.MaxTokens != nil {
				fields["max_tokens"] = *r.MaxTokens
			}

			// Send and receive
			data, err := t.RoundTripTyped(msgTypeInference, msgTypeInferenceResponse, fields)
			if err != nil {
				results <- result{idx, nil, err}
				return
			}

			resp, err := parseInferenceResponse(data)
			results <- result{idx, resp, err}
		}(i, req)
	}

	// Collect results in order
	responses := make([]*InferenceResponse, len(reqs))
	var firstErr error
	for range reqs {
		r := <-results
		if r.err != nil && firstErr == nil {
			firstErr = r.err
		}
		responses[r.index] = r.resp
	}

	return responses, firstErr
}

// ---------------------------------------------------------------------------
// Public API: Rate limiting
// ---------------------------------------------------------------------------

// RateLimitStatus queries the current rate limit status for this session.
func (c *Client) RateLimitStatus() (*RateLimitStatus, error) {
	transport, err := c.getTransport()
	if err != nil {
		return nil, err
	}

	data, err := transport.RoundTrip(msgTypeRateLimitStatus, nil)
	if err != nil {
		return nil, err
	}

	// The daemon may return a RateLimitStatusResponse or Error
	respType, err := parseResponseType(data)
	if err != nil {
		return nil, &ProtocolError{Message: fmt.Sprintf("invalid response: %v", err)}
	}

	switch respType {
	case msgTypeError:
		daemonErr := extractDaemonError(data)
		if daemonErr != nil {
			return nil, daemonErr
		}
		return nil, &Error{Code: -1, Message: "unknown daemon error"}

	default:
		// Try to parse as RateLimitStatus (the daemon may return various
		// response types for this endpoint).
		status, err := parseRateLimitStatus(data)
		if err != nil {
			return nil, &ProtocolError{
				Message: fmt.Sprintf("unexpected response type %q: %v", respType, err),
			}
		}
		return status, nil
	}
}

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// Config returns a copy of the client's current configuration.
func (c *Client) Config() ClientConfig {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.config
}

// SetLogger sets the logger used by the client.
func (c *Client) SetLogger(logger *log.Logger) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.logger = logger
}

// ---------------------------------------------------------------------------
// Stringer
// ---------------------------------------------------------------------------

func (c *Client) String() string {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return fmt.Sprintf("AinosClient(%s:%d, connected=%v)", c.config.Host, c.config.Port, c.connected)
}