# frozen_string_literal: true

require 'json'
require 'time'

module Ainos
  # Represents a request for model inference.
  #
  # @example Creating an inference request
  #   request = Ainos::InferenceRequest.new(
  #     model: 'llama3',
  #     prompt: 'Hello, world!',
  #     temperature: 0.8,
  #     max_tokens: 512
  #   )
  class InferenceRequest
    # @return [String] the model name to use for inference
    attr_reader :model

    # @return [String] the input prompt text
    attr_reader :prompt

    # @return [String, nil] optional system prompt
    attr_reader :system_prompt

    # @return [Float] the sampling temperature (0.0 to 2.0)
    attr_reader :temperature

    # @return [Integer] the maximum number of tokens to generate
    attr_reader :max_tokens

    # @return [Float] the nucleus sampling parameter (0.0 to 1.0)
    attr_reader :top_p

    # @return [Integer, nil] the top-k sampling parameter
    attr_reader :top_k

    # @return [Array<String>] sequences that stop generation
    attr_reader :stop_sequences

    # @return [Boolean] whether to stream the response
    attr_reader :stream

    # @return [String, nil] the context ID for continuing a conversation
    attr_reader :context_id

    # @return [Hash] additional metadata for the request
    attr_reader :metadata

    # @return [Hash] additional model-specific parameters
    attr_reader :parameters

    # @return [Float, nil] presence penalty
    attr_reader :presence_penalty

    # @return [Float, nil] frequency penalty
    attr_reader :frequency_penalty

    # @return [Integer, nil] seed for deterministic generation
    attr_reader :seed

    # @return [Integer, nil] number of responses to generate
    attr_reader :n

    # @return [Array<String>, nil] the messages in conversational format
    attr_reader :messages

    # Create a new inference request.
    #
    # @param model [String] the model name
    # @param prompt [String] the input prompt
    # @param system_prompt [String, nil] optional system prompt
    # @param temperature [Float] sampling temperature (default: 0.7)
    # @param max_tokens [Integer] maximum tokens to generate (default: 2048)
    # @param top_p [Float] nucleus sampling parameter (default: 1.0)
    # @param top_k [Integer, nil] top-k sampling parameter
    # @param stop_sequences [Array<String>] stop sequences (default: [])
    # @param stream [Boolean] enable streaming (default: false)
    # @param context_id [String, nil] conversation context ID
    # @param metadata [Hash] additional metadata (default: {})
    # @param parameters [Hash] model-specific parameters (default: {})
    # @param presence_penalty [Float, nil] presence penalty
    # @param frequency_penalty [Float, nil] frequency penalty
    # @param seed [Integer, nil] random seed
    # @param n [Integer, nil] number of responses
    # @param messages [Array<Hash>, nil] conversational messages
    #
    # @raise [Ainos::ArgumentError] if validation fails
    def initialize(model:, prompt: nil, system_prompt: nil,
                   temperature: 0.7, max_tokens: 2048, top_p: 1.0,
                   top_k: nil, stop_sequences: [], stream: false,
                   context_id: nil, metadata: {}, parameters: {},
                   presence_penalty: nil, frequency_penalty: nil,
                   seed: nil, n: nil, messages: nil)
      @model = validate_model(model)
      @prompt = validate_prompt(prompt) if prompt
      @system_prompt = system_prompt
      @temperature = validate_temperature(temperature)
      @max_tokens = validate_max_tokens(max_tokens)
      @top_p = validate_top_p(top_p)
      @top_k = top_k
      @stop_sequences = stop_sequences || []
      @stream = stream
      @context_id = context_id
      @metadata = metadata || {}
      @parameters = parameters || {}
      @presence_penalty = presence_penalty
      @frequency_penalty = frequency_penalty
      @seed = seed
      @n = n
      @messages = messages

      validate_request!
    end

    # Convert the request to a hash.
    #
    # @return [Hash] the hash representation
    def to_h
      hash = {
        model: @model,
        temperature: @temperature,
        max_tokens: @max_tokens,
        top_p: @top_p,
        stop_sequences: @stop_sequences,
        stream: @stream
      }

      hash[:prompt] = @prompt if @prompt
      hash[:system_prompt] = @system_prompt if @system_prompt
      hash[:top_k] = @top_k if @top_k
      hash[:context_id] = @context_id if @context_id
      hash[:metadata] = @metadata unless @metadata.empty?
      hash[:parameters] = @parameters unless @parameters.empty?
      hash[:presence_penalty] = @presence_penalty if @presence_penalty
      hash[:frequency_penalty] = @frequency_penalty if @frequency_penalty
      hash[:seed] = @seed if @seed
      hash[:n] = @n if @n
      hash[:messages] = @messages if @messages

      hash.compact
    end

    # Convert the request to a JSON string.
    #
    # @return [String] the JSON representation
    def to_json(*args)
      JSON.generate(to_h, *args)
    end

    # @return [String] a human-readable representation
    def inspect
      "#<#{self.class.name} model=#{@model.inspect} stream=#{@stream}>"
    end

    # @return [String] a short string representation
    def to_s
      "InferenceRequest(model: #{@model}, stream: #{@stream})"
    end

    private

    # Validate the model name.
    #
    # @param model [String] the model name
    # @return [String] the validated model name
    # @raise [Ainos::ArgumentError] if the model name is invalid
    def validate_model(model)
      raise ArgumentError.new(argument_name: :model,
        message: 'Model name is required') if model.nil? || model.to_s.strip.empty?

      model.to_s.strip
    end

    # Validate the prompt.
    #
    # @param prompt [String] the prompt
    # @return [String] the validated prompt
    # @raise [Ainos::ArgumentError] if the prompt is invalid
    def validate_prompt(prompt)
      prompt = prompt.to_s
      raise ArgumentError.new(argument_name: :prompt,
        message: 'Prompt must not be empty') if prompt.strip.empty?

      prompt
    end

    # Validate the temperature.
    #
    # @param temp [Float] the temperature
    # @return [Float] the validated temperature
    # @raise [Ainos::ArgumentError] if temperature is out of range
    def validate_temperature(temp)
      temp = temp.to_f
      raise ArgumentError.new(argument_name: :temperature,
        message: "Temperature must be between 0.0 and 2.0, got #{temp}") \
        if temp.negative? || temp > 2.0

      temp
    end

    # Validate max_tokens.
    #
    # @param tokens [Integer] the max tokens
    # @return [Integer] the validated max tokens
    # @raise [Ainos::ArgumentError] if max_tokens is invalid
    def validate_max_tokens(tokens)
      tokens = tokens.to_i
      raise ArgumentError.new(argument_name: :max_tokens,
        message: "max_tokens must be positive, got #{tokens}") \
        if tokens < 1

      tokens
    end

    # Validate top_p.
    #
    # @param p [Float] the top_p value
    # @return [Float] the validated top_p
    # @raise [Ainos::ArgumentError] if top_p is out of range
    def validate_top_p(p)
      p = p.to_f
      raise ArgumentError.new(argument_name: :top_p,
        message: "top_p must be between 0.0 and 1.0, got #{p}") \
        if p < 0.0 || p > 1.0

      p
    end

    # Validate the request as a whole.
    #
    # @raise [Ainos::ArgumentError] if the request is invalid
    def validate_request!
      if @prompt.nil? && @messages.nil?
        raise ArgumentError.new(argument_name: :prompt,
          message: 'Either prompt or messages must be provided')
      end

      if @prompt && @messages
        raise ArgumentError.new(argument_name: :messages,
          message: 'Cannot provide both prompt and messages')
      end
    end
  end

  # Represents a response from an inference request.
  #
  # @example
  #   response = client.infer(request)
  #   puts response.text
  class InferenceResponse
    # @return [String] the generated text
    attr_reader :text

    # @return [Integer] the number of tokens generated
    attr_reader :tokens

    # @return [String] the reason for finishing (e.g., 'stop', 'length')
    attr_reader :finish_reason

    # @return [String, nil] the model name that generated the response
    attr_reader :model

    # @return [String, nil] the request ID
    attr_reader :request_id

    # @return [Hash] usage statistics
    attr_reader :usage

    # @return [Hash] timing information
    attr_reader :timing

    # @return [Hash] additional metadata
    attr_reader :metadata

    # @return [Array<String>, nil] alternative completions
    attr_reader :choices

    # @return [Float, nil] the log probabilities
    attr_reader :logprobs

    # Create a new inference response.
    #
    # @param text [String] the generated text
    # @param tokens [Integer] number of tokens generated
    # @param finish_reason [String] the finish reason
    # @param model [String, nil] the model name
    # @param request_id [String, nil] the request ID
    # @param usage [Hash] token usage statistics
    # @param timing [Hash] timing information
    # @param metadata [Hash] additional metadata
    # @param choices [Array<String>, nil] alternative completions
    # @param logprobs [Float, nil] log probabilities
    def initialize(text:, tokens: 0, finish_reason: 'stop',
                   model: nil, request_id: nil, usage: {}, timing: {},
                   metadata: {}, choices: nil, logprobs: nil)
      @text = text.to_s
      @tokens = tokens.to_i
      @finish_reason = finish_reason.to_s
      @model = model
      @request_id = request_id
      @usage = usage
      @timing = timing
      @metadata = metadata
      @choices = choices
      @logprobs = logprobs
    end

    # Check if the generation is finished.
    #
    # @return [Boolean] true if generation is complete
    def finished?
      @finish_reason != 'incomplete'
    end

    # Check if the generation was stopped due to length.
    #
    # @return [Boolean] true if stopped due to max tokens
    def truncated?
      @finish_reason == 'length'
    end

    # Check if the generation was stopped due to a stop sequence.
    #
    # @return [Boolean] true if stopped by a stop sequence
    def stopped?
      @finish_reason == 'stop'
    end

    # Get the total tokens used (input + output).
    #
    # @return [Integer] total token count
    def total_tokens
      @usage.fetch('total_tokens', @usage.fetch(:total_tokens, @tokens))
    end

    # Get the prompt tokens used.
    #
    # @return [Integer] prompt token count
    def prompt_tokens
      @usage.fetch('prompt_tokens', @usage.fetch(:prompt_tokens, 0))
    end

    # Get the generation time in seconds.
    #
    # @return [Float, nil] generation time
    def generation_time
      @timing.fetch('generation_ms', @timing.fetch(:generation_ms, nil))&.then { |ms| ms / 1000.0 }
    end

    # Convert the response to a hash.
    #
    # @return [Hash] the hash representation
    def to_h
      {
        text: @text,
        tokens: @tokens,
        finish_reason: @finish_reason,
        model: @model,
        request_id: @request_id,
        usage: @usage,
        timing: @timing,
        metadata: @metadata,
        choices: @choices,
        logprobs: @logprobs
      }.compact
    end

    # @return [String] human-readable representation
    def inspect
      "#<#{self.class.name} tokens=#{@tokens} finish_reason=#{@finish_reason.inspect}>"
    end
  end

  # Represents a single chunk of a streaming response.
  #
  # @example
  #   client.infer_stream(request) do |chunk|
  #     print chunk.text
  #   end
  class StreamChunk
    # @return [String] the text content of this chunk
    attr_reader :text

    # @return [Integer] the index of this chunk in the stream
    attr_reader :index

    # @return [Boolean] whether this is the final chunk
    attr_reader :finished

    # @return [String, nil] the finish reason (only on final chunk)
    attr_reader :finish_reason

    # @return [Integer, nil] cumulative token count
    attr_reader :tokens

    # @return [String, nil] the request ID
    attr_reader :request_id

    # @return [Float, nil] log probabilities for this chunk
    attr_reader :logprobs

    # @return [Hash] additional metadata
    attr_reader :metadata

    # Create a new stream chunk.
    #
    # @param text [String] the chunk text
    # @param index [Integer] the chunk index
    # @param finished [Boolean] whether this is the final chunk
    # @param finish_reason [String, nil] the finish reason
    # @param tokens [Integer, nil] cumulative token count
    # @param request_id [String, nil] the request ID
    # @param logprobs [Float, nil] log probabilities
    # @param metadata [Hash] additional metadata
    def initialize(text:, index: 0, finished: false, finish_reason: nil,
                   tokens: nil, request_id: nil, logprobs: nil, metadata: {})
      @text = text.to_s
      @index = index.to_i
      @finished = finished
      @finish_reason = finish_reason
      @tokens = tokens&.to_i
      @request_id = request_id
      @logprobs = logprobs
      @metadata = metadata
    end

    # @return [Boolean] whether this is the final chunk
    def final?
      @finished
    end

    # @return [String] human-readable representation
    def inspect
      "#<#{self.class.name} index=#{@index} finished=#{@finished} text=#{@text.truncate(30).inspect}>"
    end

    # Combine this chunk with another to form a complete response.
    #
    # @param other [StreamChunk] the next chunk
    # @return [StreamChunk] a new combined chunk
    def +(other)
      StreamChunk.new(
        text: @text + other.text,
        index: other.index,
        finished: other.finished,
        finish_reason: other.finish_reason || @finish_reason,
        tokens: other.tokens || @tokens,
        request_id: @request_id || other.request_id,
        logprobs: other.logprobs || @logprobs,
        metadata: @metadata.merge(other.metadata)
      )
    end
  end

  # Information about a model available on the server.
  #
  # @example
  #   model = client.model_list.first
  #   puts "#{model.name} (#{model.status})"
  class ModelInfo
    # @return [String] the model name
    attr_reader :name

    # @return [String, nil] the model version
    attr_reader :version

    # @return [String, nil] the model file path on the server
    attr_reader :path

    # @return [String] the current status
    attr_reader :status

    # @return [Time, nil] when the model was loaded
    attr_reader :loaded_at

    # @return [Integer] the model size in bytes
    attr_reader :size_bytes

    # @return [Array<String>] the model's capabilities
    attr_reader :capabilities

    # @return [Hash] model configuration
    attr_reader :config

    # @return [String, nil] the model's description
    attr_reader :description

    # @return [String, nil] the model's architecture
    attr_reader :architecture

    # @return [String, nil] the model's quantization
    attr_reader :quantization

    # @return [Integer, nil] the context length
    attr_reader :context_length

    # Create a new model info.
    #
    # @param name [String] the model name
    # @param version [String, nil] the model version
    # @param path [String, nil] the model file path
    # @param status [String] the current status
    # @param loaded_at [Time, String, nil] when the model was loaded
    # @param size_bytes [Integer] the model size
    # @param capabilities [Array<String>] model capabilities
    # @param config [Hash] model configuration
    # @param description [String, nil] model description
    # @param architecture [String, nil] model architecture
    # @param quantization [String, nil] quantization method
    # @param context_length [Integer, nil] context length
    def initialize(name:, version: nil, path: nil, status: 'unknown',
                   loaded_at: nil, size_bytes: 0, capabilities: [],
                   config: {}, description: nil, architecture: nil,
                   quantization: nil, context_length: nil)
      @name = name.to_s
      @version = version&.to_s
      @path = path&.to_s
      @status = status.to_s
      @loaded_at = parse_time(loaded_at)
      @size_bytes = size_bytes.to_i
      @capabilities = capabilities.map(&:to_s)
      @config = config
      @description = description&.to_s
      @architecture = architecture&.to_s
      @quantization = quantization&.to_s
      @context_length = context_length&.to_i
    end

    # Check if the model is loaded and ready.
    #
    # @return [Boolean] true if the model is loaded
    def loaded?
      @status == 'loaded'
    end

    # Check if the model is loading.
    #
    # @return [Boolean] true if the model is loading
    def loading?
      @status == 'loading'
    end

    # Check if the model is unloaded.
    #
    # @return [Boolean] true if the model is unloaded
    def unloaded?
      @status == 'unloaded' || @status == 'unknown'
    end

    # Check if the model has a specific capability.
    #
    # @param capability [String] the capability to check
    # @return [Boolean] true if the model has the capability
    def supports?(capability)
      @capabilities.include?(capability.to_s)
    end

    # Get the human-readable size.
    #
    # @return [String] the formatted size
    def size_human
      bytes = @size_bytes
      return '0 B' if bytes.zero?

      units = %w[B KB MB GB TB]
      unit_idx = 0

      while bytes >= 1024 && unit_idx < units.length - 1
        bytes /= 1024.0
        unit_idx += 1
      end

      format('%.1f %s', bytes, units[unit_idx])
    end

    # Convert to hash.
    #
    # @return [Hash] the hash representation
    def to_h
      {
        name: @name,
        version: @version,
        path: @path,
        status: @status,
        loaded_at: @loaded_at&.iso8601,
        size_bytes: @size_bytes,
        capabilities: @capabilities,
        config: @config,
        description: @description,
        architecture: @architecture,
        quantization: @quantization,
        context_length: @context_length
      }.compact
    end

    # @return [String] human-readable representation
    def inspect
      "#<#{self.class.name} name=#{@name.inspect} status=#{@status.inspect}>"
    end

    private

    # Parse a time value that could be a string or Time.
    #
    # @param value [Time, String, nil] the time value
    # @return [Time, nil] the parsed time
    def parse_time(value)
      case value
      when Time then value
      when String then Time.parse(value)
      when Integer then Time.at(value)
      else nil
      end
    rescue ArgumentError
      nil
    end
  end

  # Represents the health status of the Ainos daemon.
  #
  # @example
  #   health = client.health
  #   puts "Server is #{health.status}" unless health.healthy?
  class HealthStatus
    # @return [String] the overall health status
    attr_reader :status

    # @return [Boolean] whether the daemon is healthy
    attr_reader :healthy

    # @return [String, nil] the version of the daemon
    attr_reader :version

    # @return [Time, nil] the daemon uptime
    attr_reader :uptime

    # @return [Integer, nil] the number of active connections
    attr_reader :active_connections

    # @return [Integer, nil] the number of loaded models
    attr_reader :loaded_models

    # @return [Hash] additional health details
    attr_reader :details

    # Create a new health status.
    #
    # @param status [String] the health status string
    # @param healthy [Boolean] whether the daemon is healthy
    # @param version [String, nil] the daemon version
    # @param uptime [Float, nil] the daemon uptime in seconds
    # @param active_connections [Integer, nil] active connections
    # @param loaded_models [Integer, nil] loaded models
    # @param details [Hash] additional details
    def initialize(status:, healthy: true, version: nil, uptime: nil,
                   active_connections: nil, loaded_models: nil, details: {})
      @status = status.to_s
      @healthy = healthy
      @version = version&.to_s
      @uptime = uptime&.to_f
      @active_connections = active_connections&.to_i
      @loaded_models = loaded_models&.to_i
      @details = details
    end

    # @return [Boolean] true if the daemon is healthy
    def healthy?
      @healthy
    end

    # Convert to hash.
    #
    # @return [Hash] the hash representation
    def to_h
      {
        status: @status,
        healthy: @healthy,
        version: @version,
        uptime: @uptime,
        active_connections: @active_connections,
        loaded_models: @loaded_models,
        details: @details
      }.compact
    end

    # @return [String] human-readable representation
    def inspect
      "#<#{self.class.name} status=#{@status.inspect} healthy=#{@healthy}>"
    end
  end

  # Represents the detailed server status.
  #
  # @example
  #   status = client.status
  #   puts status.to_s
  class ServerStatus
    # @return [String] the server version
    attr_reader :version

    # @return [Time, nil] when the server started
    attr_reader :started_at

    # @return [Integer] the number of active connections
    attr_reader :active_connections

    # @return [Integer] the total number of requests served
    attr_reader :total_requests

    # @return [Float] the average request latency in ms
    attr_reader :avg_latency_ms

    # @return [Integer] the number of loaded models
    attr_reader :loaded_models

    # @return [Integer] the total number of models available
    attr_reader :total_models

    # @return [Hash] memory usage statistics
    attr_reader :memory

    # @return [Hash] CPU usage statistics
    attr_reader :cpu

    # @return [Hash] GPU usage statistics (if applicable)
    attr_reader :gpu

    # @return [Hash] additional details
    attr_reader :details

    # Create a new server status.
    #
    # @param version [String] the server version
    # @param started_at [Time, String, nil] when the server started
    # @param active_connections [Integer] active connections
    # @param total_requests [Integer] total requests served
    # @param avg_latency_ms [Float] average latency
    # @param loaded_models [Integer] loaded models
    # @param total_models [Integer] total models
    # @param memory [Hash] memory stats
    # @param cpu [Hash] CPU stats
    # @param gpu [Hash] GPU stats
    # @param details [Hash] additional details
    def initialize(version: 'unknown', started_at: nil,
                   active_connections: 0, total_requests: 0,
                   avg_latency_ms: 0.0, loaded_models: 0, total_models: 0,
                   memory: {}, cpu: {}, gpu: {}, details: {})
      @version = version.to_s
      @started_at = parse_time(started_at)
      @active_connections = active_connections.to_i
      @total_requests = total_requests.to_i
      @avg_latency_ms = avg_latency_ms.to_f
      @loaded_models = loaded_models.to_i
      @total_models = total_models.to_i
      @memory = memory
      @cpu = cpu
      @gpu = gpu
      @details = details
    end

    # @return [Float, nil] the uptime in seconds
    def uptime
      return nil unless @started_at

      Time.now - @started_at
    end

    # Convert to hash.
    #
    # @return [Hash] the hash representation
    def to_h
      {
        version: @version,
        started_at: @started_at&.iso8601,
        active_connections: @active_connections,
        total_requests: @total_requests,
        avg_latency_ms: @avg_latency_ms,
        loaded_models: @loaded_models,
        total_models: @total_models,
        memory: @memory,
        cpu: @cpu,
        gpu: @gpu,
        details: @details
      }.compact
    end

    # @return [String] a formatted status string
    def to_s
      "Server v#{@version} | " \
      "Uptime: #{format_uptime} | " \
      "Models: #{@loaded_models}/#{@total_models} loaded | " \
      "Requests: #{@total_requests} | " \
      "Avg latency: #{format('%.1f', @avg_latency_ms)}ms"
    end

    # @return [String] human-readable representation
    def inspect
      "#<#{self.class.name} version=#{@version.inspect}>"
    end

    private

    # Parse a time value.
    def parse_time(value)
      case value
      when Time then value
      when String then Time.parse(value)
      when Integer then Time.at(value)
      else nil
      end
    rescue ArgumentError
      nil
    end

    # Format the uptime as a human-readable string.
    def format_uptime
      seconds = uptime.to_i
      return 'N/A' if seconds.zero?

      days = seconds / 86_400
      hours = (seconds % 86_400) / 3600
      minutes = (seconds % 3600) / 60
      secs = seconds % 60

      parts = []
      parts << "#{days}d" if days.positive?
      parts << "#{hours}h" if hours.positive?
      parts << "#{minutes}m" if minutes.positive?
      parts << "#{secs}s"
      parts.join(' ')
    end
  end

  # Represents a context entry for conversation state management.
  #
  # @example
  #   context = client.context_store('my-context', { key: 'value' })
  #   data = client.context_retrieve('my-context')
  class ContextEntry
    # @return [String] the context ID
    attr_reader :id

    # @return [Hash] the context data
    attr_reader :data

    # @return [Time, nil] when the context was created
    attr_reader :created_at

    # @return [Time, nil] when the context was last updated
    attr_reader :updated_at

    # @return [Integer, nil] the time-to-live in seconds
    attr_reader :ttl

    # @return [Integer] the number of tokens in the context
    attr_reader :token_count

    # @return [Hash] additional metadata
    attr_reader :metadata

    # Create a new context entry.
    #
    # @param id [String] the context ID
    # @param data [Hash] the context data
    # @param created_at [Time, String, nil] creation time
    # @param updated_at [Time, String, nil] last update time
    # @param ttl [Integer, nil] time-to-live in seconds
    # @param token_count [Integer] token count
    # @param metadata [Hash] additional metadata
    def initialize(id:, data: {}, created_at: nil, updated_at: nil,
                   ttl: nil, token_count: 0, metadata: {})
      @id = id.to_s
      @data = data
      @created_at = parse_time(created_at)
      @updated_at = parse_time(updated_at)
      @ttl = ttl&.to_i
      @token_count = token_count.to_i
      @metadata = metadata
    end

    # Check if the context has expired.
    #
    # @return [Boolean] true if the context has expired
    def expired?
      return false unless @ttl && @updated_at

      (Time.now - @updated_at) > @ttl
    end

    # Check if the context is still valid.
    #
    # @return [Boolean] true if the context has not expired
    def valid?
      !expired?
    end

    # Convert to hash.
    #
    # @return [Hash] the hash representation
    def to_h
      {
        id: @id,
        data: @data,
        created_at: @created_at&.iso8601,
        updated_at: @updated_at&.iso8601,
        ttl: @ttl,
        token_count: @token_count,
        metadata: @metadata
      }.compact
    end

    # @return [String] human-readable representation
    def inspect
      "#<#{self.class.name} id=#{@id.inspect} expired=#{expired?}>"
    end

    private

    # Parse a time value.
    def parse_time(value)
      case value
      when Time then value
      when String then Time.parse(value)
      when Integer then Time.at(value)
      else nil
      end
    rescue ArgumentError
      nil
    end
  end

  # Represents a model load request.
  #
  # @example
  #   request = Ainos::ModelLoadRequest.new(model: 'llama3', gpu_layers: 32)
  class ModelLoadRequest
    # @return [String] the model name
    attr_reader :model

    # @return [Integer, nil] number of GPU layers
    attr_reader :gpu_layers

    # @return [Integer, nil] context size
    attr_reader :context_size

    # @return [Integer, nil] batch size
    attr_reader :batch_size

    # @return [Integer, nil] number of threads
    attr_reader :threads

    # @return [Boolean, nil] use memory lock
    attr_reader :mlock

    # @return [Boolean, nil] use memory mapping
    attr_reader :mmap

    # @return [Hash] additional load parameters
    attr_reader :parameters

    # Create a new model load request.
    #
    # @param model [String] the model name
    # @param gpu_layers [Integer, nil] GPU layers
    # @param context_size [Integer, nil] context size
    # @param batch_size [Integer, nil] batch size
    # @param threads [Integer, nil] number of threads
    # @param mlock [Boolean, nil] memory lock
    # @param mmap [Boolean, nil] memory mapping
    # @param parameters [Hash] additional parameters
    def initialize(model:, gpu_layers: nil, context_size: nil,
                   batch_size: nil, threads: nil, mlock: nil, mmap: nil,
                   parameters: {})
      @model = model.to_s
      @gpu_layers = gpu_layers&.to_i
      @context_size = context_size&.to_i
      @batch_size = batch_size&.to_i
      @threads = threads&.to_i
      @mlock = mlock
      @mmap = mmap
      @parameters = parameters || {}
    end

    # Convert to hash.
    #
    # @return [Hash] the hash representation
    def to_h
      hash = { model: @model }
      hash[:gpu_layers] = @gpu_layers if @gpu_layers
      hash[:context_size] = @context_size if @context_size
      hash[:batch_size] = @batch_size if @batch_size
      hash[:threads] = @threads if @threads
      hash[:mlock] = @mlock unless @mlock.nil?
      hash[:mmap] = @mmap unless @mmap.nil?
      hash[:parameters] = @parameters unless @parameters.empty?
      hash.compact
    end

    # Convert to JSON.
    #
    # @return [String] the JSON representation
    def to_json(*args)
      JSON.generate(to_h, *args)
    end

    # @return [String] human-readable representation
    def inspect
      "#<#{self.class.name} model=#{@model.inspect}>"
    end
  end

  # Represents a request to the server with all necessary metadata.
  #
  # @api private
  class ServerRequest
    # @return [String] the request type
    attr_reader :type

    # @return [String] the request ID
    attr_reader :id

    # @return [Hash] the request payload
    attr_reader :payload

    # @return [String, nil] the authentication token
    attr_reader :auth

    # @return [String] the protocol version
    attr_reader :version

    # Create a new server request.
    #
    # @param type [String] the request type
    # @param payload [Hash] the request payload
    # @param id [String, nil] the request ID (auto-generated if nil)
    # @param auth [String, nil] the auth token
    # @param version [String] the protocol version
    def initialize(type:, payload:, id: nil, auth: nil, version: PROTOCOL_VERSION)
      @type = type.to_s
      @id = id || SecureRandom.uuid
      @payload = payload
      @auth = auth
      @version = version
    end

    # Convert to hash.
    #
    # @return [Hash] the hash representation
    def to_h
      hash = {
        type: @type,
        id: @id,
        payload: @payload,
        version: @version
      }
      hash[:auth] = @auth if @auth
      hash
    end

    # Convert to JSON.
    #
    # @return [String] the JSON representation
    def to_json(*args)
      JSON.generate(to_h, *args)
    end
  end

  # Represents a response from the server.
  #
  # @api private
  class ServerResponse
    # @return [String] the response type
    attr_reader :type

    # @return [String] the request ID this response corresponds to
    attr_reader :id

    # @return [Hash] the response payload
    attr_reader :payload

    # @return [Boolean] whether the request was successful
    attr_reader :ok

    # @return [String, nil] error message if the request failed
    attr_reader :error

    # Create a new server response from a parsed JSON hash.
    #
    # @param hash [Hash] the parsed JSON hash
    # @return [ServerResponse] a new response
    def self.from_hash(hash)
      new(
        type: hash['type'] || hash[:type],
        id: hash['id'] || hash[:id],
        payload: hash['payload'] || hash[:payload] || {},
        ok: hash.fetch('ok', hash.fetch(:ok, true)),
        error: hash['error'] || hash[:error]
      )
    end

    # @param type [String] the response type
    # @param id [String] the request ID
    # @param payload [Hash] the response payload
    # @param ok [Boolean] success flag
    # @param error [String, nil] error message
    def initialize(type:, id:, payload: {}, ok: true, error: nil)
      @type = type.to_s
      @id = id.to_s
      @payload = payload
      @ok = ok
      @error = error
    end

    # @return [Boolean] whether the response indicates success
    def success?
      @ok
    end

    # @return [Boolean] whether the response indicates an error
    def error?
      !@ok
    end

    # @return [Boolean] whether this is a streaming chunk
    def stream?
      @type == 'stream'
    end

    # @return [Boolean] whether this is a stream end marker
    def stream_end?
      @type == 'stream_end'
    end

    # @return [String] human-readable representation
    def inspect
      "#<#{self.class.name} type=#{@type.inspect} id=#{@id.inspect} ok=#{@ok}>"
    end
  end

  # Configuration for the Ainos client.
  #
  # @example
  #   config = Ainos::Configuration.new(
  #     host: 'localhost',
  #     port: 9500,
  #     token: ENV['AINOS_TOKEN']
  #   )
  class Configuration
    # @return [String] the daemon host
    attr_accessor :host

    # @return [Integer] the daemon port
    attr_accessor :port

    # @return [String, nil] the authentication token
    attr_accessor :token

    # @return [Float] the connection timeout in seconds
    attr_accessor :connection_timeout

    # @return [Float] the read timeout in seconds
    attr_accessor :read_timeout

    # @return [Float] the write timeout in seconds
    attr_accessor :write_timeout

    # @return [Integer] the maximum number of reconnection attempts
    attr_accessor :max_reconnect_attempts

    # @return [Float] the delay between reconnection attempts
    attr_accessor :reconnect_delay

    # @return [Boolean] whether to automatically reconnect
    attr_accessor :auto_reconnect

    # @return [Logger, nil] a logger instance
    attr_accessor :logger

    # @return [Boolean] whether to enable SSL/TLS
    attr_accessor :ssl

    # @return [Boolean] whether to verify the server certificate
    attr_accessor :ssl_verify

    # @return [Integer] the maximum message size in bytes
    attr_accessor :max_message_size

    # @return [Boolean] whether to compress messages
    attr_accessor :compression

    # Create a new configuration.
    #
    # @param host [String] the daemon host
    # @param port [Integer] the daemon port
    # @param token [String, nil] the auth token
    # @param connection_timeout [Float] connection timeout
    # @param read_timeout [Float] read timeout
    # @param write_timeout [Float] write timeout
    # @param max_reconnect_attempts [Integer] max reconnects
    # @param reconnect_delay [Float] reconnect delay
    # @param auto_reconnect [Boolean] auto reconnect
    # @param logger [Logger, nil] logger
    # @param ssl [Boolean] SSL/TLS
    # @param ssl_verify [Boolean] verify certificate
    # @param max_message_size [Integer] max message size
    # @param compression [Boolean] compression
    def initialize(host: DEFAULT_HOST, port: DEFAULT_PORT, token: nil,
                   connection_timeout: 5.0, read_timeout: 30.0,
                   write_timeout: 10.0, max_reconnect_attempts: 3,
                   reconnect_delay: 1.0, auto_reconnect: true,
                   logger: nil, ssl: false, ssl_verify: true,
                   max_message_size: MAX_MESSAGE_SIZE, compression: false)
      @host = host
      @port = port
      @token = token
      @connection_timeout = connection_timeout
      @read_timeout = read_timeout
      @write_timeout = write_timeout
      @max_reconnect_attempts = max_reconnect_attempts
      @reconnect_delay = reconnect_delay
      @auto_reconnect = auto_reconnect
      @logger = logger
      @ssl = ssl
      @ssl_verify = ssl_verify
      @max_message_size = max_message_size
      @compression = compression
    end

    # Create a configuration from a hash.
    #
    # @param hash [Hash] the configuration hash
    # @return [Configuration] a new configuration
    def self.from_hash(hash)
      new(**hash.transform_keys(&:to_sym))
    end

    # Convert to a hash.
    #
    # @return [Hash] the hash representation
    def to_h
      {
        host: @host,
        port: @port,
        token: @token&.then { |t| "#{t.slice(0, 4)}...#{t.slice(-4, 4)}" },
        connection_timeout: @connection_timeout,
        read_timeout: @read_timeout,
        write_timeout: @write_timeout,
        max_reconnect_attempts: @max_reconnect_attempts,
        reconnect_delay: @reconnect_delay,
        auto_reconnect: @auto_reconnect,
        ssl: @ssl,
        ssl_verify: @ssl_verify,
        max_message_size: @max_message_size,
        compression: @compression
      }
    end

    # @return [String] human-readable representation
    def inspect
      "#<#{self.class.name} #{@host}:#{@port}>"
    end
  end
end