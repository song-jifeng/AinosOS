# frozen_string_literal: true

require 'securerandom'
require 'time'

module Ainos
  # Main client for interacting with the Ainos daemon.
  #
  # Provides a high-level interface for all daemon operations including
  # inference, model management, health checks, and context management.
  #
  # @example Basic usage
  #   client = Ainos::Client.new(token: 'my-token')
  #   client.connect
  #
  #   response = client.infer(model: 'llama3', prompt: 'Hello!')
  #   puts response.text
  #
  #   client.disconnect
  #
  # @example With configuration block
  #   client = Ainos::Client.new do |config|
  #     config.host = 'localhost'
  #     config.port = 9500
  #     config.token = ENV['AINOS_TOKEN']
  #     config.connection_timeout = 10.0
  #   end
  class Client
    # @return [Configuration] the client configuration
    attr_reader :config

    # @return [Transport] the transport layer
    attr_reader :transport

    # @return [Auth, nil] the auth handler
    attr_reader :auth

    # @return [Boolean] whether the client is connected
    attr_reader :connected

    # Create a new Ainos client.
    #
    # @overload initialize(token:, host: DEFAULT_HOST, port: DEFAULT_PORT, ...)
    #   @param token [String, nil] the Bearer token for authentication
    #   @param host [String] the daemon hostname
    #   @param port [Integer] the daemon port
    #   @param connection_timeout [Float] connection timeout in seconds
    #   @param read_timeout [Float] read timeout in seconds
    #   @param write_timeout [Float] write timeout in seconds
    #   @param max_reconnect_attempts [Integer] max reconnection attempts
    #   @param reconnect_delay [Float] delay between reconnection attempts
    #   @param auto_reconnect [Boolean] auto-reconnect on connection loss
    #   @param logger [Logger, nil] logger instance
    #   @param ssl [Boolean] enable SSL/TLS
    #
    # @overload initialize(config = {})
    #   @param config [Hash, Configuration] configuration hash or object
    #
    # @overload initialize
    #   @yield [config] configuration block
    #   @yieldparam config [Configuration] the configuration object
    #
    # @example With token
    #   client = Ainos::Client.new(token: 'my-token')
    #
    # @example With configuration block
    #   client = Ainos::Client.new do |c|
    #     c.host = '10.0.0.1'
    #     c.port = 9500
    #     c.token = ENV['AINOS_TOKEN']
    #   end
    def initialize(**kwargs, &block)
      # Build configuration from arguments
      if kwargs.key?(:token) || kwargs.key?(:host) || kwargs.key?(:port)
        @config = Configuration.new(**kwargs)
      elsif kwargs.size == 1
        first_val = kwargs.values.first
        if first_val.is_a?(Configuration)
          @config = first_val
        elsif first_val.is_a?(Hash)
          @config = Configuration.from_hash(first_val)
        else
          @config = Configuration.new(**kwargs)
        end
      elsif kwargs.empty?
        @config = Configuration.new
      else
        @config = Configuration.new(**kwargs)
      end

      # Allow block configuration
      block.call(@config) if block

      # Setup auth
      @auth = setup_auth

      # Setup transport
      @transport = Transport.new(
        @config.host,
        @config.port,
        @config
      )

      @connected = false
      @request_count = 0
      @mutex = Mutex.new
      @active_streams = []
    end

    # Connect to the Ainos daemon.
    #
    # @param timeout [Float, nil] connection timeout
    #
    # @return [Boolean] true if connected
    #
    # @raise [Ainos::ConnectionError] if connection fails
    #
    # @example
    #   client.connect
    #   client.connect(timeout: 10.0)
    def connect(timeout: nil)
      @transport.connect(timeout: timeout)
      @connected = true
      true
    end

    # Disconnect from the Ainos daemon.
    #
    # @return [Boolean] true if disconnected
    #
    # @example
    #   client.disconnect
    def disconnect
      cancel_active_streams
      @transport.disconnect
      @connected = false
      true
    end

    # Check if the client is connected to the daemon.
    #
    # @return [Boolean] true if connected
    def connected?
      @connected && @transport.connected?
    end

    # Perform a health check on the daemon.
    #
    # @return [HealthStatus] the health status
    #
    # @raise [Ainos::ConnectionError] if not connected
    #
    # @example
    #   health = client.health
    #   puts health.healthy? ? 'OK' : 'FAIL'
    def health
      response = send_request('health', {})

      if response.success?
        payload = response.payload
        HealthStatus.new(
          status: payload.fetch('status', 'unknown'),
          healthy: payload.fetch('healthy', true),
          version: payload.fetch('version', nil),
          uptime: payload.fetch('uptime', nil),
          active_connections: payload.fetch('active_connections', nil),
          loaded_models: payload.fetch('loaded_models', nil),
          details: payload.fetch('details', {})
        )
      else
        HealthStatus.new(
          status: 'error',
          healthy: false,
          details: { error: response.error }
        )
      end
    end

    # Get the detailed server status.
    #
    # @return [ServerStatus] the server status
    #
    # @raise [Ainos::ConnectionError] if not connected
    #
    # @example
    #   status = client.status
    #   puts status
    def status
      response = send_request('status', {})

      if response.success?
        payload = response.payload
        ServerStatus.new(
          version: payload.fetch('version', 'unknown'),
          started_at: payload.fetch('started_at', nil),
          active_connections: payload.fetch('active_connections', 0),
          total_requests: payload.fetch('total_requests', 0),
          avg_latency_ms: payload.fetch('avg_latency_ms', 0.0),
          loaded_models: payload.fetch('loaded_models', 0),
          total_models: payload.fetch('total_models', 0),
          memory: payload.fetch('memory', {}),
          cpu: payload.fetch('cpu', {}),
          gpu: payload.fetch('gpu', {}),
          details: payload.fetch('details', {})
        )
      else
        raise ServerError.new(
          response.error || 'Failed to get server status',
          status_code: 500
        )
      end
    end

    # Perform inference with a prompt.
    #
    # @overload infer(model:, prompt:, ...)
    #   @param model [String] the model name
    #   @param prompt [String] the input prompt
    #   @param system_prompt [String, nil] optional system prompt
    #   @param temperature [Float] sampling temperature
    #   @param max_tokens [Integer] maximum tokens to generate
    #   @param top_p [Float] nucleus sampling parameter
    #   @param top_k [Integer, nil] top-k sampling
    #   @param stop_sequences [Array<String>] stop sequences
    #   @param context_id [String, nil] conversation context
    #
    # @overload infer(request)
    #   @param request [InferenceRequest] an inference request object
    #
    # @return [InferenceResponse] the inference response
    #
    # @raise [Ainos::InferenceError] if inference fails
    # @raise [Ainos::ModelNotFoundError] if the model is not found
    #
    # @example
    #   response = client.infer(model: 'llama3', prompt: 'Hello!')
    #   puts response.text
    #
    # @example With request object
    #   request = Ainos::InferenceRequest.new(model: 'llama3', prompt: 'Hi')
    #   response = client.infer(request)
    def infer(*args)
      request = build_inference_request(*args)

      response = send_request('infer', request.to_h)

      if response.success?
        payload = response.payload
        InferenceResponse.new(
          text: payload.fetch('text', ''),
          tokens: payload.fetch('tokens', payload.fetch('completion_tokens', 0)),
          finish_reason: payload.fetch('finish_reason', 'stop'),
          model: payload.fetch('model', request.model),
          request_id: response.id,
          usage: payload.fetch('usage', {}),
          timing: payload.fetch('timing', {}),
          metadata: payload.fetch('metadata', {})
        )
      else
        handle_inference_error(response, request.model)
      end
    end

    # Perform streaming inference with a prompt.
    #
    # @overload infer_stream(model:, prompt:, ...)
    # @overload infer_stream(request)
    #
    # @yield [StreamChunk] each chunk as it arrives
    #
    # @return [Enumerator<StreamChunk>, StreamSession] an enumerator
    #   or stream session
    #
    # @raise [Ainos::InferenceError] if inference fails
    #
    # @example Block-based
    #   client.infer_stream(model: 'llama3', prompt: 'Hello!') do |chunk|
    #     print chunk.text
    #   end
    #
    # @example Enumerator-based
    #   chunks = client.infer_stream(model: 'llama3', prompt: 'Hello!')
    #   chunks.each { |c| print c.text }
    def infer_stream(*args, &block)
      request = build_inference_request(*args)

      # Ensure streaming is enabled by creating a new request with stream: true
      unless request.stream
        request = InferenceRequest.new(**request.to_h.merge(stream: true))
      end

      session = StreamSession.new(self, request)

      if block
        session.each_chunk(&block)
        return session
      end

      # Return lazy enumerator
      enum = Enumerator.new do |yielder|
        session.each_chunk do |chunk|
          yielder << chunk
        end
      end

      enum.lazy
    end

    # List all available models.
    #
    # @return [Array<ModelInfo>] list of available models
    #
    # @raise [Ainos::ServerError] if the request fails
    #
    # @example
    #   models = client.model_list
    #   models.each { |m| puts "#{m.name} - #{m.status}" }
    def model_list
      response = send_request('model_list', {})

      if response.success?
        payload = response.payload
        models = payload.fetch('models', payload.fetch('model_list', []))
        models.map do |m|
          ModelInfo.new(
            name: m.fetch('name', m.fetch('model', 'unknown')),
            version: m.fetch('version', nil),
            path: m.fetch('path', nil),
            status: m.fetch('status', 'unknown'),
            loaded_at: m.fetch('loaded_at', nil),
            size_bytes: m.fetch('size_bytes', m.fetch('size', 0)),
            capabilities: m.fetch('capabilities', []),
            config: m.fetch('config', {}),
            description: m.fetch('description', nil),
            architecture: m.fetch('architecture', nil),
            quantization: m.fetch('quantization', nil),
            context_length: m.fetch('context_length', nil)
          )
        end
      else
        raise ServerError.new(
          response.error || 'Failed to list models',
          status_code: 500
        )
      end
    end

    # Load a model onto the daemon.
    #
    # @overload model_load(model_name, **params)
    #   @param model_name [String] the model name
    #   @param gpu_layers [Integer, nil] number of GPU layers
    #   @param context_size [Integer, nil] context window size
    #   @param batch_size [Integer, nil] batch size
    #   @param threads [Integer, nil] number of threads
    #   @param mlock [Boolean, nil] memory lock
    #   @param mmap [Boolean, nil] memory mapping
    #
    # @overload model_load(request)
    #   @param request [ModelLoadRequest] a load request object
    #
    # @return [ModelInfo] information about the loaded model
    #
    # @raise [Ainos::ModelLoadError] if loading fails
    # @raise [Ainos::ModelNotFoundError] if the model is not found
    #
    # @example
    #   model = client.model_load('llama3', gpu_layers: 32)
    def model_load(*args)
      params = build_load_request(*args)

      response = send_request('model_load', params)

      if response.success?
        payload = response.payload
        ModelInfo.new(
          name: payload.fetch('name', payload.fetch('model', params[:model])),
          version: payload.fetch('version', nil),
          status: payload.fetch('status', 'loaded'),
          loaded_at: payload.fetch('loaded_at', Time.now.iso8601),
          size_bytes: payload.fetch('size_bytes', 0),
          capabilities: payload.fetch('capabilities', []),
          config: payload.fetch('config', {}),
          architecture: payload.fetch('architecture', nil),
          quantization: payload.fetch('quantization', nil),
          context_length: payload.fetch('context_length', nil)
        )
      else
        handle_model_error(response, params[:model])
      end
    end

    # Unload a model from the daemon.
    #
    # @param model_name [String] the model name to unload
    #
    # @return [Boolean] true if the model was unloaded
    #
    # @raise [Ainos::ModelUnloadError] if unloading fails
    #
    # @example
    #   client.model_unload('llama3')
    def model_unload(model_name)
      response = send_request('model_unload', { model: model_name.to_s })

      if response.success?
        true
      else
        handle_model_error(response, model_name)
      end
    end

    # Store a context on the server.
    #
    # @param context_id [String] the context identifier
    # @param data [Hash] the context data to store
    # @param ttl [Integer, nil] time-to-live in seconds
    #
    # @return [ContextEntry] the stored context entry
    #
    # @raise [Ainos::ContextError] if storing fails
    #
    # @example
    #   context = client.context_store('my-conversation', { messages: [...] })
    def context_store(context_id, data, ttl: nil)
      response = send_request('context_store', {
        context_id: context_id.to_s,
        data: data,
        ttl: ttl
      }.compact)

      if response.success?
        payload = response.payload
        ContextEntry.new(
          id: context_id.to_s,
          data: data,
          created_at: payload.fetch('created_at', nil),
          updated_at: payload.fetch('updated_at', nil),
          ttl: ttl,
          token_count: payload.fetch('token_count', 0),
          metadata: payload.fetch('metadata', {})
        )
      else
        raise ContextError.new(
          response.error || "Failed to store context '#{context_id}'",
          context_id: context_id
        )
      end
    end

    # Retrieve a context from the server.
    #
    # @param context_id [String] the context identifier
    #
    # @return [ContextEntry, nil] the context entry, or nil if not found
    #
    # @raise [Ainos::ContextError] if retrieval fails
    #
    # @example
    #   context = client.context_retrieve('my-conversation')
    #   puts context.data.inspect
    def context_retrieve(context_id)
      response = send_request('context_retrieve', {
        context_id: context_id.to_s
      })

      if response.success?
        payload = response.payload
        return nil if payload.empty? || payload.fetch('data', nil).nil?

        ContextEntry.new(
          id: context_id.to_s,
          data: payload.fetch('data', {}),
          created_at: payload.fetch('created_at', nil),
          updated_at: payload.fetch('updated_at', nil),
          ttl: payload.fetch('ttl', nil),
          token_count: payload.fetch('token_count', 0),
          metadata: payload.fetch('metadata', {})
        )
      else
        raise ContextError.new(
          response.error || "Failed to retrieve context '#{context_id}'",
          context_id: context_id
        )
      end
    end

    # Ping the server to check connectivity.
    #
    # @return [Boolean] true if the server responds
    #
    # @example
    #   if client.ping
    #     puts "Server is reachable"
    #   end
    def ping
      response = send_request('ping', {})
      response.success?
    rescue Error
      false
    end

    # Get the version of the connected daemon.
    #
    # @return [String, nil] the daemon version
    def daemon_version
      status.version
    rescue Error
      nil
    end

    # Check if a specific model is loaded.
    #
    # @param model_name [String] the model name
    #
    # @return [Boolean] true if the model is loaded
    def model_loaded?(model_name)
      model_list.any? { |m| m.name == model_name && m.loaded? }
    end

    # Wait for a model to be ready.
    #
    # @param model_name [String] the model name
    # @param timeout [Float] maximum time to wait in seconds
    # @param poll_interval [Float] polling interval in seconds
    #
    # @return [Boolean] true if the model is ready
    #
    # @raise [Ainos::TimeoutError] if the model is not ready within timeout
    def wait_for_model(model_name, timeout: 60, poll_interval: 1.0)
      start = Time.now

      while Time.now - start < timeout
        models = model_list
        model = models.find { |m| m.name == model_name }

        if model&.loaded?
          return true
        end

        sleep(poll_interval)
      end

      raise TimeoutError.new(
        timeout: timeout,
        operation: "wait for model '#{model_name}' to be ready"
      )
    end

    # Get the total number of requests made.
    #
    # @return [Integer] the request count
    def request_count
      @mutex.synchronize { @request_count }
    end

    # Get connection statistics.
    #
    # @return [Hash] connection statistics
    def stats
      {
        connected: connected?,
        request_count: @mutex.synchronize { @request_count },
        connection_age: @transport.connection_age,
        transport_stats: @transport.stats.dup
      }
    end

    # @return [String] human-readable representation
    def inspect
      "#<#{self.class.name} #{@config.host}:#{@config.port} " \
        "connected=#{connected?}>"
    end

    # @return [String] a short string representation
    def to_s
      "Ainos::Client(#{@config.host}:#{@config.port})"
    end

    # Send a stream request to the daemon.
    # This method is public so it can be called from StreamSession.
    #
    # @param request [InferenceRequest] the inference request
    # @param request_id [String] the request ID
    #
    # @yield [StreamChunk] each chunk
    def send_stream_request(request, request_id:)
      ensure_connected!

      @mutex.synchronize { @request_count += 1 }

      @transport.send_stream_request(
        type: 'infer',
        payload: request.to_h,
        auth: @auth&.header_value,
        request_id: request_id
      ) do |chunk|
        yield chunk
      end
    rescue NotConnectedError => e
      raise ConnectionError.new(
        "Not connected to Ainos daemon at #{@config.host}:#{@config.port}",
        host: @config.host, port: @config.port, cause: e
      )
    end

    private

    # Setup authentication from configuration.
    #
    # @return [Auth, nil] the auth instance
    def setup_auth
      return nil unless @config.token

      Auth.new(@config.token, source: 'config')
    end

    # Send a request to the daemon.
    #
    # @param type [String] the request type
    # @param payload [Hash] the request payload
    #
    # @return [ServerResponse] the server response
    def send_request(type, payload)
      ensure_connected!

      @mutex.synchronize { @request_count += 1 }

      @transport.send_request(
        type: type,
        payload: payload,
        auth: @auth&.header_value
      )
    rescue NotConnectedError => e
      raise ConnectionError.new(
        "Not connected to Ainos daemon at #{@config.host}:#{@config.port}",
        host: @config.host, port: @config.port, cause: e
      )
    end

    # Build an inference request from arguments.
    #
    # @param args [Array] the arguments
    # @return [InferenceRequest] the request
    def build_inference_request(*args)
      if args.first.is_a?(InferenceRequest)
        args.first
      elsif args.first.is_a?(Hash)
        InferenceRequest.new(**args.first)
      else
        raise ArgumentError.new(
          argument_name: :args,
          message: "Expected InferenceRequest or Hash, got #{args.first.class}"
        )
      end
    end

    # Build a load request from arguments.
    #
    # @param args [Array] the arguments
    # @return [Hash] the load parameters
    def build_load_request(*args)
      if args.first.is_a?(ModelLoadRequest)
        args.first.to_h
      elsif args.first.is_a?(String) || args.first.is_a?(Symbol)
        { model: args.first.to_s }.merge(args[1] || {})
      elsif args.first.is_a?(Hash)
        args.first.transform_keys(&:to_sym)
      else
        raise ArgumentError.new(
          argument_name: :args,
          message: "Expected String, ModelLoadRequest, or Hash, got #{args.first&.class}"
        )
      end
    end

    # Handle an inference error response.
    #
    # @param response [ServerResponse] the error response
    # @param model_name [String] the model name
    #
    # @raise [Ainos::InferenceError] appropriate error subclass
    def handle_inference_error(response, model_name)
      error = response.error || 'Unknown inference error'
      code = response.payload.fetch('error_code', response.payload.fetch('code', ''))

      case code
      when 'model_not_found'
        raise ModelNotFoundError.new(model_name: model_name)
      when 'model_not_ready'
        raise ModelNotReadyError.new(
          model_name: model_name,
          status: response.payload.fetch('status', 'unknown')
        )
      when 'rate_limit'
        raise RateLimitError.new(
          retry_after: response.payload.fetch('retry_after', 60),
          model_name: model_name
        )
      when 'rejected'
        raise InferenceRejectedError.new(
          reason: response.payload.fetch('reason', error),
          model_name: model_name,
          request_id: response.id
        )
      else
        raise InferenceError.new(
          error,
          model_name: model_name,
          request_id: response.id
        )
      end
    end

    # Handle a model error response.
    #
    # @param response [ServerResponse] the error response
    # @param model_name [String] the model name
    #
    # @raise [Ainos::ModelError] appropriate error subclass
    def handle_model_error(response, model_name)
      error = response.error || 'Unknown model error'
      code = response.payload.fetch('error_code', response.payload.fetch('code', ''))

      case code
      when 'model_not_found'
        raise ModelNotFoundError.new(model_name: model_name)
      when 'load_failed'
        raise ModelLoadError.new(
          model_name: model_name,
          reason: response.payload.fetch('reason', error)
        )
      when 'unload_failed'
        raise ModelUnloadError.new(
          model_name: model_name,
          reason: response.payload.fetch('reason', error)
        )
      when 'not_ready'
        raise ModelNotReadyError.new(
          model_name: model_name,
          status: response.payload.fetch('status', 'unknown')
        )
      else
        raise ModelError.new(error, model_name: model_name)
      end
    end

    # Ensure the client is connected.
    #
    # @raise [Ainos::ConnectionError] if not connected
    def ensure_connected!
      connect unless connected?
    end

    # Cancel all active streams.
    def cancel_active_streams
      @active_streams.each(&:cancel)
      @active_streams.clear
    end
  end
end