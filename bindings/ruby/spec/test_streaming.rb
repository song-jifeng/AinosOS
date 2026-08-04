# frozen_string_literal: true

require_relative 'spec_helper'

RSpec.describe Ainos::StreamSession do
  let(:mock_daemon) { MockDaemon.new }
  let(:client) do
    Ainos::Client.new(
      host: '127.0.0.1',
      port: mock_daemon.port,
      token: 'test-token',
      auto_reconnect: false,
      connection_timeout: 2.0,
      read_timeout: 5.0
    )
  end

  before(:each) do
    mock_daemon.start
    client.connect
  end

  after(:each) do
    client.disconnect rescue nil
    mock_daemon.stop rescue nil
  end

  describe '#initialize' do
    it 'creates a session with a client and request' do
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hello')
      session = described_class.new(client, request)
      expect(session.client).to eq(client)
      expect(session.request).to eq(request)
      expect(session.model).to eq('test')
    end

    it 'generates a request ID if not provided' do
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hello')
      session = described_class.new(client, request)
      expect(session.request_id).to be_a(String)
      expect(session.request_id.length).to be > 10
    end

    it 'accepts a custom request ID' do
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hello')
      session = described_class.new(client, request, request_id: 'custom-id')
      expect(session.request_id).to eq('custom-id')
    end

    it 'starts with no chunks' do
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hello')
      session = described_class.new(client, request)
      expect(session.chunks).to be_empty
      expect(session.chunk_count).to eq(0)
    end
  end

  describe '#each_chunk' do
    it 'yields each chunk to the block' do
      mock_daemon.stream_scenario(['Hello', ' ', 'World'])
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hi')
      session = described_class.new(client, request)

      chunks = []
      session.each_chunk { |chunk| chunks << chunk }
      expect(chunks.length).to eq(3)
      expect(chunks.map(&:text).join).to eq('Hello World')
    end

    it 'returns an Enumerator when no block is given' do
      mock_daemon.stream_scenario(['A', 'B'])
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hi')
      session = described_class.new(client, request)

      enum = session.each_chunk
      expect(enum).to be_a(Enumerator)
      expect(enum.map(&:text).to_a.join).to eq('AB')
    end

    it 'collects chunks in the session' do
      mock_daemon.stream_scenario(['One', 'Two'])
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hi')
      session = described_class.new(client, request)

      session.each_chunk {}
      expect(session.chunks.length).to eq(2)
      expect(session.chunk_count).to eq(2)
    end

    it 'marks the session as finished after the stream' do
      mock_daemon.stream_scenario(['X'])
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hi')
      session = described_class.new(client, request)

      session.each_chunk {}
      expect(session.finished?).to be true
    end

    it 'raises InferenceError on server error' do
      mock_daemon.on_request('infer') do |request, socket|
        mock_daemon.send(:send_error, socket, request, 'Stream failed')
      end

      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hi')
      session = described_class.new(client, request)

      expect {
        session.each_chunk { |c| }
      }.to raise_error(Ainos::InferenceError)
    end
  end

  describe '#collect' do
    it 'returns an InferenceResponse with all chunks combined' do
      mock_daemon.stream_scenario(['Hello', ' ', 'World!'])
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hi')
      session = described_class.new(client, request)

      response = session.collect
      expect(response).to be_a(Ainos::InferenceResponse)
      expect(response.text).to eq('Hello World!')
    end

    it 'returns nil if no chunks were received' do
      mock_daemon.stream_scenario([])
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hi')
      session = described_class.new(client, request)

      response = session.collect
      expect(response).to be_nil
    end

    it 'includes the finish reason from the last chunk' do
      mock_daemon.stream_scenario(['Hello'], finish_reason: 'stop')
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hi')
      session = described_class.new(client, request)

      response = session.collect
      expect(response.finish_reason).to eq('stop')
    end
  end

  describe '#process' do
    it 'calls on_chunk for each chunk' do
      mock_daemon.stream_scenario(['A', 'B', 'C'])
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hi')
      session = described_class.new(client, request)

      chunks = []
      session.process(
        on_chunk: ->(chunk) { chunks << chunk.text }
      )
      expect(chunks.join).to eq('ABC')
    end

    it 'calls on_complete with the final response' do
      mock_daemon.stream_scenario(['Test'])
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hi')
      session = described_class.new(client, request)

      final_response = nil
      session.process(
        on_complete: ->(response) { final_response = response }
      )
      expect(final_response).to be_a(Ainos::InferenceResponse)
      expect(final_response.text).to eq('Test')
    end

    it 'calls on_error when an error occurs' do
      mock_daemon.on_request('infer') do |request, socket|
        mock_daemon.send(:send_error, socket, request, 'Failed')
      end

      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hi')
      session = described_class.new(client, request)

      error_caught = nil
      session.process(
        on_error: ->(error) { error_caught = error }
      )
      expect(error_caught).to be_a(Ainos::InferenceError)
    end
  end

  describe '#cancel' do
    it 'marks the session as finished' do
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hi')
      session = described_class.new(client, request)
      session.cancel
      expect(session.finished?).to be true
    end
  end

  describe '#accumulated_text' do
    it 'returns the text accumulated so far' do
      mock_daemon.stream_scenario(['Hello', ' ', 'World'])
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hi')
      session = described_class.new(client, request)

      session.each_chunk {}
      expect(session.accumulated_text).to eq('Hello World')
    end
  end

  describe '#total_text_length' do
    it 'returns the total length of all chunk texts' do
      mock_daemon.stream_scenario(['Hello', 'World'])
      request = Ainos::InferenceRequest.new(model: 'test', prompt: 'Hi')
      session = described_class.new(client, request)

      session.each_chunk {}
      expect(session.total_text_length).to eq(10)
    end
  end
end

RSpec.describe Ainos::StreamAccumulator do
  subject(:accumulator) { described_class.new }

  describe '#initialize' do
    it 'starts with an empty buffer' do
      expect(accumulator.buffer).to be_empty
    end

    it 'starts with zero chunks' do
      expect(accumulator.chunk_count).to eq(0)
    end

    it 'is not finished' do
      expect(accumulator.finished?).to be false
    end
  end

  describe '#<<' do
    it 'appends chunk text to the buffer' do
      chunk = Ainos::StreamChunk.new(text: 'Hello')
      accumulator << chunk
      expect(accumulator.buffer).to eq('Hello')
    end

    it 'increments the chunk count' do
      expect {
        accumulator << Ainos::StreamChunk.new(text: 'A')
        accumulator << Ainos::StreamChunk.new(text: 'B')
      }.to change { accumulator.chunk_count }.from(0).to(2)
    end

    it 'marks as finished when the final chunk is added' do
      accumulator << Ainos::StreamChunk.new(text: 'Final', finished: true)
      expect(accumulator.finished?).to be true
    end

    it 'calls the on_chunk callback' do
      chunks = []
      accumulator.on_chunk { |c| chunks << c.text }
      accumulator << Ainos::StreamChunk.new(text: 'Test')
      expect(chunks).to eq(['Test'])
    end

    it 'calls the on_finish callback when finished' do
      final_text = nil
      accumulator.on_finish { |text| final_text = text }
      accumulator << Ainos::StreamChunk.new(text: 'Done', finished: true)
      expect(final_text).to eq('Done')
    end
  end

  describe '#on_chunk' do
    it 'registers a callback for each chunk' do
      callback = double('callback')
      expect(callback).to receive(:call).twice
      accumulator.on_chunk { |c| callback.call(c) }

      accumulator << Ainos::StreamChunk.new(text: 'A')
      accumulator << Ainos::StreamChunk.new(text: 'B')
    end
  end

  describe '#on_finish' do
    it 'registers a callback for completion' do
      callback = double('callback')
      expect(callback).to receive(:call).with('Final')
      accumulator.on_finish { |text| callback.call(text) }
      accumulator << Ainos::StreamChunk.new(text: 'Final', finished: true)
    end
  end

  describe '#on_error' do
    it 'registers a callback for errors' do
      error = RuntimeError.new('test error')
      callback = double('callback')
      expect(callback).to receive(:call).with(error)
      accumulator.on_error { |e| callback.call(e) }
      accumulator.error(error)
    end
  end

  describe '#error' do
    it 'marks the accumulator as finished' do
      accumulator.error(RuntimeError.new('test'))
      expect(accumulator.finished?).to be true
    end

    it 'calls the on_error callback' do
      error_caught = nil
      accumulator.on_error { |e| error_caught = e }
      accumulator.error(RuntimeError.new('test'))
      expect(error_caught).to be_a(RuntimeError)
    end
  end

  describe '#reset' do
    it 'clears the buffer' do
      accumulator << Ainos::StreamChunk.new(text: 'Data')
      accumulator.reset
      expect(accumulator.buffer).to be_empty
    end

    it 'resets the chunk count' do
      accumulator << Ainos::StreamChunk.new(text: 'A')
      accumulator.reset
      expect(accumulator.chunk_count).to eq(0)
    end

    it 'resets the finished flag' do
      accumulator << Ainos::StreamChunk.new(text: 'Done', finished: true)
      accumulator.reset
      expect(accumulator.finished?).to be false
    end
  end

  describe '#chunks' do
    it 'returns all chunks' do
      c1 = Ainos::StreamChunk.new(text: 'A')
      c2 = Ainos::StreamChunk.new(text: 'B')
      accumulator << c1 << c2
      expect(accumulator.chunks).to eq([c1, c2])
    end

    it 'returns a duplicate array' do
      accumulator << Ainos::StreamChunk.new(text: 'A')
      chunks = accumulator.chunks
      chunks << Ainos::StreamChunk.new(text: 'B')
      expect(accumulator.chunks.length).to eq(1)
    end
  end

  describe '#elapsed_time' do
    it 'returns nil before any chunks' do
      expect(accumulator.elapsed_time).to be_nil
    end

    it 'returns a positive number after receiving chunks' do
      accumulator << Ainos::StreamChunk.new(text: 'A')
      expect(accumulator.elapsed_time).to be_a(Float)
      expect(accumulator.elapsed_time).to be >= 0
    end
  end
end

RSpec.describe Ainos::StreamBuilder do
  let(:mock_daemon) { MockDaemon.new }
  let(:client) do
    Ainos::Client.new(
      host: '127.0.0.1',
      port: mock_daemon.port,
      token: 'test-token',
      auto_reconnect: false,
      connection_timeout: 2.0,
      read_timeout: 5.0
    )
  end

  before(:each) do
    mock_daemon.start
    client.connect
  end

  after(:each) do
    client.disconnect rescue nil
    mock_daemon.stop rescue nil
  end

  describe '#model' do
    it 'sets the model name' do
      builder = described_class.new(client)
      builder.model('llama3')
      expect(builder.params[:model]).to eq('llama3')
    end
  end

  describe '#prompt' do
    it 'sets the prompt' do
      builder = described_class.new(client)
      builder.prompt('Hello')
      expect(builder.params[:prompt]).to eq('Hello')
    end
  end

  describe '#temperature' do
    it 'sets the temperature' do
      builder = described_class.new(client)
      builder.temperature(0.8)
      expect(builder.params[:temperature]).to eq(0.8)
    end
  end

  describe '#max_tokens' do
    it 'sets the max tokens' do
      builder = described_class.new(client)
      builder.max_tokens(512)
      expect(builder.params[:max_tokens]).to eq(512)
    end
  end

  describe '#start' do
    it 'starts a streaming session' do
      mock_daemon.stream_scenario(['Test'])
      builder = described_class.new(client)
      builder.model('test').prompt('Hi')

      session = builder.start
      expect(session).to be_a(Ainos::StreamSession)
    end
  end

  describe '#collect' do
    it 'returns a complete response' do
      mock_daemon.stream_scenario(['Hello', ' World'])
      builder = described_class.new(client)
      builder.model('test').prompt('Hi')

      response = builder.collect
      expect(response).to be_a(Ainos::InferenceResponse)
      expect(response.text).to eq('Hello World')
    end
  end

  describe 'fluent interface' do
    it 'chains method calls' do
      builder = described_class.new(client)
      result = builder.model('test')
                      .prompt('Hello')
                      .temperature(0.8)
                      .max_tokens(256)
                      .top_p(0.95)
      expect(result).to be(builder)
      expect(builder.params[:model]).to eq('test')
      expect(builder.params[:prompt]).to eq('Hello')
      expect(builder.params[:temperature]).to eq(0.8)
      expect(builder.params[:max_tokens]).to eq(256)
      expect(builder.params[:top_p]).to eq(0.95)
    end
  end
end

RSpec.describe Ainos::StreamChunk do
  describe '#initialize' do
    it 'creates a chunk with text' do
      chunk = described_class.new(text: 'Hello')
      expect(chunk.text).to eq('Hello')
    end

    it 'defaults to not finished' do
      chunk = described_class.new(text: 'Hello')
      expect(chunk.finished?).to be false
    end

    it 'accepts a finish reason' do
      chunk = described_class.new(text: '', finished: true, finish_reason: 'stop')
      expect(chunk.finish_reason).to eq('stop')
    end

    it 'accepts an index' do
      chunk = described_class.new(text: 'Hello', index: 5)
      expect(chunk.index).to eq(5)
    end
  end

  describe '#final?' do
    it 'returns true when finished' do
      chunk = described_class.new(text: '', finished: true)
      expect(chunk.final?).to be true
    end

    it 'returns false when not finished' do
      chunk = described_class.new(text: 'Hello')
      expect(chunk.final?).to be false
    end
  end

  describe '#+' do
    it 'combines two chunks' do
      c1 = described_class.new(text: 'Hello ', index: 0)
      c2 = described_class.new(text: 'World', index: 1, finished: true, finish_reason: 'stop')
      combined = c1 + c2
      expect(combined.text).to eq('Hello World')
      expect(combined.finished?).to be true
      expect(combined.finish_reason).to eq('stop')
    end
  end
end

RSpec.describe Ainos::StreamUtils do
  describe '.sliding_window' do
    it 'yields sliding windows of text' do
      chunks = [
        Ainos::StreamChunk.new(text: 'Hello '),
        Ainos::StreamChunk.new(text: 'World')
      ]

      windows = []
      described_class.sliding_window(chunks, window_size: 5) { |w| windows << w }
      expect(windows).not_to be_empty
    end
  end

  describe '.filter' do
    it 'filters chunks by predicate' do
      chunks = [
        Ainos::StreamChunk.new(text: 'Hello'),
        Ainos::StreamChunk.new(text: ''),
        Ainos::StreamChunk.new(text: 'World')
      ]

      filtered = described_class.filter(chunks) { |c| !c.text.empty? }
      result = filtered.to_a
      expect(result.length).to eq(2)
    end
  end

  describe '.map' do
    it 'transforms chunks' do
      chunks = [
        Ainos::StreamChunk.new(text: 'hello'),
        Ainos::StreamChunk.new(text: 'world')
      ]

      mapped = described_class.map(chunks) { |c| c.text.upcase }
      expect(mapped.to_a).to eq(%w[HELLO WORLD])
    end
  end

  describe '.take' do
    it 'takes the first N chunks' do
      chunks = (1..10).map { |i| Ainos::StreamChunk.new(text: i.to_s) }
      taken = described_class.take(chunks, 3)
      expect(taken.to_a.length).to eq(3)
    end
  end

  describe '.with_timing' do
    it 'yields chunks with timing information' do
      chunks = [Ainos::StreamChunk.new(text: 'A')]
      results = []
      described_class.with_timing(chunks) { |chunk, delta| results << [chunk.text, delta] }
      expect(results.first[0]).to eq('A')
      expect(results.first[1]).to be_a(Float)
    end
  end
end