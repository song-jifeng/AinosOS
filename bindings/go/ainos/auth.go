package ainos

import (
	"fmt"
	"sync"
	"time"
)

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

// Authenticator manages authentication with the Ainos daemon.
type Authenticator struct {
	mu            sync.RWMutex
	transport     *Transport
	token         string
	sessionToken  string
	authenticated bool
	permissions   []string
	sessionTTL    time.Duration
	sessionCreated time.Time
	autoRefresh   bool
}

// NewAuthenticator creates a new Authenticator that uses the given transport
// and bearer token.
func NewAuthenticator(transport *Transport, token string) *Authenticator {
	return &Authenticator{
		transport:   transport,
		token:       token,
		autoRefresh: true,
	}
}

// Authenticate performs authentication with the daemon.
//
// It sends an Auth message with the bearer token and processes the
// AuthResponse.  On success, the session token and permissions are stored
// for subsequent requests.
func (a *Authenticator) Authenticate() (*AuthResponse, error) {
	if a.token == "" {
		return nil, ErrNoAuthToken
	}

	data, err := a.transport.RoundTripTyped(msgTypeAuth, msgTypeAuthResponse, map[string]interface{}{
		"token": a.token,
	})
	if err != nil {
		return nil, &AuthError{Message: err.Error()}
	}

	resp, err := parseAuthResponse(data)
	if err != nil {
		return nil, &ProtocolError{Message: fmt.Sprintf("invalid auth response: %v", err)}
	}

	if !resp.Success {
		return nil, &AuthError{Message: resp.Message}
	}

	a.mu.Lock()
	a.sessionToken = resp.SessionToken
	a.authenticated = true
	a.permissions = resp.Permissions
	a.sessionTTL = time.Duration(resp.SessionTTLSeconds) * time.Second
	a.sessionCreated = time.Now()
	a.mu.Unlock()

	return resp, nil
}

// IsAuthenticated returns true if the client has been authenticated.
func (a *Authenticator) IsAuthenticated() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.authenticated
}

// SessionToken returns the current session token.
func (a *Authenticator) SessionToken() string {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.sessionToken
}

// Permissions returns the permissions granted to the current session.
func (a *Authenticator) Permissions() []string {
	a.mu.RLock()
	defer a.mu.RUnlock()
	p := make([]string, len(a.permissions))
	copy(p, a.permissions)
	return p
}

// HasPermission checks whether the current session has a specific permission.
func (a *Authenticator) HasPermission(perm string) bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	if !a.authenticated {
		return false
	}
	for _, p := range a.permissions {
		if p == PermissionAll || p == perm {
			return true
		}
	}
	return false
}

// SessionInfo returns information about the current session.
func (a *Authenticator) SessionInfo() *SessionInfo {
	a.mu.RLock()
	defer a.mu.RUnlock()
	if !a.authenticated {
		return nil
	}
	elapsed := time.Since(a.sessionCreated)
	remaining := a.sessionTTL - elapsed
	if remaining < 0 {
		remaining = 0
	}
	return &SessionInfo{
		Token:       a.sessionToken,
		Permissions: a.permissions,
		TTL:         remaining,
		Created:     a.sessionCreated,
	}
}

// SessionExpired returns true if the session has expired.
func (a *Authenticator) SessionExpired() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	if !a.authenticated {
		return true
	}
	if a.sessionTTL == 0 {
		return false // no expiry
	}
	return time.Since(a.sessionCreated) >= a.sessionTTL
}

// Refresh re-authenticates using the stored token.  This is useful when the
// session has expired.
func (a *Authenticator) Refresh() (*AuthResponse, error) {
	if a.token == "" {
		return nil, ErrNoAuthToken
	}
	return a.Authenticate()
}

// Clear resets the authentication state (e.g. on disconnect).
func (a *Authenticator) Clear() {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.sessionToken = ""
	a.authenticated = false
	a.permissions = nil
	a.sessionTTL = 0
	a.sessionCreated = time.Time{}
}

// SetToken updates the bearer token used for authentication.
func (a *Authenticator) SetToken(token string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.token = token
}

// ---------------------------------------------------------------------------
// Token management
// ---------------------------------------------------------------------------

// TokenAuth provides Bearer token helpers.
type TokenAuth struct {
	Token string
}

// BearerHeader returns the Authorization header value for this token.
func (t *TokenAuth) BearerHeader() string {
	return "Bearer " + t.Token
}

// IsValid checks whether the token meets minimum length requirements.
func (t *TokenAuth) IsValid() bool {
	return len(t.Token) >= 8
}

// Mask returns a masked version of the token for logging (e.g. "abc...xyz").
func (t *TokenAuth) Mask() string {
	if len(t.Token) <= 8 {
		return "****"
	}
	return t.Token[:4] + "..." + t.Token[len(t.Token)-4:]
}