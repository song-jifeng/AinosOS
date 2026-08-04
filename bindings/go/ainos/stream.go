package ainos

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
)

// ---------------------------------------------------------------------------
// StreamReader
// ---------------------------------------------------------------------------

// StreamReader reads streaming inference chunks from the daemon.
//
// The daemon sends one JSON line per chunk, each containing an InferenceChunk.
// StreamReader reads these lines, parses them, and delivers them to the
// caller via a channel.
type StreamReader struct {
	transport *Transport
	chunks    chan *InferenceChunk
	errCh     chan error
	done      chan struct{}
	closed    atomic.Bool
	mu        sync.Mutex
	chunkBuf  []*InferenceChunk // buffer for backpressure
	index     int               // chunk sequence counter
}

// NewStreamReader creates a new StreamReader for the given transport.
func NewStreamReader(transport *Transport) *StreamReader {
	return &StreamReader{
		transport: transport,
		chunks:    make(chan *InferenceChunk, 64),
		errCh:     make(chan error, 1),
		done:      make(chan struct{}),
	}
}

// Chunks returns a read-only channel of inference chunks.
func (sr *StreamReader) Chunks() <-chan *InferenceChunk {
	return sr.chunks
}

// Err returns a read-only channel that receives any error that occurs during
// streaming.
func (sr *StreamReader) Err() <-chan error {
	return sr.errCh
}

// Done returns a channel that is closed when the stream completes.
func (sr *StreamReader) Done() <-chan struct{} {
	return sr.done
}

// readLoop reads chunks from the transport and sends them to the chunks
// channel.  It runs in a goroutine and stops when the stream ends or an
// error occurs.
func (sr *StreamReader) readLoop(ctx context.Context) {
	defer func() {
		sr.closed.Store(true)
		close(sr.done)
		close(sr.chunks)
		close(sr.errCh)
	}()

	for {
		// Check context cancellation
		select {
		case <-ctx.Done():
			sr.errCh <- ctx.Err()
			return
		default:
		}

		// Read a line from the transport
		line, err := sr.transport.ReadLine()
		if err != nil {
			sr.errCh <- err
			return
		}

		// Parse the response type
		respType, parseErr := parseResponseType(line)
		if parseErr != nil {
			sr.errCh <- &ProtocolError{Message: fmt.Sprintf("invalid response: %v", parseErr)}
			return
		}

		switch respType {
		case msgTypeInferenceChunk:
			chunk, err := parseInferenceChunk(line)
			if err != nil {
				sr.errCh <- err
				return
			}
			sr.index++
			chunk.Index = sr.index

			// Send chunk to channel (respect context cancellation)
			select {
			case sr.chunks <- chunk:
			case <-ctx.Done():
				sr.errCh <- ctx.Err()
				return
			}

			if chunk.Done {
				return // stream complete
			}

		case msgTypeInferenceResponse:
			// Non-streaming fallback: the server returned a single response
			// instead of chunks.  Deliver it as a single chunk.
			resp, err := parseInferenceResponse(line)
			if err != nil {
				sr.errCh <- err
				return
			}
			sr.index++
			chunk := &InferenceChunk{
				Text:         resp.Text,
				Index:        sr.index,
				Done:         true,
				FinishReason: "stop",
			}
			select {
			case sr.chunks <- chunk:
			case <-ctx.Done():
				sr.errCh <- ctx.Err()
				return
			}
			return

		case msgTypeError:
			daemonErr := extractDaemonError(line)
			if daemonErr != nil {
				sr.errCh <- daemonErr
			} else {
				sr.errCh <- &Error{Code: -1, Message: "unknown daemon error during streaming"}
			}
			return

		default:
			sr.errCh <- &ProtocolError{
				Message: fmt.Sprintf("unexpected response type during streaming: %q", respType),
			}
			return
		}
	}
}

// Close closes the stream reader, stopping any pending reads.
func (sr *StreamReader) Close() {
	if sr.closed.Load() {
		return
	}
	sr.mu.Lock()
	defer sr.mu.Unlock()
	if sr.closed.Load() {
		return
	}
	// Signal done so the read loop exits
	sr.closed.Store(true)
	// Drain the transport connection to unblock any pending read
	if sr.transport != nil && sr.transport.IsConnected() {
		// We can't easily interrupt a TCP read, but the context cancellation
		// in readLoop will cause it to exit on the next iteration.
	}
}

// ---------------------------------------------------------------------------
// InferStream implementation
// ---------------------------------------------------------------------------

// startInferStream sends an InferenceStream request and starts reading chunks.
//
// It returns a StreamReader that the caller can use to receive chunks.
// The caller MUST consume from the Chunks() channel until it is closed,
// or the stream will leak a goroutine.
func startInferStream(ctx context.Context, transport *Transport, req *InferenceRequest) (*StreamReader, error) {
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

	// Send the InferenceStream request
	if err := transport.SendRequest(msgTypeInferenceStream, fields); err != nil {
		return nil, err
	}

	// Create stream reader and start reading
	reader := NewStreamReader(transport)
	go reader.readLoop(ctx)

	return reader, nil
}

// CollectStream collects all chunks from a stream into a single response.
func CollectStream(ctx context.Context, chunks <-chan *InferenceChunk) (*InferenceResponse, error) {
	var text string
	chunkCount := 0

	for chunk := range chunks {
		chunkCount++
		text += chunk.Text
		if chunk.Done {
			break
		}
	}

	return &InferenceResponse{
		Text:            text,
		TokensGenerated: chunkCount,
		Source:          "local",
	}, nil
}

// ---------------------------------------------------------------------------
// Channel helpers
// ---------------------------------------------------------------------------

// MergeChunks merges multiple chunk channels into a single channel.
// All chunks are forwarded to the output channel, which is closed when
// all input channels are exhausted.
func MergeChunks(ctx context.Context, channels ...<-chan *InferenceChunk) <-chan *InferenceChunk {
	out := make(chan *InferenceChunk, 64)
	var wg sync.WaitGroup

	multiplex := func(ch <-chan *InferenceChunk) {
		defer wg.Done()
		for chunk := range ch {
			select {
			case out <- chunk:
			case <-ctx.Done():
				return
			}
		}
	}

	wg.Add(len(channels))
	for _, ch := range channels {
		go multiplex(ch)
	}

	go func() {
		wg.Wait()
		close(out)
	}()

	return out
}

// FilterChunks filters chunks from a channel based on a predicate.
func FilterChunks(ctx context.Context, in <-chan *InferenceChunk, fn func(*InferenceChunk) bool) <-chan *InferenceChunk {
	out := make(chan *InferenceChunk, 64)
	go func() {
		defer close(out)
		for chunk := range in {
			if fn(chunk) {
				select {
				case out <- chunk:
				case <-ctx.Done():
					return
				}
			}
		}
	}()
	return out
}