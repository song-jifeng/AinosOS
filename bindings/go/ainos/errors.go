// Package ainos provides a Go SDK for the Ainos AI Daemon.
//
// The SDK communicates with the daemon over TCP using newline-delimited JSON
// (NDJSON) protocol on port 9500.  It supports inference, model management,
// context storage, streaming, authentication, and rate-limit handling.
package ainos

import (
	"errors"
	"fmt"
	"time"
)

// ---------------------------------------------------------------------------
// Sentinel errors
// ---------------------------------------------------------------------------

// Package-level sentinel errors for simple failure cases.
var (
	// ErrNotConnected is returned when an operation is attempted without an
	// active connection.
	ErrNotConnected = errors.New("ainos: not connected to daemon")

	// ErrAlreadyConnected is returned when Connect is called on an already-
	// connected client.
	ErrAlreadyConnected = errors.New("ainos: already connected")

	// ErrNoAuthToken is returned when authentication is attempted without
	// providing a token.
	ErrNoAuthToken = errors.New("ainos: no authentication token provided")

	// ErrAuthRequired is returned when the daemon requires authentication but
	// the client is not authenticated.
	ErrAuthRequired = errors.New("ainos: authentication required")

	// ErrSessionExpired is returned when the session token has expired.
	ErrSessionExpired = errors.New("ainos: session token expired")

	// ErrStreamClosed is returned when attempting to read from a closed stream.
	ErrStreamClosed = errors.New("ainos: stream closed")

	// ErrModelNotFound is returned when the requested model is not registered.
	ErrModelNotFound = errors.New("ainos: model not found")
)

// ---------------------------------------------------------------------------
// Error types
// ---------------------------------------------------------------------------

// Error is the structured error type returned by the Ainos daemon.
// It carries a numeric code and a human-readable message.
type Error struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Op      string `json:"-"` // the operation that failed
}

func (e *Error) Error() string {
	if e.Op != "" {
		return fmt.Sprintf("ainos: %s failed (code=%d): %s", e.Op, e.Code, e.Message)
	}
	return fmt.Sprintf("ainos: daemon error (code=%d): %s", e.Code, e.Message)
}

// Unwrap provides compatibility with errors.Is / errors.As for sentinel checks.
func (e *Error) Unwrap() error {
	switch e.Code {
	case 401:
		return ErrSessionExpired
	default:
		return nil
	}
}

// ConnectionError is returned when the SDK cannot establish or maintain a
// TCP connection to the Ainos daemon.
type ConnectionError struct {
	Op   string // the operation being attempted
	Addr string // the remote address
	Err  error  // the underlying error
}

func (e *ConnectionError) Error() string {
	return fmt.Sprintf("ainos: %s connection to %s: %v", e.Op, e.Addr, e.Err)
}

func (e *ConnectionError) Unwrap() error { return e.Err }

// AuthError is returned when authentication with the daemon fails.
type AuthError struct {
	Message string
}

func (e *AuthError) Error() string {
	return fmt.Sprintf("ainos: authentication failed: %s", e.Message)
}

// PermissionError is returned when the session lacks the required permission.
type PermissionError struct {
	Permission string
}

func (e *PermissionError) Error() string {
	return fmt.Sprintf("ainos: permission denied: %s", e.Permission)
}

// RateLimitError is returned when the daemon rate-limits a request.
type RateLimitError struct {
	Category    string
	RetryAfter  time.Duration
	Message     string
}

func (e *RateLimitError) Error() string {
	if e.RetryAfter > 0 {
		return fmt.Sprintf("ainos: rate limit exceeded for %q, retry after %v: %s",
			e.Category, e.RetryAfter, e.Message)
	}
	return fmt.Sprintf("ainos: rate limit exceeded for %q: %s", e.Category, e.Message)
}

// InferenceError is returned when an inference request fails.
type InferenceError struct {
	Message string
	Code    int
}

func (e *InferenceError) Error() string {
	return fmt.Sprintf("ainos: inference error (code=%d): %s", e.Code, e.Message)
}

// TimeoutError is returned when an operation exceeds the configured timeout.
type TimeoutError struct {
	Operation string
	Timeout   time.Duration
}

func (e *TimeoutError) Error() string {
	return fmt.Sprintf("ainos: %s timed out after %v", e.Operation, e.Timeout)
}

// ProtocolError is returned when the daemon sends an unexpected or malformed
// response.
type ProtocolError struct {
	Message string
}

func (e *ProtocolError) Error() string {
	return fmt.Sprintf("ainos: protocol error: %s", e.Message)
}

// ---------------------------------------------------------------------------
// Retry classification
// ---------------------------------------------------------------------------

// RetryKind classifies an error for retry decisions.
type RetryKind int

const (
	// RetryFatal indicates the error should not be retried.
	RetryFatal RetryKind = iota
	// RetryTransient indicates the error can be retried (possibly with backoff).
	RetryTransient
	// RetryThrottled indicates the error should be retried after a delay.
	RetryThrottled
)

// RetryKind returns the retry classification for the error.
func RetryKindOf(err error) RetryKind {
	if err == nil {
		return RetryFatal
	}

	switch e := err.(type) {
	case *ConnectionError:
		return RetryTransient
	case *TimeoutError:
		return RetryTransient
	case *RateLimitError:
		return RetryThrottled
	case *Error:
		if e.Code == 429 {
			return RetryThrottled
		}
		return RetryFatal
	case *AuthError, *PermissionError, *ProtocolError, *InferenceError:
		return RetryFatal
	}

	if errors.Is(err, ErrNotConnected) || errors.Is(err, ErrSessionExpired) {
		return RetryTransient
	}
	if errors.Is(err, ErrModelNotFound) {
		return RetryFatal
	}

	return RetryFatal
}

// IsRetryable returns true if the error can be retried.
func IsRetryable(err error) bool {
	return RetryKindOf(err) != RetryFatal
}

// ---------------------------------------------------------------------------
// Retry configuration
// ---------------------------------------------------------------------------

// RetryConfig controls automatic retry behaviour.
type RetryConfig struct {
	// MaxRetries is the maximum number of retry attempts (0 = no retries).
	MaxRetries int
	// InitialBackoff is the delay before the first retry.
	InitialBackoff time.Duration
	// MaxBackoff is the maximum delay between retries.
	MaxBackoff time.Duration
	// BackoffMultiplier is applied after each attempt (e.g. 2.0 = exponential).
	BackoffMultiplier float64
}

// DefaultRetryConfig returns a sensible default retry configuration.
func DefaultRetryConfig() RetryConfig {
	return RetryConfig{
		MaxRetries:        3,
		InitialBackoff:    100 * time.Millisecond,
		MaxBackoff:        10 * time.Second,
		BackoffMultiplier: 2.0,
	}
}

// Backoff computes the delay for a given attempt number (0-based).
func (rc RetryConfig) Backoff(attempt int) time.Duration {
	if attempt < 0 {
		attempt = 0
	}
	base := float64(rc.InitialBackoff) * pow(rc.BackoffMultiplier, attempt)
	if base > float64(rc.MaxBackoff) {
		return rc.MaxBackoff
	}
	return time.Duration(base)
}

func pow(base float64, exp int) float64 {
	result := 1.0
	for i := 0; i < exp; i++ {
		result *= base
	}
	return result
}

// ---------------------------------------------------------------------------
// Error classification helpers
// ---------------------------------------------------------------------------

// IsAuthError returns true if the error is related to authentication.
func IsAuthError(err error) bool {
	if err == nil {
		return false
	}
	switch err.(type) {
	case *AuthError, *PermissionError:
		return true
	}
	return errors.Is(err, ErrSessionExpired) || errors.Is(err, ErrAuthRequired)
}

// IsConnectionError returns true if the error is related to connectivity.
func IsConnectionError(err error) bool {
	if err == nil {
		return false
	}
	_, ok := err.(*ConnectionError)
	return ok || errors.Is(err, ErrNotConnected)
}

// IsTimeout returns true if the error is a timeout.
func IsTimeout(err error) bool {
	if err == nil {
		return false
	}
	_, ok := err.(*TimeoutError)
	return ok
}

// IsRateLimited returns true if the error is a rate-limit response.
func IsRateLimited(err error) bool {
	if err == nil {
		return false
	}
	_, ok := err.(*RateLimitError)
	return ok
}

// DaemonCode extracts the daemon error code, if the error carries one.
func DaemonCode(err error) (int, bool) {
	if err == nil {
		return 0, false
	}
	switch e := err.(type) {
	case *Error:
		return e.Code, true
	case *InferenceError:
		return e.Code, true
	}
	return 0, false
}