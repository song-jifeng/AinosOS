using System.Text.Json.Serialization;

namespace AinosSdk.Models;

/// <summary>
/// Request parameters for a model inference operation.
/// Use the <see cref="Builder"/> to construct instances with a fluent API.
/// </summary>
public class InferenceRequest
{
    /// <summary>
    /// The model identifier to use for inference (default "default").
    /// </summary>
    [JsonPropertyName("model")]
    public string Model { get; init; } = "default";

    /// <summary>
    /// The input prompt text.
    /// </summary>
    [JsonPropertyName("prompt")]
    public string Prompt { get; init; } = string.Empty;

    /// <summary>
    /// Sampling temperature (0.0–2.0). Null uses the daemon default.
    /// </summary>
    [JsonPropertyName("temperature")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public float? Temperature { get; init; }

    /// <summary>
    /// Maximum number of tokens to generate. Null uses the daemon default.
    /// </summary>
    [JsonPropertyName("max_tokens")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? MaxTokens { get; init; }

    /// <summary>
    /// Optional session identifier for context tracking.
    /// </summary>
    [JsonPropertyName("session_id")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? SessionId { get; init; }

    /// <summary>
    /// Creates a new <see cref="Builder"/> for constructing an <see cref="InferenceRequest"/>.
    /// </summary>
    /// <param name="prompt">The input prompt text.</param>
    public static Builder CreateBuilder(string prompt) => new Builder().WithPrompt(prompt);

    /// <summary>
    /// Creates a new <see cref="Builder"/> for constructing an <see cref="InferenceRequest"/>.
    /// </summary>
    /// <param name="prompt">The input prompt text.</param>
    /// <param name="model">The model identifier.</param>
    public static Builder CreateBuilder(string prompt, string model) =>
        new Builder().WithPrompt(prompt).WithModel(model);

    /// <summary>
    /// Fluent builder for <see cref="InferenceRequest"/>.
    /// </summary>
    public class Builder
    {
        private string _model = "default";
        private string _prompt = string.Empty;
        private float? _temperature;
        private int? _maxTokens;
        private string? _sessionId;

        internal Builder()
        {
        }

        /// <summary>Sets the model identifier.</summary>
        public Builder WithModel(string model) { _model = model; return this; }

        /// <summary>Sets the input prompt.</summary>
        public Builder WithPrompt(string prompt) { _prompt = prompt; return this; }

        /// <summary>Sets the sampling temperature.</summary>
        public Builder WithTemperature(float temperature) { _temperature = temperature; return this; }

        /// <summary>Sets the maximum tokens to generate.</summary>
        public Builder WithMaxTokens(int maxTokens) { _maxTokens = maxTokens; return this; }

        /// <summary>Sets the session identifier for context tracking.</summary>
        public Builder WithSessionId(string sessionId) { _sessionId = sessionId; return this; }

        /// <summary>Builds the <see cref="InferenceRequest"/>.</summary>
        public InferenceRequest Build() => new()
        {
            Model = _model,
            Prompt = _prompt,
            Temperature = _temperature,
            MaxTokens = _maxTokens,
            SessionId = _sessionId,
        };
    }

    /// <summary>
    /// Returns a JSON-compatible dictionary representation for wire serialization.
    /// </summary>
    internal Dictionary<string, object?> ToWireFormat()
    {
        var dict = new Dictionary<string, object?>
        {
            ["type"] = "Inference",
            ["model"] = Model,
            ["prompt"] = Prompt,
        };
        if (Temperature.HasValue) dict["temperature"] = Temperature.Value;
        if (MaxTokens.HasValue) dict["max_tokens"] = MaxTokens.Value;
        if (SessionId is not null) dict["session_id"] = SessionId;
        return dict;
    }

    /// <summary>
    /// Returns a JSON-compatible dictionary for streaming wire format.
    /// </summary>
    internal Dictionary<string, object?> ToStreamWireFormat()
    {
        var dict = new Dictionary<string, object?>
        {
            ["type"] = "InferenceStream",
            ["model"] = Model,
            ["prompt"] = Prompt,
        };
        if (Temperature.HasValue) dict["temperature"] = Temperature.Value;
        if (MaxTokens.HasValue) dict["max_tokens"] = MaxTokens.Value;
        if (SessionId is not null) dict["session_id"] = SessionId;
        return dict;
    }
}