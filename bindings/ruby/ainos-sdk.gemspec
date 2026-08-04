# frozen_string_literal: true

require_relative 'lib/ainos/version'

Gem::Specification.new do |spec|
  spec.name          = 'ainos-sdk'
  spec.version       = Ainos::VERSION
  spec.authors       = ['Ainos Engineering']
  spec.email         = ['engineering@ainos.ai']

  spec.summary       = 'Ruby SDK for the Ainos inference daemon'
  spec.description   = 'A comprehensive Ruby SDK for interacting with the ' \
                       'Ainos inference daemon. Provides support for model ' \
                       'inference, streaming responses, model management, ' \
                       'server health monitoring, and context management ' \
                       'over the NDJSON-over-TCP protocol.'
  spec.homepage      = 'https://github.com/ainos/ainos-sdk-ruby'
  spec.license       = 'MIT'

  spec.required_ruby_version = '>= 3.0.0'

  spec.metadata = {
    'homepage_uri' => spec.homepage,
    'source_code_uri' => 'https://github.com/ainos/ainos-sdk-ruby',
    'changelog_uri' => 'https://github.com/ainos/ainos-sdk-ruby/blob/main/CHANGELOG.md',
    'documentation_uri' => 'https://www.rubydoc.info/gems/ainos-sdk',
    'bug_tracker_uri' => 'https://github.com/ainos/ainos-sdk-ruby/issues',
    'rubygems_mfa_required' => 'true'
  }

  spec.files = Dir.glob('lib/**/*.rb') +
               Dir.glob('spec/**/*.rb') +
               Dir.glob('examples/**/*.rb') +
               %w[
                 Gemfile
                 ainos-sdk.gemspec
                 README.md
                 LICENSE.txt
                 CHANGELOG.md
               ]

  spec.require_paths = ['lib']

  spec.bindir = 'bin'
  spec.executables = []

  # Runtime dependencies
  spec.add_dependency 'base64', '~> 0.2'

  # Development dependencies (not needed for runtime)
  spec.add_development_dependency 'rspec', '~> 3.12'
  spec.add_development_dependency 'yard', '~> 0.9'
  spec.add_development_dependency 'rake', '~> 13.0'

  spec.post_install_message = <<~MSG
    Thank you for installing the Ainos Ruby SDK!

    Get started quickly:
      require 'ainos'
      client = Ainos::Client.new(token: ENV['AINOS_TOKEN'])
      client.connect
      response = client.infer(model: 'llama3', prompt: 'Hello!')
      puts response.text
      client.disconnect

    See the README for more details.
  MSG
end