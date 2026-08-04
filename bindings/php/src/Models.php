<?php

declare(strict_types=1);

namespace Ainos;

/**
 * Ainos - Data models for request/response serialization.
 *
 * All model classes use PHP 8.1+ readonly properties and named constructors
 * for immutable, type-safe data transfer objects.
 *
 * @package Ainos
 */

/**
 * Represents the completion finish reason for an inference response.
 */
enum FinishReason: string
{
    case Stop = 'stop';
    case Length = 'length';
    case ContentFilter = 'content_filter';
    case ToolCalls = 'tool_calls';
    case FunctionCall = 'function_call';
    case Error = 'error';
    case Cancelled = 'cancelled';
    case Unknown = 'unknown';

    /**
     * Create from a string value, with fallback to Unknown.
     *
     * @param string $value Raw finish reason string
     * @return self
     */
    public static function fromValue(string $value): self
    {
        return self::tryFrom($value) ?? self::Unknown;
    }

    /**
     * Check if this finish reason indicates a successful completion.
     *
     * @return bool
     */
    public function isSuccessful(): bool
    {
        return $this === self::Stop;
    }

    /**
     * Check if this finish reason indicates an error or abnormal termination.
     *
     * @return bool
     */
    public function isError(): bool
    {
        return \in_array($this, [self::Error, self::ContentFilter, self::Cancelled], true);
    }
}

/**
 * Log probability information for a token position.
 *
 * @immutable
 */
readonly class Logprobs
{
    /**
     * @param array<string> $tokens The tokens at this position
     * @param array<float> $tokenLogprobs Log probabilities of each token
     * @param array<array<string, float>>|null $topLogprobs Top alternative tokens and their log probs
     * @param array<int> $textOffset Byte offsets of each token in the original text
     */
    public function __construct(
        public array $tokens = [],
        public array $tokenLogprobs = [],
        public ?array $topLogprobs = null,
        public array $textOffset = [],
    ) {}

    /**
     * Create a Logprobs instance from an array.
     *
     * @param array $data Source data
     * @return self
     */
    public static function fromArray(array $data): self
    {
        return new self(
            tokens: (array)($data['tokens'] ?? []),
            tokenLogprobs: \array_map('floatval', (array)($data['token_logprobs'] ?? [])),
            topLogprobs: isset($data['top_logprobs']) ? (array)$data['top_logprobs'] : null,
            textOffset: \array_map('intval', (array)($data['text_offset'] ?? [])),
        );
    }

    /**
     * Convert to an array for serialization.
     *
     * @return array
     */
    public function toArray(): array
    {
        return \Ainos\Utils::arrayFilterRecursive([
            'tokens' => $this->tokens,
            'token_logprobs' => $this->tokenLogprobs,
            'top_logprobs' => $this->topLogprobs,
            'text_offset' => $this->textOffset,
        ]);
    }
}

/**
 * Token usage statistics for an inference request.
 *
 * @immutable
 */
readonly class Usage
{
    /**
     * @param int $promptTokens Number of tokens in the prompt
     * @param int $completionTokens Number of tokens in the completion
     * @param int $totalTokens Total number of tokens processed
     * @param float|null $promptTime Prompt processing time in seconds
     * @param float|null $completionTime Completion generation time in seconds
     * @param float|null $totalTime Total request time in seconds
     * @param int|null $promptTokensPerSecond Prompt tokens per second
     * @param int|null $completionTokensPerSecond Completion tokens per second
     */
    public function __construct(
        public int $promptTokens = 0,
        public int $completionTokens = 0,
        public int $totalTokens = 0,
        public ?float $promptTime = null,
        public ?float $completionTime = null,
        public ?float $totalTime = null,
        public ?int $promptTokensPerSecond = null,
        public ?int $completionTokensPerSecond = null,
    ) {}

    /**
     * Create a Usage instance from an array.
     *
     * @param array $data Source data
     * @return self
     */
    public static function fromArray(array $data): self
    {
        return new self(
            promptTokens: (int)($data['prompt_tokens'] ?? $data['promptTokens'] ?? 0),
            completionTokens: (int)($data['completion_tokens'] ?? $data['completionTokens'] ?? 0),
            totalTokens: (int)($data['total_tokens'] ?? $data['totalTokens'] ?? 0),
            promptTime: isset($data['prompt_time']) ? (float)$data['prompt_time'] : (isset($data['promptTime']) ? (float)$data['promptTime'] : null),
            completionTime: isset($data['completion_time']) ? (float)$data['completion_time'] : (isset($data['completionTime']) ? (float)$data['completionTime'] : null),
            totalTime: isset($data['total_time']) ? (float)$data['total_time'] : (isset($data['totalTime']) ? (float)$data['totalTime'] : null),
            promptTokensPerSecond: isset($data['prompt_tokens_per_second']) ? (int)$data['prompt_tokens_per_second'] : (isset($data['promptTokensPerSecond']) ? (int)$data['promptTokensPerSecond'] : null),
            completionTokensPerSecond: isset($data['completion_tokens_per_second']) ? (int)$data['completion_tokens_per_second'] : (isset($data['completionTokensPerSecond']) ? (int)$data['completionTokensPerSecond'] : null),
        );
    }

    /**
     * Convert to an array for serialization.
     *
     * @return array
     */
    public function toArray(): array
    {
        return \Ainos\Utils::arrayFilterRecursive([
            'prompt_tokens' => $this->promptTokens,
            'completion_tokens' => $this->completionTokens,
            'total_tokens' => $this->totalTokens,
            'prompt_time' => $this->promptTime,
            'completion_time' => $this->completionTime,
            'total_time' => $this->totalTime,
            'prompt_tokens_per_second' => $this->promptTokensPerSecond,
            'completion_tokens_per_second' => $this->completionTokensPerSecond,
        ]);
    }

    /**
     * Calculate and return tokens per second for the completion.
     *
     * @return float|null
     */
    public function getCompletionTokensPerSecond(): ?float
    {
        if ($this->completionTokensPerSecond !== null) {
            return (float)$this->completionTokensPerSecond;
        }

        if ($this->completionTokens > 0 && $this->completionTime !== null && $this->completionTime > 0) {
            return $this->completionTokens / $this->completionTime;
        }

        return null;
    }

    /**
     * Calculate and return tokens per second for the prompt.
     *
     * @return float|null
     */
    public function getPromptTokensPerSecond(): ?float
    {
        if ($this->promptTokensPerSecond !== null) {
            return (float)$this->promptTokensPerSecond;
        }

        if ($this->promptTokens > 0 && $this->promptTime !== null && $this->promptTime > 0) {
            return $this->promptTokens / $this->promptTime;
        }

        return null;
    }

    /**
     * Create a Usage instance from two Usage instances (sum).
     *
     * @param self $a First usage
     * @param self $b Second usage
     * @return self
     */
    public static function sum(self $a, self $b): self
    {
        return new self(
            promptTokens: $a->promptTokens + $b->promptTokens,
            completionTokens: $a->completionTokens + $b->completionTokens,
            totalTokens: $a->totalTokens + $b->totalTokens,
        );
    }

    /**
     * Get the cost ratio (completion tokens / prompt tokens).
     *
     * @return float|null
     */
    public function getRatio(): ?float
    {
        if ($this->promptTokens === 0) {
            return null;
        }

        return $this->completionTokens / $this->promptTokens;
    }
}

/**
 * Inference parameters for controlling model generation.
 *
 * @immutable
 */
readonly class Parameters
{
    /**
     * @param float|null $temperature Sampling temperature (0.0-2.0, default 0.7)
     * @param float|null $topP Nucleus sampling threshold (0.0-1.0, default 0.9)
     * @param int|null $topK Top-K sampling (default 40)
     * @param int|null $maxTokens Maximum tokens to generate (default 2048)
     * @param int|null $maxInputTokens Maximum input tokens to process (default 4096)
     * @param array<string>|null $stop Stop sequences
     * @param float|null $presencePenalty Presence penalty (-2.0 to 2.0)
     * @param float|null $frequencyPenalty Frequency penalty (-2.0 to 2.0)
     * @param float|null $repeatPenalty Repetition penalty (1.0-2.0)
     * @param int|null $seed Random seed for reproducibility
     * @param bool|null $mirostat Enable Mirostat sampling
     * @param float|null $mirostatTau Mirostat tau (learning rate, default 5.0)
     * @param float|null $mirostatEta Mirostat eta (entropy target, default 0.1)
     * @param bool|null $logprobs Return log probabilities
     * @param int|null $topLogprobs Number of top logprobs to return (if logprobs is true)
     * @param bool|null $echo Echo the prompt in the response
     * @param int|null $n Number of completions to generate
     * @param float|null $minP Minimum probability for min-p sampling
     * @param float|null $typicalP Typical probability for typical sampling
     * @param float|null $tfsZ Tail-free sampling Z value
     * @param array|null $logitBias Token ID to bias mapping
     * @param string|null $grammar BNF grammar for constrained generation
     * @param string|null $grammarType Grammar type (e.g., 'gbnf')
     * @param array|null $stopTokenIds Token IDs to use as stop tokens
     * @param bool|null $ignoreEos Ignore end-of-sequence token
     * @param int|null $minTokens Minimum tokens to generate
     */
    public function __construct(
        public ?float $temperature = null,
        public ?float $topP = null,
        public ?int $topK = null,
        public ?int $maxTokens = null,
        public ?int $maxInputTokens = null,
        public ?array $stop = null,
        public ?float $presencePenalty = null,
        public ?float $frequencyPenalty = null,
        public ?float $repeatPenalty = null,
        public ?int $seed = null,
        public ?bool $mirostat = null,
        public ?float $mirostatTau = null,
        public ?float $mirostatEta = null,
        public ?bool $logprobs = null,
        public ?int $topLogprobs = null,
        public ?bool $echo = null,
        public ?int $n = null,
        public ?float $minP = null,
        public ?float $typicalP = null,
        public ?float $tfsZ = null,
        public ?array $logitBias = null,
        public ?string $grammar = null,
        public ?string $grammarType = null,
        public ?array $stopTokenIds = null,
        public ?bool $ignoreEos = null,
        public ?int $minTokens = null,
    ) {}

    /**
     * Default inference parameters.
     *
     * @return self
     */
    public static function defaults(): self
    {
        return new self(
            temperature: 0.7,
            topP: 0.9,
            topK: 40,
            maxTokens: 2048,
            maxInputTokens: 4096,
            stop: [],
            presencePenalty: 0.0,
            frequencyPenalty: 0.0,
            repeatPenalty: 1.0,
            logprobs: false,
            echo: false,
            n: 1,
        );
    }

    /**
     * Create a Parameters instance from an array.
     *
     * @param array $data Source data
     * @return self
     */
    public static function fromArray(array $data): self
    {
        return new self(
            temperature: isset($data['temperature']) ? (float)$data['temperature'] : null,
            topP: isset($data['top_p']) ? (float)$data['top_p'] : (isset($data['topP']) ? (float)$data['topP'] : null),
            topK: isset($data['top_k']) ? (int)$data['top_k'] : (isset($data['topK']) ? (int)$data['topK'] : null),
            maxTokens: isset($data['max_tokens']) ? (int)$data['max_tokens'] : (isset($data['maxTokens']) ? (int)$data['maxTokens'] : null),
            maxInputTokens: isset($data['max_input_tokens']) ? (int)$data['max_input_tokens'] : (isset($data['maxInputTokens']) ? (int)$data['maxInputTokens'] : null),
            stop: isset($data['stop']) ? (array)$data['stop'] : null,
            presencePenalty: isset($data['presence_penalty']) ? (float)$data['presence_penalty'] : (isset($data['presencePenalty']) ? (float)$data['presencePenalty'] : null),
            frequencyPenalty: isset($data['frequency_penalty']) ? (float)$data['frequency_penalty'] : (isset($data['frequencyPenalty']) ? (float)$data['frequencyPenalty'] : null),
            repeatPenalty: isset($data['repeat_penalty']) ? (float)$data['repeat_penalty'] : (isset($data['repeatPenalty']) ? (float)$data['repeatPenalty'] : null),
            seed: isset($data['seed']) ? (int)$data['seed'] : null,
            mirostat: isset($data['mirostat']) ? (bool)$data['mirostat'] : null,
            mirostatTau: isset($data['mirostat_tau']) ? (float)$data['mirostat_tau'] : (isset($data['mirostatTau']) ? (float)$data['mirostatTau'] : null),
            mirostatEta: isset($data['mirostat_eta']) ? (float)$data['mirostat_eta'] : (isset($data['mirostatEta']) ? (float)$data['mirostatEta'] : null),
            logprobs: isset($data['logprobs']) ? (bool)$data['logprobs'] : null,
            topLogprobs: isset($data['top_logprobs']) ? (int)$data['top_logprobs'] : (isset($data['topLogprobs']) ? (int)$data['topLogprobs'] : null),
            echo: isset($data['echo']) ? (bool)$data['echo'] : null,
            n: isset($data['n']) ? (int)$data['n'] : null,
            minP: isset($data['min_p']) ? (float)$data['min_p'] : (isset($data['minP']) ? (float)$data['minP'] : null),
            typicalP: isset($data['typical_p']) ? (float)$data['typical_p'] : (isset($data['typicalP']) ? (float)$data['typicalP'] : null),
            tfsZ: isset($data['tfs_z']) ? (float)$data['tfs_z'] : (isset($data['tfsZ']) ? (float)$data['tfsZ'] : null),
            logitBias: isset($data['logit_bias']) ? (array)$data['logit_bias'] : (isset($data['logitBias']) ? (array)$data['logitBias'] : null),
            grammar: isset($data['grammar']) ? (string)$data['grammar'] : null,
            grammarType: isset($data['grammar_type']) ? (string)$data['grammar_type'] : (isset($data['grammarType']) ? (string)$data['grammarType'] : null),
            stopTokenIds: isset($data['stop_token_ids']) ? (array)$data['stop_token_ids'] : (isset($data['stopTokenIds']) ? (array)$data['stopTokenIds'] : null),
            ignoreEos: isset($data['ignore_eos']) ? (bool)$data['ignore_eos'] : (isset($data['ignoreEos']) ? (bool)$data['ignoreEos'] : null),
            minTokens: isset($data['min_tokens']) ? (int)$data['min_tokens'] : (isset($data['minTokens']) ? (int)$data['minTokens'] : null),
        );
    }

    /**
     * Merge with other parameters (non-null values override).
     *
     * @param self $other Parameters to merge
     * @return self
     */
    public function merge(self $other): self
    {
        return new self(
            temperature: $other->temperature ?? $this->temperature,
            topP: $other->topP ?? $this->topP,
            topK: $other->topK ?? $this->topK,
            maxTokens: $other->maxTokens ?? $this->maxTokens,
            maxInputTokens: $other->maxInputTokens ?? $this->maxInputTokens,
            stop: $other->stop ?? $this->stop,
            presencePenalty: $other->presencePenalty ?? $this->presencePenalty,
            frequencyPenalty: $other->frequencyPenalty ?? $this->frequencyPenalty,
            repeatPenalty: $other->repeatPenalty ?? $this->repeatPenalty,
            seed: $other->seed ?? $this->seed,
            mirostat: $other->mirostat ?? $this->mirostat,
            mirostatTau: $other->mirostatTau ?? $this->mirostatTau,
            mirostatEta: $other->mirostatEta ?? $this->mirostatEta,
            logprobs: $other->logprobs ?? $this->logprobs,
            topLogprobs: $other->topLogprobs ?? $this->topLogprobs,
            echo: $other->echo ?? $this->echo,
            n: $other->n ?? $this->n,
            minP: $other->minP ?? $this->minP,
            typicalP: $other->typicalP ?? $this->typicalP,
            tfsZ: $other->tfsZ ?? $this->tfsZ,
            logitBias: $other->logitBias ?? $this->logitBias,
            grammar: $other->grammar ?? $this->grammar,
            grammarType: $other->grammarType ?? $this->grammarType,
            stopTokenIds: $other->stopTokenIds ?? $this->stopTokenIds,
            ignoreEos: $other->ignoreEos ?? $this->ignoreEos,
            minTokens: $other->minTokens ?? $this->minTokens,
        );
    }

    /**
     * Convert to an array for serialization, omitting null values.
     *
     * @return array
     */
    public function toArray(): array
    {
        return \Ainos\Utils::arrayFilterRecursive([
            'temperature' => $this->temperature,
            'top_p' => $this->topP,
            'top_k' => $this->topK,
            'max_tokens' => $this->maxTokens,
            'max_input_tokens' => $this->maxInputTokens,
            'stop' => $this->stop,
            'presence_penalty' => $this->presencePenalty,
            'frequency_penalty' => $this->frequencyPenalty,
            'repeat_penalty' => $this->repeatPenalty,
            'seed' => $this->seed,
            'mirostat' => $this->mirostat,
            'mirostat_tau' => $this->mirostatTau,
            'mirostat_eta' => $this->mirostatEta,
            'logprobs' => $this->logprobs,
            'top_logprobs' => $this->topLogprobs,
            'echo' => $this->echo,
            'n' => $this->n,
            'min_p' => $this->minP,
            'typical_p' => $this->typicalP,
            'tfs_z' => $this->tfsZ,
            'logit_bias' => $this->logitBias,
            'grammar' => $this->grammar,
            'grammar_type' => $this->grammarType,
            'stop_token_ids' => $this->stopTokenIds,
            'ignore_eos' => $this->ignoreEos,
            'min_tokens' => $this->minTokens,
        ]);
    }

    /**
     * Validate parameters and throw if any are out of range.
     *
     * @return self
     * @throws \Ainos\InvalidRequestException
     */
    public function validate(): self
    {
        if ($this->temperature !== null) {
            \Ainos\Utils::assertRange('temperature', $this->temperature, 0.0, 2.0);
        }

        if ($this->topP !== null) {
            \Ainos\Utils::assertRange('top_p', $this->topP, 0.0, 1.0);
        }

        if ($this->topK !== null) {
            \Ainos\Utils::assertRange('top_k', $this->topK, 1, 1000);
        }

        if ($this->maxTokens !== null) {
            \Ainos\Utils::assertRange('max_tokens', $this->maxTokens, 1, 1000000);
        }

        if ($this->maxInputTokens !== null) {
            \Ainos\Utils::assertRange('max_input_tokens', $this->maxInputTokens, 1, 1000000);
        }

        if ($this->presencePenalty !== null) {
            \Ainos\Utils::assertRange('presence_penalty', $this->presencePenalty, -2.0, 2.0);
        }

        if ($this->frequencyPenalty !== null) {
            \Ainos\Utils::assertRange('frequency_penalty', $this->frequencyPenalty, -2.0, 2.0);
        }

        if ($this->repeatPenalty !== null) {
            \Ainos\Utils::assertRange('repeat_penalty', $this->repeatPenalty, 0.0, 2.0);
        }

        if ($this->n !== null) {
            \Ainos\Utils::assertRange('n', $this->n, 1, 100);
        }

        if ($this->minP !== null) {
            \Ainos\Utils::assertRange('min_p', $this->minP, 0.0, 1.0);
        }

        if ($this->typicalP !== null) {
            \Ainos\Utils::assertRange('typical_p', $this->typicalP, 0.0, 1.0);
        }

        if ($this->tfsZ !== null) {
            \Ainos\Utils::assertRange('tfs_z', $this->tfsZ, 0.0, 1.0);
        }

        return $this;
    }
}

/**
 * Represents a single completion choice in an inference response.
 *
 * @immutable
 */
readonly class Choice
{
    /**
     * @param int $index Choice index
     * @param string $text Generated text
     * @param FinishReason $finishReason Reason the generation finished
     * @param \Ainos\Logprobs|null $logprobs Log probability information
     */
    public function __construct(
        public int $index = 0,
        public string $text = '',
        public FinishReason $finishReason = FinishReason::Stop,
        public ?Logprobs $logprobs = null,
    ) {}

    /**
     * Create a Choice instance from an array.
     *
     * @param array $data Source data
     * @return self
     */
    public static function fromArray(array $data): self
    {
        return new self(
            index: (int)($data['index'] ?? 0),
            text: (string)($data['text'] ?? $data['content'] ?? ''),
            finishReason: FinishReason::fromValue((string)($data['finish_reason'] ?? $data['finishReason'] ?? 'unknown')),
            logprobs: isset($data['logprobs']) ? Logprobs::fromArray((array)$data['logprobs']) : null,
        );
    }

    /**
     * Convert to an array for serialization.
     *
     * @return array
     */
    public function toArray(): array
    {
        return \Ainos\Utils::arrayFilterRecursive([
            'index' => $this->index,
            'text' => $this->text,
            'finish_reason' => $this->finishReason->value,
            'logprobs' => $this->logprobs?->toArray(),
        ]);
    }
}

/**
 * Inference response from the Ainos server.
 *
 * @immutable
 */
readonly class InferenceResponse
{
    /**
     * @param string $id Unique response identifier
     * @param string $model Model used for inference
     * @param array<Choice> $choices Generated completion choices
     * @param \Ainos\Usage $usage Token usage statistics
     * @param int $created Unix timestamp of response creation
     * @param array|null $context Context data returned from the server
     * @param string|null $object Response object type
     */
    public function __construct(
        public string $id = '',
        public string $model = '',
        public array $choices = [],
        public Usage $usage = new Usage(),
        public int $created = 0,
        public ?array $context = null,
        public ?string $object = 'text_completion',
    ) {}

    /**
     * Create an InferenceResponse instance from an array.
     *
     * @param array $data Source data
     * @return self
     */
    public static function fromArray(array $data): self
    {
        $choices = [];
        foreach ((array)($data['choices'] ?? []) as $choiceData) {
            $choices[] = Choice::fromArray((array)$choiceData);
        }

        return new self(
            id: (string)($data['id'] ?? ''),
            model: (string)($data['model'] ?? ''),
            choices: $choices,
            usage: Usage::fromArray((array)($data['usage'] ?? [])),
            created: (int)($data['created'] ?? \time()),
            context: isset($data['context']) ? (array)$data['context'] : null,
            object: isset($data['object']) ? (string)$data['object'] : 'text_completion',
        );
    }

    /**
     * Get the primary generated text (first choice).
     *
     * @return string Generated text, or empty string if no choices
     */
    public function getText(): string
    {
        return $this->choices[0]->text ?? '';
    }

    /**
     * Get the finish reason of the first choice.
     *
     * @return FinishReason|null
     */
    public function getFinishReason(): ?FinishReason
    {
        return $this->choices[0]->finishReason ?? null;
    }

    /**
     * Check if the response completed successfully.
     *
     * @return bool
     */
    public function isComplete(): bool
    {
        return $this->getFinishReason() === FinishReason::Stop;
    }

    /**
     * Convert to an array for serialization.
     *
     * @return array
     */
    public function toArray(): array
    {
        return \Ainos\Utils::arrayFilterRecursive([
            'id' => $this->id,
            'model' => $this->model,
            'choices' => \array_map(fn(Choice $c) => $c->toArray(), $this->choices),
            'usage' => $this->usage->toArray(),
            'created' => $this->created,
            'context' => $this->context,
            'object' => $this->object,
        ]);
    }
}

/**
 * Streaming chunk received during streaming inference.
 *
 * @immutable
 */
readonly class StreamChunk
{
    /**
     * @param string $id Request identifier
     * @param string $model Model used for inference
     * @param string $text Text delta for this chunk
     * @param int $index Choice index
     * @param FinishReason|null $finishReason Finish reason (only on last chunk)
     * @param \Ainos\Usage|null $usage Usage statistics (only on last chunk)
     * @param bool $isEnd Whether this is the final chunk
     * @param int $created Unix timestamp
     */
    public function __construct(
        public string $id = '',
        public string $model = '',
        public string $text = '',
        public int $index = 0,
        public ?FinishReason $finishReason = null,
        public ?Usage $usage = null,
        public bool $isEnd = false,
        public int $created = 0,
    ) {}

    /**
     * Create a StreamChunk instance from an array.
     *
     * @param array $data Source data
     * @return self
     */
    public static function fromArray(array $data): self
    {
        return new self(
            id: (string)($data['id'] ?? ''),
            model: (string)($data['model'] ?? ''),
            text: (string)($data['text'] ?? $data['content'] ?? $data['delta'] ?? ''),
            index: (int)($data['index'] ?? 0),
            finishReason: isset($data['finish_reason']) ? FinishReason::fromValue((string)$data['finish_reason']) : (isset($data['finishReason']) ? FinishReason::fromValue((string)$data['finishReason']) : null),
            usage: isset($data['usage']) ? Usage::fromArray((array)$data['usage']) : null,
            isEnd: (bool)($data['end'] ?? $data['is_end'] ?? $data['isEnd'] ?? false),
            created: (int)($data['created'] ?? \time()),
        );
    }

    /**
     * Convert to an array for serialization.
     *
     * @return array
     */
    public function toArray(): array
    {
        return \Ainos\Utils::arrayFilterRecursive([
            'id' => $this->id,
            'model' => $this->model,
            'text' => $this->text,
            'index' => $this->index,
            'finish_reason' => $this->finishReason?->value,
            'usage' => $this->usage?->toArray(),
            'end' => $this->isEnd,
            'created' => $this->created,
        ]);
    }

    /**
     * Create a StreamChunk that signals the end of a stream.
     *
     * @param string $id Request identifier
     * @param string $model Model name
     * @param \Ainos\Usage|null $usage Final usage statistics
     * @return self
     */
    public static function end(string $id, string $model, ?Usage $usage = null): self
    {
        return new self(
            id: $id,
            model: $model,
            isEnd: true,
            usage: $usage,
            finishReason: FinishReason::Stop,
        );
    }
}

/**
 * Information about a loaded model.
 *
 * @immutable
 */
readonly class ModelInfo
{
    /**
     * @param string $name Model name
     * @param string $id Model identifier
     * @param string $path Filesystem path to the model file
     * @param int $size Model file size in bytes
     * @param bool $loaded Whether the model is currently loaded in memory
     * @param array $metadata Additional metadata (architecture, quantization, etc.)
     * @param int|null $modifiedAt Unix timestamp of last modification
     * @param int|null $loadedAt Unix timestamp when the model was loaded
     * @param string|null $version Model version
     * @param string|null $description Model description
     * @param string|null $license Model license
     * @param string|null $author Model author
     */
    public function __construct(
        public string $name = '',
        public string $id = '',
        public string $path = '',
        public int $size = 0,
        public bool $loaded = false,
        public array $metadata = [],
        public ?int $modifiedAt = null,
        public ?int $loadedAt = null,
        public ?string $version = null,
        public ?string $description = null,
        public ?string $license = null,
        public ?string $author = null,
    ) {}

    /**
     * Create a ModelInfo instance from an array.
     *
     * @param array $data Source data
     * @return self
     */
    public static function fromArray(array $data): self
    {
        return new self(
            name: (string)($data['name'] ?? ''),
            id: (string)($data['id'] ?? $data['model'] ?? ''),
            path: (string)($data['path'] ?? ''),
            size: (int)($data['size'] ?? 0),
            loaded: (bool)($data['loaded'] ?? false),
            metadata: (array)($data['metadata'] ?? []),
            modifiedAt: isset($data['modified_at']) ? (int)$data['modified_at'] : (isset($data['modifiedAt']) ? (int)$data['modifiedAt'] : null),
            loadedAt: isset($data['loaded_at']) ? (int)$data['loaded_at'] : (isset($data['loadedAt']) ? (int)$data['loadedAt'] : null),
            version: isset($data['version']) ? (string)$data['version'] : null,
            description: isset($data['description']) ? (string)$data['description'] : null,
            license: isset($data['license']) ? (string)$data['license'] : null,
            author: isset($data['author']) ? (string)$data['author'] : null,
        );
    }

    /**
     * Convert to an array for serialization.
     *
     * @return array
     */
    public function toArray(): array
    {
        return \Ainos\Utils::arrayFilterRecursive([
            'name' => $this->name,
            'id' => $this->id,
            'path' => $this->path,
            'size' => $this->size,
            'loaded' => $this->loaded,
            'metadata' => $this->metadata,
            'modified_at' => $this->modifiedAt,
            'loaded_at' => $this->loadedAt,
            'version' => $this->version,
            'description' => $this->description,
            'license' => $this->license,
            'author' => $this->author,
        ]);
    }

    /**
     * Get the model size as a human-readable string.
     *
     * @param int $precision Number of decimal places
     * @return string
     */
    public function getSizeFormatted(int $precision = 2): string
    {
        return \Ainos\Utils::formatBytes($this->size, $precision);
    }
}

/**
 * A list of models available on the server.
 *
 * @immutable
 */
readonly class ModelList
{
    /**
     * @param array<ModelInfo> $models Available models
     * @param int $total Total number of models
     * @param int $loadedCount Number of loaded models
     * @param int $totalSize Total size of all models in bytes
     */
    public function __construct(
        public array $models = [],
        public int $total = 0,
        public int $loadedCount = 0,
        public int $totalSize = 0,
    ) {}

    /**
     * Create a ModelList instance from an array.
     *
     * @param array $data Source data
     * @return self
     */
    public static function fromArray(array $data): self
    {
        $models = [];
        foreach ((array)($data['models'] ?? $data['data'] ?? []) as $modelData) {
            $models[] = ModelInfo::fromArray((array)$modelData);
        }

        return new self(
            models: $models,
            total: (int)($data['total'] ?? \count($models)),
            loadedCount: (int)($data['loaded_count'] ?? $data['loadedCount'] ?? 0),
            totalSize: (int)($data['total_size'] ?? $data['totalSize'] ?? 0),
        );
    }

    /**
     * Convert to an array for serialization.
     *
     * @return array
     */
    public function toArray(): array
    {
        return [
            'models' => \array_map(fn(ModelInfo $m) => $m->toArray(), $this->models),
            'total' => $this->total,
            'loaded_count' => $this->loadedCount,
            'total_size' => $this->totalSize,
        ];
    }

    /**
     * Get a model by name.
     *
     * @param string $name Model name to find
     * @return ModelInfo|null
     */
    public function getByName(string $name): ?ModelInfo
    {
        foreach ($this->models as $model) {
            if ($model->name === $name) {
                return $model;
            }
        }

        return null;
    }

    /**
     * Get only loaded models.
     *
     * @return array<ModelInfo>
     */
    public function getLoaded(): array
    {
        return \array_values(
            \array_filter($this->models, fn(ModelInfo $m) => $m->loaded)
        );
    }

    /**
     * Get model names as an array of strings.
     *
     * @return array<string>
     */
    public function getNames(): array
    {
        return \array_map(fn(ModelInfo $m) => $m->name, $this->models);
    }

    /**
     * Check if a specific model is available.
     *
     * @param string $name Model name to check
     * @return bool
     */
    public function has(string $name): bool
    {
        return $this->getByName($name) !== null;
    }
}

/**
 * Server health status.
 *
 * @immutable
 */
readonly class HealthStatus
{
    /**
     * @param string $status Overall health status ('healthy', 'degraded', 'unhealthy')
     * @param float $uptime Server uptime in seconds
     * @param string $version Server version string
     * @param array $memory Memory usage statistics
     * @param int $activeConnections Number of active connections
     * @param int $startTime Unix timestamp when the server started
     * @param array|null $checks Individual health check results
     */
    public function __construct(
        public string $status = 'unknown',
        public float $uptime = 0.0,
        public string $version = '',
        public array $memory = [],
        public int $activeConnections = 0,
        public int $startTime = 0,
        public ?array $checks = null,
    ) {}

    /**
     * Create a HealthStatus instance from an array.
     *
     * @param array $data Source data
     * @return self
     */
    public static function fromArray(array $data): self
    {
        return new self(
            status: (string)($data['status'] ?? 'unknown'),
            uptime: (float)($data['uptime'] ?? 0.0),
            version: (string)($data['version'] ?? ''),
            memory: (array)($data['memory'] ?? []),
            activeConnections: (int)($data['active_connections'] ?? $data['activeConnections'] ?? 0),
            startTime: (int)($data['start_time'] ?? $data['startTime'] ?? 0),
            checks: isset($data['checks']) ? (array)$data['checks'] : null,
        );
    }

    /**
     * Convert to an array for serialization.
     *
     * @return array
     */
    public function toArray(): array
    {
        return \Ainos\Utils::arrayFilterRecursive([
            'status' => $this->status,
            'uptime' => $this->uptime,
            'version' => $this->version,
            'memory' => $this->memory,
            'active_connections' => $this->activeConnections,
            'start_time' => $this->startTime,
            'checks' => $this->checks,
        ]);
    }

    /**
     * Check if the server is healthy.
     *
     * @return bool
     */
    public function isHealthy(): bool
    {
        return $this->status === 'healthy';
    }

    /**
     * Get uptime as a human-readable string.
     *
     * @return string
     */
    public function getUptimeFormatted(): string
    {
        $seconds = (int)$this->uptime;

        $days = (int)($seconds / 86400);
        $seconds %= 86400;
        $hours = (int)($seconds / 3600);
        $seconds %= 3600;
        $minutes = (int)($seconds / 60);
        $seconds %= 60;

        $parts = [];
        if ($days > 0) { $parts[] = "{$days}d"; }
        if ($hours > 0) { $parts[] = "{$hours}h"; }
        if ($minutes > 0) { $parts[] = "{$minutes}m"; }
        $parts[] = "{$seconds}s";

        return \implode(' ', $parts);
    }
}

/**
 * Detailed server status information.
 *
 * @immutable
 */
readonly class ServerStatus
{
    /**
     * @param string $version Server version
     * @param int $uptime Server uptime in seconds
     * @param array<string> $activeModels List of currently loaded model names
     * @param int $totalRequests Total requests processed since server start
     * @param array $memory Memory usage details
     * @param float|null $cpuAverage CPU usage average
     * @param int $activeConnections Current active connections
     * @param int $startTime Unix timestamp when the server started
     * @param array $config Server configuration
     * @param array $hardware Hardware information (GPU, CPU, etc.)
     * @param array $stats Additional statistics
     */
    public function __construct(
        public string $version = '',
        public int $uptime = 0,
        public array $activeModels = [],
        public int $totalRequests = 0,
        public array $memory = [],
        public ?float $cpuAverage = null,
        public int $activeConnections = 0,
        public int $startTime = 0,
        public array $config = [],
        public array $hardware = [],
        public array $stats = [],
    ) {}

    /**
     * Create a ServerStatus instance from an array.
     *
     * @param array $data Source data
     * @return self
     */
    public static function fromArray(array $data): self
    {
        return new self(
            version: (string)($data['version'] ?? ''),
            uptime: (int)($data['uptime'] ?? 0),
            activeModels: (array)($data['active_models'] ?? $data['activeModels'] ?? []),
            totalRequests: (int)($data['total_requests'] ?? $data['totalRequests'] ?? 0),
            memory: (array)($data['memory'] ?? []),
            cpuAverage: isset($data['cpu_average']) ? (float)$data['cpu_average'] : (isset($data['cpuAverage']) ? (float)$data['cpuAverage'] : null),
            activeConnections: (int)($data['active_connections'] ?? $data['activeConnections'] ?? 0),
            startTime: (int)($data['start_time'] ?? $data['startTime'] ?? 0),
            config: (array)($data['config'] ?? []),
            hardware: (array)($data['hardware'] ?? []),
            stats: (array)($data['stats'] ?? []),
        );
    }

    /**
     * Convert to an array for serialization.
     *
     * @return array
     */
    public function toArray(): array
    {
        return \Ainos\Utils::arrayFilterRecursive([
            'version' => $this->version,
            'uptime' => $this->uptime,
            'active_models' => $this->activeModels,
            'total_requests' => $this->totalRequests,
            'memory' => $this->memory,
            'cpu_average' => $this->cpuAverage,
            'active_connections' => $this->activeConnections,
            'start_time' => $this->startTime,
            'config' => $this->config,
            'hardware' => $this->hardware,
            'stats' => $this->stats,
        ]);
    }
}

/**
 * A context entry stored on the server.
 *
 * @immutable
 */
readonly class ContextEntry
{
    /**
     * @param string $id Context entry identifier
     * @param string $key Context key
     * @param mixed $value Context value
     * @param int $ttl Time-to-live in seconds
     * @param int $createdAt Unix timestamp when the entry was created
     * @param int|null $expiresAt Unix timestamp when the entry expires
     * @param int|null $lastAccessedAt Unix timestamp of last access
     * @param int|null $accessCount Number of times the entry has been accessed
     */
    public function __construct(
        public string $id = '',
        public string $key = '',
        public mixed $value = null,
        public int $ttl = 3600,
        public int $createdAt = 0,
        public ?int $expiresAt = null,
        public ?int $lastAccessedAt = null,
        public ?int $accessCount = null,
    ) {}

    /**
     * Create a ContextEntry instance from an array.
     *
     * @param array $data Source data
     * @return self
     */
    public static function fromArray(array $data): self
    {
        return new self(
            id: (string)($data['id'] ?? ''),
            key: (string)($data['key'] ?? ''),
            value: $data['value'] ?? null,
            ttl: (int)($data['ttl'] ?? 3600),
            createdAt: (int)($data['created_at'] ?? $data['createdAt'] ?? \time()),
            expiresAt: isset($data['expires_at']) ? (int)$data['expires_at'] : (isset($data['expiresAt']) ? (int)$data['expiresAt'] : null),
            lastAccessedAt: isset($data['last_accessed_at']) ? (int)$data['last_accessed_at'] : (isset($data['lastAccessedAt']) ? (int)$data['lastAccessedAt'] : null),
            accessCount: isset($data['access_count']) ? (int)$data['access_count'] : (isset($data['accessCount']) ? (int)$data['accessCount'] : null),
        );
    }

    /**
     * Convert to an array for serialization.
     *
     * @return array
     */
    public function toArray(): array
    {
        return \Ainos\Utils::arrayFilterRecursive([
            'id' => $this->id,
            'key' => $this->key,
            'value' => $this->value,
            'ttl' => $this->ttl,
            'created_at' => $this->createdAt,
            'expires_at' => $this->expiresAt,
            'last_accessed_at' => $this->lastAccessedAt,
            'access_count' => $this->accessCount,
        ]);
    }

    /**
     * Check if the context entry has expired.
     *
     * @return bool
     */
    public function isExpired(): bool
    {
        if ($this->expiresAt === null) {
            return false;
        }

        return \time() > $this->expiresAt;
    }

    /**
     * Get the remaining time-to-live in seconds.
     *
     * @return int|null Seconds remaining, or null if no expiry
     */
    public function getRemainingTtl(): ?int
    {
        if ($this->expiresAt === null) {
            return null;
        }

        return \max(0, $this->expiresAt - \time());
    }
}

/**
 * Request envelope for sending commands to the Ainos server.
 *
 * @immutable
 */
readonly class RequestEnvelope
{
    /**
     * @param string $method RPC method name
     * @param array $params Method parameters
     * @param string $id Request identifier
     * @param string|null $token Authentication token (optional, can be set via headers)
     */
    public function __construct(
        public string $method = '',
        public array $params = [],
        public string $id = '',
        public ?string $token = null,
    ) {}

    /**
     * Create a RequestEnvelope from method and parameters.
     *
     * @param string $method RPC method name
     * @param array $params Method parameters
     * @param string|null $id Optional request ID (auto-generated if null)
     * @return self
     */
    public static function create(string $method, array $params = [], ?string $id = null): self
    {
        return new self(
            method: $method,
            params: $params,
            id: $id ?? \Ainos\Utils::generateId('req'),
        );
    }

    /**
     * Convert to an array for NDJSON serialization.
     *
     * @return array
     */
    public function toArray(): array
    {
        $data = [
            'method' => $this->method,
            'params' => $this->params,
            'id' => $this->id,
        ];

        if ($this->token !== null) {
            $data['token'] = $this->token;
        }

        return $data;
    }

    /**
     * Convert to NDJSON string.
     *
     * @return string
     */
    public function toNDJSON(): string
    {
        return \Ainos\NDJSON::encode($this->toArray());
    }
}

/**
 * Response envelope from the Ainos server.
 *
 * @immutable
 */
readonly class ResponseEnvelope
{
    /**
     * @param string $id Request identifier this response corresponds to
     * @param mixed $result Successful result data
     * @param array|null $error Error information if the request failed
     * @param string|null $type Response type (e.g., 'stream', 'stream_end', 'result')
     */
    public function __construct(
        public string $id = '',
        public mixed $result = null,
        public ?array $error = null,
        public ?string $type = null,
    ) {}

    /**
     * Create a ResponseEnvelope from an array.
     *
     * @param array $data Source data
     * @return self
     */
    public static function fromArray(array $data): self
    {
        return new self(
            id: (string)($data['id'] ?? ''),
            result: $data['result'] ?? null,
            error: isset($data['error']) ? (array)$data['error'] : null,
            type: isset($data['type']) ? (string)$data['type'] : null,
        );
    }

    /**
     * Check if the response indicates an error.
     *
     * @return bool
     */
    public function isError(): bool
    {
        return $this->error !== null;
    }

    /**
     * Check if this is a streaming chunk.
     *
     * @return bool
     */
    public function isStream(): bool
    {
        return $this->type === 'stream';
    }

    /**
     * Check if this is the end of a stream.
     *
     * @return bool
     */
    public function isStreamEnd(): bool
    {
        return $this->type === 'stream_end';
    }

    /**
     * Get the error message if this is an error response.
     *
     * @return string
     */
    public function getErrorMessage(): string
    {
        return $this->error['message'] ?? $this->error['error'] ?? 'Unknown server error';
    }

    /**
     * Get the error code if this is an error response.
     *
     * @return int
     */
    public function getErrorCode(): int
    {
        return (int)($this->error['code'] ?? 0);
    }

    /**
     * Throw an appropriate exception if this response is an error.
     *
     * @return void
     * @throws \Ainos\AinosException
     */
    public function throwIfError(): void
    {
        if (!$this->isError()) {
            return;
        }

        $errorMessage = $this->getErrorMessage();
        $errorCode = $this->getErrorCode();

        throw match ($errorCode) {
            1001, 1002, 1003 => new ConnectionException('', 0, $errorMessage),
            1011, 1012, 1013 => new AuthenticationException($errorMessage),
            1021, 1022, 1023 => new InvalidRequestException($errorMessage),
            1031 => new ModelNotFoundException($errorMessage),
            default => \Ainos\ProtocolException::serverError($errorMessage, $errorCode),
        };
    }
}