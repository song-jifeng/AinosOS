package ainos

import (
	"bufio"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"net"
	"sync"
	"time"
)

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

// Transport manages a single TCP connection to the Ainos daemon, providing
// thread-safe NDJSON message send and receive operations.
type Transport struct {
	mu       sync.Mutex
	conn     net.Conn
	reader   *bufio.Reader
	host     string
	port     int
	dialTimeout time.Duration
	readTimeout  time.Duration
	writeTimeout time.Duration
	useTLS       bool
	tlsConfig    *tls.Config
	connected    bool
}

// NewTransport creates a new Transport targeting the given address.
func NewTransport(host string, port int, timeout time.Duration) *Transport {
	return &Transport{
		host:        host,
		port:        port,
		dialTimeout: timeout,
		readTimeout: 120 * time.Second,
		writeTimeout: 10 * time.Second,
	}
}

// SetReadTimeout sets the read timeout for the transport.
func (t *Transport) SetReadTimeout(d time.Duration) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.readTimeout = d
}

// SetWriteTimeout sets the write timeout for the transport.
func (t *Transport) SetWriteTimeout(d time.Duration) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.writeTimeout = d
}

// EnableTLS configures TLS for the transport.
func (t *Transport) EnableTLS(insecureSkipVerify bool) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.useTLS = true
	t.tlsConfig = &tls.Config{
		InsecureSkipVerify: insecureSkipVerify,
	}
}

// Dial establishes a TCP connection to the daemon.
func (t *Transport) Dial() error {
	t.mu.Lock()
	defer t.mu.Unlock()

	if t.connected {
		return nil
	}

	addr := fmt.Sprintf("%s:%d", t.host, t.port)
	var conn net.Conn
	var err error

	if t.useTLS {
		dialer := &net.Dialer{Timeout: t.dialTimeout}
		conn, err = tls.DialWithDialer(dialer, "tcp", addr, t.tlsConfig)
	} else {
		conn, err = net.DialTimeout("tcp", addr, t.dialTimeout)
	}

	if err != nil {
		return &ConnectionError{
			Op:   "dial",
			Addr: addr,
			Err:  err,
		}
	}

	t.conn = conn
	t.reader = bufio.NewReaderSize(conn, 64*1024) // 64 KB buffer
	t.connected = true
	return nil
}

// Close closes the connection.
func (t *Transport) Close() error {
	t.mu.Lock()
	defer t.mu.Unlock()

	if !t.connected || t.conn == nil {
		return nil
	}

	err := t.conn.Close()
	t.conn = nil
	t.reader = nil
	t.connected = false
	return err
}

// IsConnected returns whether the transport has an active connection.
func (t *Transport) IsConnected() bool {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.connected
}

// SendJSON marshals v as JSON, appends a newline, and writes it to the
// connection.
func (t *Transport) SendJSON(v interface{}) error {
	t.mu.Lock()
	defer t.mu.Unlock()

	if !t.connected || t.conn == nil {
		return ErrNotConnected
	}

	data, err := json.Marshal(v)
	if err != nil {
		return fmt.Errorf("ainos: marshal error: %w", err)
	}

	if t.writeTimeout > 0 {
		t.conn.SetWriteDeadline(time.Now().Add(t.writeTimeout))
	}

	// Write JSON + newline
	data = append(data, '\n')
	if _, err := t.conn.Write(data); err != nil {
		t.connected = false
		return &ConnectionError{
			Op:   "write",
			Addr: t.conn.RemoteAddr().String(),
			Err:  err,
		}
	}

	return nil
}

// SendRequest builds a JSON request with the given type and fields and sends
// it over the connection.
func (t *Transport) SendRequest(msgType string, fields map[string]interface{}) error {
	msg := make(map[string]interface{}, len(fields)+1)
	msg["type"] = msgType
	for k, v := range fields {
		if v != nil {
			msg[k] = v
		}
	}
	return t.SendJSON(msg)
}

// ReadLine reads a single newline-delimited line from the connection.
func (t *Transport) ReadLine() ([]byte, error) {
	t.mu.Lock()
	conn := t.conn
	reader := t.reader
	connected := t.connected
	readTimeout := t.readTimeout
	t.mu.Unlock()

	if !connected || conn == nil {
		return nil, ErrNotConnected
	}

	if readTimeout > 0 {
		conn.SetReadDeadline(time.Now().Add(readTimeout))
	}

	line, err := reader.ReadBytes('\n')
	if err != nil {
		// Mark as disconnected on read error
		t.mu.Lock()
		t.connected = false
		t.mu.Unlock()

		if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
			return nil, &TimeoutError{
				Operation: "read",
				Timeout:   readTimeout,
			}
		}
		return nil, &ConnectionError{
			Op:   "read",
			Addr: conn.RemoteAddr().String(),
			Err:  err,
		}
	}

	// Strip trailing newline
	if len(line) > 0 {
		line = line[:len(line)-1]
	}

	return line, nil
}

// RoundTrip sends a request and reads a single response.
func (t *Transport) RoundTrip(msgType string, fields map[string]interface{}) ([]byte, error) {
	if err := t.SendRequest(msgType, fields); err != nil {
		return nil, err
	}
	return t.ReadLine()
}

// RoundTripTyped sends a request, reads the response, and checks that the
// response type matches the expected type.
func (t *Transport) RoundTripTyped(msgType, expectedType string, fields map[string]interface{}) ([]byte, error) {
	data, err := t.RoundTrip(msgType, fields)
	if err != nil {
		return nil, err
	}

	respType, err := parseResponseType(data)
	if err != nil {
		return nil, &ProtocolError{Message: fmt.Sprintf("cannot parse response type: %v", err)}
	}

	if respType == msgTypeError {
		daemonErr := extractDaemonError(data)
		if daemonErr != nil {
			return nil, daemonErr
		}
		return nil, &Error{Code: -1, Message: "unknown daemon error"}
	}

	if respType != expectedType {
		return nil, &ProtocolError{
			Message: fmt.Sprintf("expected %q response, got %q", expectedType, respType),
		}
	}

	return data, nil
}

// LocalAddr returns the local address of the connection, if connected.
func (t *Transport) LocalAddr() net.Addr {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.conn != nil {
		return t.conn.LocalAddr()
	}
	return nil
}

// RemoteAddr returns the remote address of the connection, if connected.
func (t *Transport) RemoteAddr() net.Addr {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.conn != nil {
		return t.conn.RemoteAddr()
	}
	return nil
}

// ---------------------------------------------------------------------------
// Connection Pool
// ---------------------------------------------------------------------------

// ConnPool manages a pool of transports for concurrent batch operations.
type ConnPool struct {
	mu       sync.Mutex
	host     string
	port     int
	config   PoolConfig
	transports chan *Transport
	active     int
	closed     bool
}

// NewConnPool creates a new connection pool.
func NewConnPool(host string, port int, config PoolConfig) *ConnPool {
	return &ConnPool{
		host:       host,
		port:       port,
		config:     config,
		transports: make(chan *Transport, config.MaxSize),
	}
}

// Acquire retrieves a transport from the pool, creating a new one if needed.
func (p *ConnPool) Acquire() (*Transport, error) {
	p.mu.Lock()
	if p.closed {
		p.mu.Unlock()
		return nil, fmt.Errorf("ainos: connection pool is closed")
	}
	p.mu.Unlock()

	// Try to get an existing transport
	select {
	case t := <-p.transports:
		// Check if the transport is still alive
		if t.IsConnected() {
			return t, nil
		}
		// Discard dead transport
		p.mu.Lock()
		p.active--
		p.mu.Unlock()
	default:
	}

	// Create a new transport
	p.mu.Lock()
	if p.active >= p.config.MaxSize {
		p.mu.Unlock()
		return nil, fmt.Errorf("ainos: connection pool exhausted (max %d)", p.config.MaxSize)
	}
	p.active++
	p.mu.Unlock()

	t := NewTransport(p.host, p.port, 5*time.Second)
	if err := t.Dial(); err != nil {
		p.mu.Lock()
		p.active--
		p.mu.Unlock()
		return nil, err
	}
	return t, nil
}

// Release returns a transport to the pool.
func (p *ConnPool) Release(t *Transport) {
	if t == nil {
		return
	}

	p.mu.Lock()
	defer p.mu.Unlock()

	if p.closed || !t.IsConnected() {
		t.Close()
		p.active--
		return
	}

	select {
	case p.transports <- t:
		// Returned to pool
	default:
		// Pool full, close the transport
		t.Close()
		p.active--
	}
}

// Close closes all transports in the pool.
func (p *ConnPool) Close() {
	p.mu.Lock()
	p.closed = true
	p.mu.Unlock()

	close(p.transports)
	for t := range p.transports {
		t.Close()
		p.active--
	}
}

// Active returns the number of active transports.
func (p *ConnPool) Active() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.active
}