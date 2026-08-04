# frozen_string_literal: true

module Ainos
  # Provides streaming inference capabilities with Enumerator support.
  #
  # Allows processing inference results as they arrive, without waiting
  # for the complete response. Supports both block-based and lazy
  # Enumerator-based iteration.
  #
  # @example Block-based iteration
  #   stream = Ainos::StreamSession.new(client, request)
  #   stream.each_chunk { |chunk| print chunk.text }
  #
  # @example Enumerator-based iteration
  #   stream = Ainos::StreamSession.new(client, request)
  #   chunks = stream.to_enum(:each_chunk).map(&:text).join
  #
  # @example Building a complete response
  #   stream = Ainos::StreamSession.new(client, request)
  #   response = stream.collect
  class StreamSession
    # @return [Ainos::Client] the client instance
    attr_reader :client

    # @return [Ainos::InferenceRequest] the request
    attr_reader :request

    # @return [String] the request ID
    attr_reader :request_id

    # @return [String] the model name
    attr_reader :model

    # @return [Array<StreamChunk>] collected chunks
    attr_reader :chunks

    # Create a new stream session.
    #
    # @param client [Ainos::Client] the client instance
    # @param request [Ainos::InferenceRequest] the inference request
    # @param request_id [String, nil] optional request ID
    def initialize(client, request, request_id: nil)
      @client = client
      @request = request
      @request_id = request_id || SecureRandom.uuid
      @model = request.model
      @chunks = []
      @started = false
      @finished = false
      @mutex = Mutex.new
      @chunk_count = 0
      @total_text_length = 0
    end

    # Start the streaming session and yield each chunk.
    #
    # @yield [StreamChunk] each chunk as it arrives
    #
    # @return [self] the stream session
    #
    # @raise [Ainos::InferenceError] if streaming fails
    def each_chunk(&block)
      return to_enum(:each_chunk) unless block

      @mutex.synchronize { @started = true }

      begin
        @client.send_stream_request(
          @request,
          request_id: @request_id
        ) do |chunk|
          @mutex.synchronize do
            @chunks << chunk
            @chunk_count += 1
            @total_text_length += chunk.text.length
            @finished = chunk.final?
          end

          block.call(chunk)
        end
      rescue StandardError => e
        @mutex.synchronize { @finished = true }
        raise InferenceError.new(
          "Streaming failed: #{e.message}",
          model_name: @model,
          request_id: @request_id,
          cause: e
        )
      end

      @mutex.synchronize { @finished = true }
      self
    end

    # Collect all chunks into a single response.
    #
    # @return [Ainos::InferenceResponse] the complete response
    def collect
      each_chunk {}

      return nil if @chunks.empty?

      last_chunk = @chunks.last
      full_text = @chunks.map(&:text).join

      InferenceResponse.new(
        text: full_text,
        tokens: last_chunk.tokens || @chunks.sum { |c| c.text.length / 4 },
        finish_reason: last_chunk.finish_reason || 'stop',
        model: @model,
        request_id: @request_id,
        usage: {
          'total_tokens' => last_chunk.tokens || @chunks.sum { |c| c.text.length / 4 },
          'completion_tokens' => @chunks.sum { |c| c.text.length / 4 },
          'prompt_tokens' => 0
        },
        timing: { 'generation_ms' => 0 }
      )
    end

    # Process the stream with a callback for each chunk and a
    # completion callback when finished.
    #
    # @param on_chunk [Proc, nil] called for each chunk
    # @param on_complete [Proc, nil] called with the complete response
    # @param on_error [Proc, nil] called on error
    #
    # @return [Ainos::InferenceResponse, nil] the response, or nil on error
    def process(on_chunk: nil, on_complete: nil, on_error: nil)
      begin
        each_chunk do |chunk|
          on_chunk&.call(chunk)
        end

        response = collect
        on_complete&.call(response)
        response
      rescue InferenceError => e
        on_error&.call(e)
        nil
      end
    end

    # Check if the stream has finished.
    #
    # @return [Boolean] true if the stream is complete
    def finished?
      @mutex.synchronize { @finished }
    end

    # Check if the stream has started.
    #
    # @return [Boolean] true if the stream has started
    def started?
      @mutex.synchronize { @started }
    end

    # Get the number of chunks received.
    #
    # @return [Integer] the chunk count
    def chunk_count
      @mutex.synchronize { @chunk_count }
    end

    # Get the total text length received.
    #
    # @return [Integer] the total text length
    def total_text_length
      @mutex.synchronize { @total_text_length }
    end

    # Get the current accumulated text.
    #
    # @return [String] the accumulated text
    def accumulated_text
      @mutex.synchronize { @chunks.map(&:text).join }
    end

    # Cancel the stream (if supported).
    def cancel
      @mutex.synchronize { @finished = true }
    end

    # @return [String] human-readable representation
    def inspect
      "#<#{self.class.name} model=#{@model.inspect} " \
        "chunks=#{@chunk_count} finished=#{@finished}>"
    end
  end

  # Accumulates streaming chunks into a buffer with callbacks.
  #
  # Useful for real-time processing of streaming text, such as
  # updating a UI or processing partial results.
  #
  # @example
  #   accumulator = Ainos::StreamAccumulator.new
  #   accumulator.on_chunk { |chunk| print chunk.text }
  #   accumulator.on_finish { |full_text| puts "\nDone!" }
  class StreamAccumulator
    # @return [String] the accumulated text
    attr_reader :buffer

    # @return [Integer] the number of chunks processed
    attr_reader :chunk_count

    # @return [Boolean] whether accumulation is complete
    attr_reader :finished

    # Create a new stream accumulator.
    def initialize
      @buffer = +''
      @chunks = []
      @chunk_count = 0
      @finished = false
      @on_chunk_callbacks = []
      @on_finish_callbacks = []
      @on_error_callbacks = []
      @mutex = Mutex.new
      @start_time = nil
      @end_time = nil
    end

    # Register a callback for each chunk.
    #
    # @yield [StreamChunk] the chunk
    # @return [self]
    def on_chunk(&block)
      @on_chunk_callbacks << block if block
      self
    end

    # Register a callback for when streaming finishes.
    #
    # @yield [String] the full accumulated text
    # @return [self]
    def on_finish(&block)
      @on_finish_callbacks << block if block
      self
    end

    # Register a callback for errors.
    #
    # @yield [Exception] the error
    # @return [self]
    def on_error(&block)
      @on_error_callbacks << block if block
      self
    end

    # Process a chunk.
    #
    # @param chunk [StreamChunk] the chunk to process
    def <<(chunk)
      @mutex.synchronize do
        @start_time ||= Time.now
        @chunks << chunk
        @chunk_count += 1
        @buffer << chunk.text
        @finished = chunk.final?

        if @finished
          @end_time = Time.now
        end
      end

      @on_chunk_callbacks.each { |cb| cb.call(chunk) }

      if @finished
        @on_finish_callbacks.each { |cb| cb.call(@buffer) }
      end

      self
    end

    # Signal an error.
    #
    # @param error [Exception] the error
    def error(error)
      @mutex.synchronize do
        @finished = true
        @end_time = Time.now
      end

      @on_error_callbacks.each { |cb| cb.call(error) }
    end

    # Reset the accumulator.
    def reset
      @mutex.synchronize do
        @buffer = +''
        @chunks = []
        @chunk_count = 0
        @finished = false
        @start_time = nil
        @end_time = nil
      end
    end

    # Get the elapsed time in seconds.
    #
    # @return [Float, nil] elapsed time
    def elapsed_time
      return nil unless @start_time

      (@end_time || Time.now) - @start_time
    end

    # Get the average tokens per second.
    #
    # @return [Float, nil] tokens per second
    def tokens_per_second
      elapsed = elapsed_time
      return nil unless elapsed&.positive?

      @buffer.length / 4.0 / elapsed
    end

    # Get all chunks.
    #
    # @return [Array<StreamChunk>] all chunks
    def chunks
      @mutex.synchronize { @chunks.dup }
    end

    # @return [String] human-readable representation
    def inspect
      "#<#{self.class.name} chunks=#{@chunk_count} " \
        "buffer_size=#{@buffer.length} finished=#{@finished}>"
    end
  end

  # Builds streaming requests with a fluent interface.
  #
  # @example
  #   builder = Ainos::StreamBuilder.new(client)
  #   builder.model('llama3')
  #          .prompt('Hello!')
  #          .temperature(0.8)
  #          .on_chunk { |chunk| print chunk.text }
  #          .start
  class StreamBuilder
    # @return [Ainos::Client] the client
    attr_reader :client

    # @return [Hash] the request parameters
    attr_reader :params

    # @return [Ainos::StreamAccumulator, nil] the accumulator
    attr_reader :accumulator

    # Create a new stream builder.
    #
    # @param client [Ainos::Client] the client instance
    def initialize(client)
      @client = client
      @params = { stream: true }
      @accumulator = nil
      @chunk_callback = nil
      @finish_callback = nil
      @error_callback = nil
    end

    # Set the model name.
    #
    # @param model [String] the model name
    # @return [self]
    def model(model)
      @params[:model] = model
      self
    end

    # Set the prompt.
    #
    # @param prompt [String] the prompt
    # @return [self]
    def prompt(prompt)
      @params[:prompt] = prompt
      self
    end

    # Set the system prompt.
    #
    # @param system_prompt [String] the system prompt
    # @return [self]
    def system_prompt(system_prompt)
      @params[:system_prompt] = system_prompt
      self
    end

    # Set the temperature.
    #
    # @param temperature [Float] the temperature
    # @return [self]
    def temperature(temperature)
      @params[:temperature] = temperature
      self
    end

    # Set the maximum number of tokens.
    #
    # @param max_tokens [Integer] max tokens
    # @return [self]
    def max_tokens(max_tokens)
      @params[:max_tokens] = max_tokens
      self
    end

    # Set top_p.
    #
    # @param top_p [Float] the top_p value
    # @return [self]
    def top_p(top_p)
      @params[:top_p] = top_p
      self
    end

    # Set top_k.
    #
    # @param top_k [Integer] the top_k value
    # @return [self]
    def top_k(top_k)
      @params[:top_k] = top_k
      self
    end

    # Set stop sequences.
    #
    # @param stop_sequences [Array<String>] stop sequences
    # @return [self]
    def stop_sequences(stop_sequences)
      @params[:stop_sequences] = stop_sequences
      self
    end

    # Set the context ID.
    #
    # @param context_id [String] the context ID
    # @return [self]
    def context_id(context_id)
      @params[:context_id] = context_id
      self
    end

    # Set metadata.
    #
    # @param metadata [Hash] metadata
    # @return [self]
    def metadata(metadata)
      @params[:metadata] = metadata
      self
    end

    # Register a chunk callback.
    #
    # @yield [StreamChunk] the chunk
    # @return [self]
    def on_chunk(&block)
      @chunk_callback = block
      self
    end

    # Register a finish callback.
    #
    # @yield [String] the full text
    # @return [self]
    def on_finish(&block)
      @finish_callback = block
      self
    end

    # Register an error callback.
    #
    # @yield [Exception] the error
    # @return [self]
    def on_error(&block)
      @error_callback = block
      self
    end

    # Start the streaming session.
    #
    # @return [StreamSession] the stream session
    def start
      request = InferenceRequest.new(**@params)
      session = StreamSession.new(@client, request)

      if @chunk_callback || @finish_callback || @error_callback
        accumulator = StreamAccumulator.new
        accumulator.on_chunk(&@chunk_callback) if @chunk_callback
        accumulator.on_finish(&@finish_callback) if @finish_callback
        accumulator.on_error(&@error_callback) if @error_callback

        session.each_chunk { |chunk| accumulator << chunk }
      end

      session
    end

    # Collect the streaming result.
    #
    # @return [Ainos::InferenceResponse] the complete response
    def collect
      start.collect
    end
  end

  # Module methods for stream processing.
  module StreamUtils
    module_function

    # Process a stream with a sliding window of text.
    #
    # @param stream [Enumerable<StreamChunk>] the stream
    # @param window_size [Integer] the window size in characters
    # @yield [String] the sliding window text
    # @return [Enumerator] if no block given
    def sliding_window(stream, window_size: 100, &block)
      return to_enum(__method__, stream, window_size: window_size) unless block

      buffer = +''

      stream.each do |chunk|
        buffer << chunk.text

        while buffer.length > window_size
          block.call(buffer.slice!(0, window_size))
        end
      end

      block.call(buffer) unless buffer.empty?
    end

    # Filter stream chunks by a predicate.
    #
    # @param stream [Enumerable<StreamChunk>] the stream
    # @yield [StreamChunk] filter predicate
    # @return [Enumerator] the filtered stream
    def filter(stream, &block)
      Enumerator.new do |yielder|
        stream.each do |chunk|
          yielder << chunk if block.call(chunk)
        end
      end.lazy
    end

    # Map stream chunks.
    #
    # @param stream [Enumerable<StreamChunk>] the stream
    # @yield [StreamChunk] transform function
    # @return [Enumerator] the mapped stream
    def map(stream, &block)
      Enumerator.new do |yielder|
        stream.each do |chunk|
          yielder << block.call(chunk)
        end
      end.lazy
    end

    # Take a limited number of chunks from the stream.
    #
    # @param stream [Enumerable<StreamChunk>] the stream
    # @param n [Integer] number of chunks to take
    # @return [Enumerator] the limited stream
    def take(stream, n)
      Enumerator.new do |yielder|
        count = 0
        stream.each do |chunk|
          break if count >= n

          yielder << chunk
          count += 1
        end
      end.lazy
    end

    # Measure the timing of each chunk.
    #
    # @param stream [Enumerable<StreamChunk>] the stream
    # @yield [StreamChunk, Float] chunk and time since last chunk
    # @return [Enumerator] if no block given
    def with_timing(stream, &block)
      return to_enum(__method__, stream) unless block

      last_time = Time.now

      stream.each do |chunk|
        now = Time.now
        delta = now - last_time
        last_time = now
        block.call(chunk, delta)
      end
    end
  end
end