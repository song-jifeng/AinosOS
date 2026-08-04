# frozen_string_literal: true

module Ainos
  # Base error class for all Ainos SDK errors.
  #
  # All errors raised by the Ainos SDK inherit from this class, making it
  # possible to rescue any Ainos-specific error with a single rescue clause.
  #
  # @example Catching all Ainos errors
  #   begin
  #     client.infer(...)
  #   rescue Ainos::Error => e
  #     puts "Ainos error: #{e.message}"
  #   end
  class Error < StandardError
    # @return [String] the error code for programmatic handling
    attr_reader :error_code

    # @return [Hash] additional metadata about the error
    attr_reader :metadata

    # @param message [String] the human-readable error message
    # @param error_code [String] a machine-readable error code
    # @param metadata [Hash] additional context about the error
    # @param cause [Exception] the original exception that caused this error
    def initialize(message = nil, error_code: nil, metadata: {}, cause: nil)
      super(message)
      @error_code = error_code || self.class.name.split('::').last
        .gsub(/([A-Z])/, '_\1').downcase.sub(/^_/, '')
      @metadata = metadata.dup.freeze

      set_backtrace(cause.backtrace) if cause&.backtrace
    end

    # @return [String] a detailed error report
    def detailed_message
      parts = ["[#{@error_code}] #{message}"]
      parts << "Metadata: #{@metadata.inspect}" unless @metadata.empty?
      parts.join("\n")
    end
  end

  # Raised when a connection to the Ainos daemon cannot be established.
  #
  # @example
  #   rescue Ainos::ConnectionError => e
  #     puts "Cannot connect to daemon: #{e.message}"
  class ConnectionError < Error
    # @return [String] the host that was attempted
    attr_reader :host

    # @return [Integer] the port that was attempted
    attr_reader :port

    # @param message [String] error description
    # @param host [String] the host that was attempted
    # @param port [Integer] the port that was attempted
    # @param cause [Exception] the original exception
    def initialize(message = 'Failed to connect to Ainos daemon',
                   host: '127.0.0.1', port: 9500, cause: nil)
      @host = host
      @port = port
      super(
        "#{message} (#{host}:#{port})",
        error_code: 'connection_error',
        metadata: { host: host, port: port },
        cause: cause
      )
    end
  end

  # Raised when the connection to the daemon is lost unexpectedly.
  class ConnectionLostError < ConnectionError
    def initialize(message = 'Connection to Ainos daemon was lost',
                   host: '127.0.0.1', port: 9500, cause: nil)
      @host = host
      @port = port
      super(message, host: host, port: port, cause: cause)
      @error_code = 'connection_lost'
    end
  end

  # Raised when the maximum number of reconnection attempts is exceeded.
  class MaxReconnectError < ConnectionError
    # @return [Integer] the number of attempts made
    attr_reader :attempts

    # @param attempts [Integer] the number of attempts made
    # @param host [String] the host that was attempted
    # @param port [Integer] the port that was attempted
    # @param cause [Exception] the original exception
    def initialize(attempts: 3, host: '127.0.0.1', port: 9500, cause: nil)
      @attempts = attempts
      super(
        "Max reconnection attempts (#{attempts}) exceeded for #{host}:#{port}",
        host: host, port: port, cause: cause
      )
      @error_code = 'max_reconnect_exceeded'
    end
  end

  # Raised when authentication fails.
  class AuthError < Error
    # @return [String] the reason for authentication failure
    attr_reader :reason

    # @param message [String] error description
    # @param reason [String] the specific reason for failure
    # @param cause [Exception] the original exception
    def initialize(message = 'Authentication failed',
                   reason: 'invalid_token', cause: nil)
      @reason = reason
      super(
        "#{message} (#{reason})",
        error_code: "auth_#{reason}",
        metadata: { reason: reason },
        cause: cause
      )
    end
  end

  # Raised when the token has expired and needs to be refreshed.
  class TokenExpiredError < AuthError
    def initialize(message = 'Authentication token has expired')
      super(message, reason: 'token_expired')
      @error_code = 'auth_token_expired'
    end
  end

  # Raised when the token format is invalid.
  class InvalidTokenError < AuthError
    def initialize(message = 'Authentication token format is invalid')
      super(message, reason: 'invalid_token_format')
      @error_code = 'auth_invalid_token'
    end
  end

  # Raised when a protocol-level error occurs.
  class ProtocolError < Error
    # @return [String] the type of protocol error
    attr_reader :protocol_type

    # @param message [String] error description
    # @param protocol_type [String] the type of protocol error
    # @param cause [Exception] the original exception
    def initialize(message = 'Protocol error', protocol_type: 'unknown',
                   cause: nil)
      @protocol_type = protocol_type
      super(
        "#{message} (type: #{protocol_type})",
        error_code: "protocol_#{protocol_type}",
        metadata: { protocol_type: protocol_type },
        cause: cause
      )
    end
  end

  # Raised when a malformed message is received.
  class MalformedMessageError < ProtocolError
    # @return [String] the raw message data
    attr_reader :raw_data

    # @param raw_data [String] the raw message data
    # @param cause [Exception] the original exception
    def initialize(raw_data: nil, cause: nil)
      @raw_data = raw_data
      super(
        "Received malformed message: #{raw_data&.slice(0, 200)}",
        protocol_type: 'malformed_message',
        cause: cause
      )
      @error_code = 'protocol_malformed_message'
    end
  end

  # Raised when an unexpected message type is received.
  class UnexpectedMessageError < ProtocolError
    # @return [String] the unexpected message type
    attr_reader :received_type

    # @param received_type [String] the unexpected message type
    # @param expected_types [Array<String>] the expected message types
    def initialize(received_type:, expected_types: [])
      @received_type = received_type
      super(
        "Unexpected message type '#{received_type}'" \
        "#{expected_types.any? ? " (expected: #{expected_types.join(', ')})" : ''}",
        protocol_type: 'unexpected_message'
      )
      @error_code = 'protocol_unexpected_message'
    end
  end

  # Raised when a message is too large to process.
  class MessageTooLargeError < ProtocolError
    # @return [Integer] the size of the message in bytes
    attr_reader :message_size

    # @return [Integer] the maximum allowed size in bytes
    attr_reader :max_size

    # @param message_size [Integer] the size of the message
    # @param max_size [Integer] the maximum allowed size
    def initialize(message_size:, max_size: 10_485_760)
      @message_size = message_size
      @max_size = max_size
      super(
        "Message size #{message_size} bytes exceeds maximum of #{max_size} bytes",
        protocol_type: 'message_too_large'
      )
      @error_code = 'protocol_message_too_large'
    end
  end

  # Raised when an operation times out.
  class TimeoutError < Error
    # @return [Float] the timeout duration in seconds
    attr_reader :timeout

    # @return [String] the operation that timed out
    attr_reader :operation

    # @param timeout [Float] the timeout duration
    # @param operation [String] the operation that timed out
    def initialize(timeout: 30, operation: 'unknown')
      @timeout = timeout
      @operation = operation
      super(
        "Operation '#{operation}' timed out after #{timeout}s",
        error_code: "timeout_#{operation}",
        metadata: { timeout: timeout, operation: operation }
      )
    end
  end

  # Raised when a connection timeout occurs.
  class ConnectionTimeoutError < TimeoutError
    # @return [String] the host
    # @return [Integer] the port
    attr_reader :host, :port

    # @param timeout [Float] the timeout duration
    # @param host [String] the host
    # @param port [Integer] the port
    def initialize(timeout: 5, host: '127.0.0.1', port: 9500)
      @host = host
      @port = port
      super(
        timeout: timeout,
        operation: "connect to #{host}:#{port}"
      )
      @error_code = 'timeout_connection'
    end
  end

  # Raised when an inference request times out.
  class InferenceTimeoutError < TimeoutError
    # @return [String] the model name
    attr_reader :model

    # @param timeout [Float] the timeout duration
    # @param model [String] the model name
    def initialize(timeout: 120, model: 'unknown')
      @model = model
      super(
        timeout: timeout,
        operation: "inference on model '#{model}'"
      )
      @error_code = 'timeout_inference'
    end
  end

  # Raised when a model-related error occurs.
  class ModelError < Error
    # @return [String] the model name
    attr_reader :model_name

    # @param message [String] error description
    # @param model_name [String] the model name
    # @param cause [Exception] the original exception
    def initialize(message = 'Model error', model_name: 'unknown', cause: nil)
      @model_name = model_name
      super(
        "#{message} (model: #{model_name})",
        error_code: 'model_error',
        metadata: { model_name: model_name },
        cause: cause
      )
    end
  end

  # Raised when a model is not found on the server.
  class ModelNotFoundError < ModelError
    # @param model_name [String] the model name that was not found
    def initialize(model_name:)
      super("Model '#{model_name}' not found", model_name: model_name)
      @error_code = 'model_not_found'
    end
  end

  # Raised when a model fails to load.
  class ModelLoadError < ModelError
    # @param model_name [String] the model name
    # @param reason [String] the reason for the failure
    def initialize(model_name:, reason: 'unknown')
      @reason = reason
      super(
        "Failed to load model '#{model_name}': #{reason}",
        model_name: model_name
      )
      @error_code = 'model_load_failed'
    end
  end

  # Raised when a model fails to unload.
  class ModelUnloadError < ModelError
    # @param model_name [String] the model name
    # @param reason [String] the reason for the failure
    def initialize(model_name:, reason: 'unknown')
      @reason = reason
      super(
        "Failed to unload model '#{model_name}': #{reason}",
        model_name: model_name
      )
      @error_code = 'model_unload_failed'
    end
  end

  # Raised when a model is not ready for inference.
  class ModelNotReadyError < ModelError
    # @param model_name [String] the model name
    # @param status [String] the current status of the model
    def initialize(model_name:, status: 'unknown')
      @status = status
      super(
        "Model '#{model_name}' is not ready (status: #{status})",
        model_name: model_name
      )
      @error_code = 'model_not_ready'
    end
  end

  # Raised when an inference request fails.
  class InferenceError < Error
    # @return [String] the model name
    attr_reader :model_name

    # @return [String] the request ID
    attr_reader :request_id

    # @param message [String] error description
    # @param model_name [String] the model name
    # @param request_id [String] the request ID
    # @param cause [Exception] the original exception
    def initialize(message = 'Inference failed',
                   model_name: 'unknown', request_id: nil, cause: nil)
      @model_name = model_name
      @request_id = request_id
      super(
        "#{message}#{request_id ? " (request: #{request_id})" : ''}",
        error_code: 'inference_error',
        metadata: { model_name: model_name, request_id: request_id },
        cause: cause
      )
    end
  end

  # Raised when inference is rejected by the server.
  class InferenceRejectedError < InferenceError
    # @param reason [String] the rejection reason
    # @param model_name [String] the model name
    # @param request_id [String] the request ID
    def initialize(reason: 'unknown', model_name: 'unknown', request_id: nil)
      @reason = reason
      super(
        "Inference rejected: #{reason}",
        model_name: model_name, request_id: request_id
      )
      @error_code = 'inference_rejected'
    end
  end

  # Raised when the server returns a rate limit error.
  class RateLimitError < InferenceError
    # @return [Integer] the number of seconds to wait before retrying
    attr_reader :retry_after

    # @param retry_after [Integer] seconds to wait
    # @param model_name [String] the model name
    def initialize(retry_after: 60, model_name: 'unknown')
      @retry_after = retry_after
      super(
        "Rate limit exceeded. Retry after #{retry_after}s",
        model_name: model_name
      )
      @error_code = 'rate_limit_exceeded'
    end
  end

  # Raised when a context-related error occurs.
  class ContextError < Error
    # @return [String] the context ID
    attr_reader :context_id

    # @param message [String] error description
    # @param context_id [String] the context ID
    # @param cause [Exception] the original exception
    def initialize(message = 'Context error', context_id: nil, cause: nil)
      @context_id = context_id
      super(
        "#{message}#{context_id ? " (context: #{context_id})" : ''}",
        error_code: 'context_error',
        metadata: { context_id: context_id },
        cause: cause
      )
    end
  end

  # Raised when a context is not found.
  class ContextNotFoundError < ContextError
    # @param context_id [String] the context ID
    def initialize(context_id:)
      super("Context '#{context_id}' not found", context_id: context_id)
      @error_code = 'context_not_found'
    end
  end

  # Raised when the context store is full.
  class ContextStoreFullError < ContextError
    # @param max_contexts [Integer] the maximum number of contexts
    def initialize(max_contexts: 100)
      super(
        "Context store is full (max: #{max_contexts})",
        context_id: nil
      )
      @error_code = 'context_store_full'
    end
  end

  # Raised when a transport-level error occurs.
  class TransportError < Error
    # @return [String] the transport operation
    attr_reader :operation

    # @param message [String] error description
    # @param operation [String] the transport operation
    # @param cause [Exception] the original exception
    def initialize(message = 'Transport error', operation: 'unknown',
                   cause: nil)
      @operation = operation
      super(
        "#{message} (operation: #{operation})",
        error_code: "transport_#{operation}",
        metadata: { operation: operation },
        cause: cause
      )
    end
  end

  # Raised when a write operation fails.
  class WriteError < TransportError
    # @param message [String] error description
    # @param cause [Exception] the original exception
    def initialize(message = 'Failed to write to transport', cause: nil)
      super(message, operation: 'write', cause: cause)
      @error_code = 'transport_write_failed'
    end
  end

  # Raised when a read operation fails.
  class ReadError < TransportError
    # @param message [String] error description
    # @param cause [Exception] the original exception
    def initialize(message = 'Failed to read from transport', cause: nil)
      super(message, operation: 'read', cause: cause)
      @error_code = 'transport_read_failed'
    end
  end

  # Raised when the socket is not connected.
  class NotConnectedError < TransportError
    def initialize(message = 'Not connected to Ainos daemon')
      super(message, operation: 'not_connected')
      @error_code = 'transport_not_connected'
    end
  end

  # Raised when an invalid argument is provided.
  class ArgumentError < Error
    # @return [String] the argument name
    attr_reader :argument_name

    # @param argument_name [String] the argument name
    # @param message [String] error description
    # @param cause [Exception] the original exception
    def initialize(argument_name:, message: nil, cause: nil)
      @argument_name = argument_name
      super(
        message || "Invalid argument '#{argument_name}'",
        error_code: "invalid_argument_#{argument_name}",
        metadata: { argument_name: argument_name },
        cause: cause
      )
    end
  end

  # Raised when a feature is not supported.
  class UnsupportedError < Error
    # @return [String] the feature that is not supported
    attr_reader :feature

    # @param feature [String] the feature name
    def initialize(feature:)
      @feature = feature
      super("Feature '#{feature}' is not supported",
            error_code: "unsupported_#{feature}",
            metadata: { feature: feature })
    end
  end

  # Raised when the server encounters an internal error.
  class ServerError < Error
    # @return [Integer] the HTTP-like status code
    attr_reader :status_code

    # @param message [String] error description
    # @param status_code [Integer] the status code
    def initialize(message = 'Internal server error', status_code: 500)
      @status_code = status_code
      super(
        "#{message} (status: #{status_code})",
        error_code: 'server_error',
        metadata: { status_code: status_code }
      )
    end
  end
end