# frozen_string_literal: true

# Ainos Ruby SDK
#
# @author Ainos Engineering
module Ainos
  # Current version of the Ainos Ruby SDK.
  #
  # Follows semantic versioning (MAJOR.MINOR.PATCH):
  # - MAJOR: incompatible API changes
  # - MINOR: backward-compatible new functionality
  # - PATCH: backward-compatible bug fixes
  #
  # @example
  #   Ainos::VERSION  # => "0.1.0"
  VERSION = '0.1.0'

  # The minimum Ruby version required to run this SDK.
  MINIMUM_RUBY_VERSION = '3.0.0'

  # The default host for the Ainos daemon.
  DEFAULT_HOST = '127.0.0.1'

  # The default port for the Ainos daemon.
  DEFAULT_PORT = 9500

  # The default timeout for operations in seconds.
  DEFAULT_TIMEOUT = 30

  # The maximum number of reconnection attempts.
  MAX_RECONNECT_ATTEMPTS = 3

  # The delay between reconnection attempts in seconds.
  RECONNECT_DELAY = 1.0

  # The maximum message size in bytes (10 MB).
  MAX_MESSAGE_SIZE = 10_485_760

  # The size of the read buffer for TCP connections.
  READ_BUFFER_SIZE = 4096

  # The NDJSON delimiter character.
  NDJSON_DELIMITER = "\n"

  # The protocol version supported by this SDK.
  PROTOCOL_VERSION = '1.0.0'

  # User agent string sent with requests.
  USER_AGENT = "ainos-ruby-sdk/#{VERSION}"

  # Check if the current Ruby version meets the minimum requirement.
  #
  # @return [Boolean] true if the Ruby version is sufficient
  # @raise [RuntimeError] if the Ruby version is too old
  # @example
  #   Ainos.check_version!
  def self.check_version!
    current = RUBY_VERSION
    required = MINIMUM_RUBY_VERSION

    if current < required
      raise "Ainos SDK requires Ruby #{required} or higher (current: #{current})"
    end

    true
  end
end