package ainos

import "time"

// ---------------------------------------------------------------------------
// RequestOption
// ---------------------------------------------------------------------------

// RequestOption is a functional option for configuring an InferenceRequest.
type RequestOption interface {
	apply(*InferenceRequest)
}

type requestOptionFunc func(*InferenceRequest)

func (f requestOptionFunc) apply(r *InferenceRequest) { f(r) }

// WithTemperature sets the sampling temperature (0.0–2.0).
func WithTemperature(t float64) RequestOption {
	return requestOptionFunc(func(r *InferenceRequest) {
		r.Temperature = &t
	})
}

// WithTopP sets the nucleus sampling threshold (0.0–1.0).
func WithTopP(p float64) RequestOption {
	return requestOptionFunc(func(r *InferenceRequest) {
		r.TopP = &p
	})
}

// WithTopK limits the number of top tokens considered at each step.
func WithTopK(k int) RequestOption {
	return requestOptionFunc(func(r *InferenceRequest) {
		r.TopK = &k
	})
}

// WithMaxTokens sets the maximum number of tokens to generate.
func WithMaxTokens(n int) RequestOption {
	return requestOptionFunc(func(r *InferenceRequest) {
		r.MaxTokens = &n
	})
}

// WithStop sets the stop sequences where generation halts.
func WithStop(seqs []string) RequestOption {
	return requestOptionFunc(func(r *InferenceRequest) {
		r.Stop = seqs
	})
}

// WithStream enables streaming mode for the inference request.
func WithStream(stream bool) RequestOption {
	return requestOptionFunc(func(r *InferenceRequest) {
		r.Stream = stream
	})
}

// WithModel sets the model identifier for the request.
func WithModel(model string) RequestOption {
	return requestOptionFunc(func(r *InferenceRequest) {
		r.Model = model
	})
}

// WithSessionID sets the session identifier for context tracking.
func WithSessionID(sessionID string) RequestOption {
	return requestOptionFunc(func(r *InferenceRequest) {
		r.SessionID = sessionID
	})
}

// ---------------------------------------------------------------------------
// ClientOption
// ---------------------------------------------------------------------------

// ClientOption is a functional option for configuring a Client.
type ClientOption interface {
	apply(*Client)
}

type clientOptionFunc func(*Client)

func (f clientOptionFunc) apply(c *Client) { f(c) }

// WithHost sets the daemon hostname.
func WithHost(host string) ClientOption {
	return clientOptionFunc(func(c *Client) {
		c.config.Host = host
	})
}

// WithPort sets the daemon TCP port.
func WithPort(port int) ClientOption {
	return clientOptionFunc(func(c *Client) {
		c.config.Port = port
	})
}

// WithConnectTimeout sets the connection timeout.
func WithConnectTimeout(d time.Duration) ClientOption {
	return clientOptionFunc(func(c *Client) {
		c.config.ConnectTimeout = d
	})
}

// WithReadTimeout sets the read timeout for responses.
func WithReadTimeout(d time.Duration) ClientOption {
	return clientOptionFunc(func(c *Client) {
		c.config.ReadTimeout = d
	})
}

// WithWriteTimeout sets the write timeout for requests.
func WithWriteTimeout(d time.Duration) ClientOption {
	return clientOptionFunc(func(c *Client) {
		c.config.WriteTimeout = d
	})
}

// WithTimeout sets both connect and read timeouts.
func WithTimeout(d time.Duration) ClientOption {
	return clientOptionFunc(func(c *Client) {
		c.config.ConnectTimeout = d
		c.config.ReadTimeout = d
	})
}

// WithAutoReconnect enables or disables automatic reconnection.
func WithAutoReconnect(enabled bool) ClientOption {
	return clientOptionFunc(func(c *Client) {
		c.config.AutoReconnect = enabled
	})
}

// WithReconnectDelay sets the initial delay before reconnection.
func WithReconnectDelay(d time.Duration) ClientOption {
	return clientOptionFunc(func(c *Client) {
		c.config.ReconnectDelay = d
	})
}

// WithMaxReconnectAttempts sets the maximum number of reconnection attempts.
func WithMaxReconnectAttempts(n int) ClientOption {
	return clientOptionFunc(func(c *Client) {
		c.config.MaxReconnectAttempts = n
	})
}

// WithAuthToken sets the bearer token for authentication.
func WithAuthToken(token string) ClientOption {
	return clientOptionFunc(func(c *Client) {
		c.config.AuthToken = token
	})
}

// WithAutoAuthenticate enables or disables automatic authentication.
func WithAutoAuthenticate(enabled bool) ClientOption {
	return clientOptionFunc(func(c *Client) {
		c.config.AutoAuthenticate = enabled
	})
}

// WithTLS enables TLS encryption.
func WithTLS(enabled bool) ClientOption {
	return clientOptionFunc(func(c *Client) {
		c.config.TLS = enabled
	})
}

// WithTLSInsecureSkipVerify controls TLS certificate verification.
func WithTLSInsecureSkipVerify(skip bool) ClientOption {
	return clientOptionFunc(func(c *Client) {
		c.config.TLSInsecureSkipVerify = skip
	})
}

// WithRetryConfig sets the retry configuration.
func WithRetryConfig(rc RetryConfig) ClientOption {
	return clientOptionFunc(func(c *Client) {
		c.config.RetryConfig = rc
	})
}

// ---------------------------------------------------------------------------
// NewRequest convenience builder
// ---------------------------------------------------------------------------

// NewRequest creates a new InferenceRequest with the given prompt and options.
func NewRequest(prompt string, opts ...RequestOption) *InferenceRequest {
	r := &InferenceRequest{
		Prompt: prompt,
		Model:  "default",
	}
	for _, opt := range opts {
		opt.apply(r)
	}
	return r
}