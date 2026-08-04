# frozen_string_literal: true

require 'simplecov'
SimpleCov.start do
  add_filter '/spec/'
  add_filter '/examples/'
  enable_coverage :branch
  minimum_coverage 80
end

$LOAD_PATH.unshift(File.expand_path('../lib', __dir__))

require 'ainos'
require 'json'
require 'securerandom'
require 'socket'
require 'timeout'
require 'stringio'
require 'tempfile'

# Load support files
require_relative 'mock_daemon'

RSpec.configure do |config|
  # Enable color in output
  config.color = true
  config.tty = true
  config.formatter = :documentation

  # Use the expect syntax
  config.expect_with :rspec do |expectations|
    expectations.include_chain_clauses_in_custom_matcher_descriptions = true
  end

  # Mock framework
  config.mock_with :rspec do |mocks|
    mocks.verify_partial_doubles = true
  end

  # Shared context metadata
  config.shared_context_metadata_behavior = :apply_to_host_groups

  # Filter out integration tests by default
  config.filter_run_when_matching :focus
  config.run_all_when_everything_filtered = true

  # Order
  config.order = :random
  Kernel.srand config.seed

  # Clean up after each test
  config.after(:each) do
    # Clean up any temporary files
    # (implementations should clean up after themselves)
  end
end

# Helper methods for tests
module SpecHelpers
  module_function

  # Create a temporary token file for testing.
  #
  # @param token [String] the token to write
  # @return [String] the path to the temp file
  def create_token_file(token = 'test-token-12345')
    file = Tempfile.new('ainos-token')
    file.write(token)
    file.close
    file.path
  end

  # Create a mock server response JSON string.
  #
  # @param type [String] the response type
  # @param id [String] the request ID
  # @param payload [Hash] the response payload
  # @param ok [Boolean] success flag
  # @param error [String, nil] error message
  # @return [String] the JSON string
  def mock_response(type:, id:, payload: {}, ok: true, error: nil)
    response = {
      type: type,
      id: id,
      payload: payload,
      ok: ok
    }
    response[:error] = error if error
    JSON.generate(response) + "\n"
  end

  # Create a mock stream chunk JSON string.
  #
  # @param text [String] the chunk text
  # @param index [Integer] the chunk index
  # @param finished [Boolean] whether this is the final chunk
  # @param id [String] the request ID
  # @return [String] the JSON string
  def mock_stream_chunk(text:, index: 0, finished: false, id: 'test-1')
    payload = {
      text: text,
      index: index,
      finished: finished
    }
    payload[:tokens] = index * 10 + 10 if finished

    mock_response(
      type: finished ? 'stream_end' : 'stream',
      id: id,
      payload: payload
    )
  end

  # Create a mock inference request.
  #
  # @param model [String] the model name
  # @param prompt [String] the prompt
  # @param kwargs [Hash] additional options
  # @return [InferenceRequest] the request
  def mock_inference_request(model: 'test-model', prompt: 'Hello', **kwargs)
    InferenceRequest.new(model: model, prompt: prompt, **kwargs)
  end

  # Wait for a condition with timeout.
  #
  # @param timeout [Float] the timeout in seconds
  # @param interval [Float] the polling interval
  # @yield condition to check
  # @return [Boolean] whether the condition was met
  def wait_for(timeout: 5.0, interval: 0.01)
    start = Time.now
    loop do
      return true if yield
      break if Time.now - start >= timeout
      sleep(interval)
    end
    false
  end
end