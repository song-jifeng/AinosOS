// Ainos AI Daemon - Runtime Manager
// 管理推理引擎 (GGML / ONNX) 并提供推理管线
// 支持模型加载/卸载、分词、上下文窗口管理、KV-cache、采样、流式推理、批处理
//
// Feature flags:
// - `ggml`: 启用真实 GGML FFI 推理
// - `onnx`: 启用 ONNX Runtime 集成
// - `cuda`: 启用 CUDA GPU 加速
// - `vulkan`: 启用 Vulkan GPU 加速

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Instant;
use thiserror::Error;
use tracing::{info, debug};
#[cfg(feature = "ggml")]
use tracing::{error, warn};

// ============================================================================
// Error Types
// ============================================================================

/// 推理运行时错误
#[derive(Error, Debug, Clone)]
pub enum RuntimeError {
    #[error("Model not found: {0}")]
    ModelNotFound(String),

    #[error("Model not loaded: {0}")]
    ModelNotLoaded(String),

    #[error("Engine not initialized: {0}")]
    EngineNotInitialized(String),

    #[error("Inference failed: {0}")]
    InferenceFailed(String),

    #[error("Invalid parameter: {0}")]
    InvalidParameter(String),

    #[error("Out of memory: {0}")]
    OutOfMemory(String),

    #[error("Context overflow: {0}")]
    ContextOverflow(String),

    #[error("Unsupported operation: {0}")]
    Unsupported(String),
}

impl From<RuntimeError> for String {
    fn from(e: RuntimeError) -> String {
        e.to_string()
    }
}

// ============================================================================
// Core Types
// ============================================================================

/// 推理引擎类型
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum EngineType {
    /// 本地 GGML 推理
    GGML,
    /// ONNX Runtime (云端回退)
    ONNX,
}

/// 量化类型
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum QuantizationType {
    Q4_0,
    Q4_1,
    Q5_0,
    Q5_1,
    Q8_0,
    F16,
    F32,
}

impl QuantizationType {
    /// 从字符串解析量化类型
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "q4_0" => Some(Self::Q4_0),
            "q4_1" => Some(Self::Q4_1),
            "q5_0" => Some(Self::Q5_0),
            "q5_1" => Some(Self::Q5_1),
            "q8_0" => Some(Self::Q8_0),
            "f16" | "fp16" => Some(Self::F16),
            "f32" | "fp32" => Some(Self::F32),
            _ => None,
        }
    }

    /// 模型大小相对于 FP32 的倍数
    pub fn size_multiplier(&self) -> f32 {
        match self {
            Self::Q4_0 => 0.25,
            Self::Q4_1 => 0.28,
            Self::Q5_0 => 0.31,
            Self::Q5_1 => 0.35,
            Self::Q8_0 => 0.50,
            Self::F16 => 0.50,
            Self::F32 => 1.0,
        }
    }

    /// 返回 GGML 类型常量 (用于 FFI)
    #[cfg(feature = "ggml")]
    pub fn to_ggml_type(&self) -> i32 {
        match self {
            Self::Q4_0 => 2,  // GGML_TYPE_Q4_0
            Self::Q4_1 => 3,  // GGML_TYPE_Q4_1
            Self::Q5_0 => 6,  // GGML_TYPE_Q5_0
            Self::Q5_1 => 7,  // GGML_TYPE_Q5_1
            Self::Q8_0 => 8,  // GGML_TYPE_Q8_0
            Self::F16 => 1,   // GGML_TYPE_F16
            Self::F32 => 0,   // GGML_TYPE_F32
        }
    }
}

/// 推理请求
#[derive(Debug, Clone)]
pub struct InferenceRequest {
    pub model: String,
    pub prompt: String,
    pub temperature: f32,
    pub top_p: f32,
    pub top_k: u32,
    pub max_tokens: u32,
    pub session_id: Option<String>,
    pub num_threads: Option<u32>,
    pub repeat_penalty: f32,
    pub frequency_penalty: f32,
    pub presence_penalty: f32,
}

impl Default for InferenceRequest {
    fn default() -> Self {
        Self {
            model: "default".to_string(),
            prompt: String::new(),
            temperature: 0.7,
            top_p: 0.9,
            top_k: 40,
            max_tokens: 512,
            session_id: None,
            num_threads: None,
            repeat_penalty: 1.1,
            frequency_penalty: 0.0,
            presence_penalty: 0.0,
        }
    }
}

impl InferenceRequest {
    /// 从旧格式的 (model, prompt, temperature, max_tokens, session_id) 创建
    pub fn new(model: String, prompt: String, temperature: Option<f32>,
               max_tokens: Option<u32>, session_id: Option<String>) -> Self {
        Self {
            model,
            prompt,
            temperature: temperature.unwrap_or(0.7),
            top_p: 0.9,
            top_k: 40,
            max_tokens: max_tokens.unwrap_or(512),
            session_id,
            num_threads: None,
            repeat_penalty: 1.1,
            frequency_penalty: 0.0,
            presence_penalty: 0.0,
        }
    }
}

/// 推理结果
#[derive(Debug, Clone)]
pub struct InferenceResult {
    pub output: String,
    pub tokens_generated: u32,
    pub prompt_tokens: u32,
    pub inference_ms: u64,
    pub tokens_per_second: f64,
    pub engine: EngineType,
}

/// 模型元数据
#[derive(Debug, Clone)]
pub struct ModelMetadata {
    pub model_id: String,
    pub model_path: String,
    pub framework: String,
    pub quantization: Option<QuantizationType>,
    pub loaded_time: i64,
    pub memory_usage: u64,
    pub device: String,
    pub ref_count: u64,
    pub architecture: String,
    pub n_layers: u64,
    pub n_heads: u64,
    pub n_embd: u64,
    pub n_vocab: u64,
}

/// 采样配置
#[derive(Debug, Clone)]
pub struct SamplingConfig {
    pub temperature: f32,
    pub top_p: f32,
    pub top_k: u32,
    pub repeat_penalty: f32,
    pub frequency_penalty: f32,
    pub presence_penalty: f32,
}

impl Default for SamplingConfig {
    fn default() -> Self {
        Self {
            temperature: 0.7,
            top_p: 0.9,
            top_k: 40,
            repeat_penalty: 1.1,
            frequency_penalty: 0.0,
            presence_penalty: 0.0,
        }
    }
}

impl From<&InferenceRequest> for SamplingConfig {
    fn from(req: &InferenceRequest) -> Self {
        Self {
            temperature: req.temperature,
            top_p: req.top_p,
            top_k: req.top_k,
            repeat_penalty: req.repeat_penalty,
            frequency_penalty: req.frequency_penalty,
            presence_penalty: req.presence_penalty,
        }
    }
}

// ============================================================================
// KV Cache
// ============================================================================

/// KV 缓存状态
#[derive(Debug, Clone)]
pub struct KVCacheState {
    pub max_seq_len: usize,
    pub n_layers: usize,
    pub n_heads: usize,
    pub n_embd: usize,
    pub current_seq_len: usize,
    pub memory_usage: u64,
}

impl KVCacheState {
    pub fn new(n_layers: usize, n_heads: usize, n_embd: usize, max_seq_len: usize) -> Self {
        let cache_size = n_layers * n_heads * n_embd * max_seq_len * 2; // K + V
        Self {
            max_seq_len,
            n_layers,
            n_heads,
            n_embd,
            current_seq_len: 0,
            memory_usage: (cache_size * 2) as u64, // FP16: 2 bytes per element
        }
    }
}

// ============================================================================
// Model Handle
// ============================================================================

/// 内部模型句柄
#[derive(Debug)]
struct ModelHandle {
    id: String,
    path: String,
    quantization: Option<QuantizationType>,
    architecture: String,
    loaded_time: Instant,
    memory_usage: u64,
    ref_count: AtomicU64,
    n_layers: u64,
    n_heads: u64,
    n_embd: u64,
    n_vocab: u64,
    #[cfg(feature = "ggml")]
    ggml_context: Option<std::ptr::NonNull<std::ffi::c_void>>,
    kv_cache: Option<KVCacheState>,
}

// ============================================================================
// GGML FFI Bindings (feature-gated)
// ============================================================================

/// GGML 和 Ainos Runtime 的 FFI 绑定
#[cfg(feature = "ggml")]
mod ggml_ffi {
    #![allow(non_camel_case_types, dead_code)]
    use std::ffi::{CStr, CString};
    use std::os::raw::{c_char, c_double, c_float, c_int, c_void};

    // ---- GGML 核心库 FFI ----

    #[link(name = "ggml")]
    extern "C" {
        pub fn ggml_init(mem_size: usize) -> *mut c_void;
        pub fn ggml_free(ctx: *mut c_void);
        pub fn ggml_time_us() -> i64;
        pub fn ggml_quantize_q4_0(
            src: *const c_void, dst: *mut c_void, n: c_int, k: c_int, hist: *mut i64,
        ) -> usize;
        pub fn ggml_quantize_q4_1(
            src: *const c_void, dst: *mut c_void, n: c_int, k: c_int, hist: *mut i64,
        ) -> usize;
        pub fn ggml_quantize_q5_0(
            src: *const c_void, dst: *mut c_void, n: c_int, k: c_int, hist: *mut i64,
        ) -> usize;
        pub fn ggml_quantize_q5_1(
            src: *const c_void, dst: *mut c_void, n: c_int, k: c_int, hist: *mut i64,
        ) -> usize;
        pub fn ggml_quantize_q8_0(
            src: *const c_void, dst: *mut c_void, n: c_int, k: c_int, hist: *mut i64,
        ) -> usize;
        pub fn ggml_new_tensor_1d(ctx: *mut c_void, dtype: c_int, ne0: c_int) -> *mut c_void;
        pub fn ggml_new_tensor_2d(ctx: *mut c_void, dtype: c_int, ne0: c_int, ne1: c_int) -> *mut c_void;
        pub fn ggml_set_param(ctx: *mut c_void, tensor: *mut c_void);
        pub fn ggml_set_i32(tensor: *mut c_void, value: c_int);
        pub fn ggml_set_f32(tensor: *mut c_void, value: c_float);
        pub fn ggml_get_i32_1d(tensor: *const c_void, i: c_int) -> c_int;
        pub fn ggml_get_f32_1d(tensor: *const c_void, i: c_int) -> c_float;
        pub fn ggml_build_forward_expand(ctx: *mut c_void, gf: *mut c_void, tensor: *mut c_void);
        pub fn ggml_graph_compute(ctx: *mut c_void, gf: *mut c_void, n_threads: c_int);
        pub fn ggml_graph_export(gf: *const c_void, fname: *const c_char);
        pub fn ggml_graph_print(gf: *const c_void);
        pub fn ggml_opt(ctx: *mut c_void, opt: *mut c_void, tensor: *mut c_void, niter: c_int);
        pub fn gguf_init_from_file(fname: *const c_char, use_mmap: bool) -> *mut c_void;
        pub fn gguf_free(ctx: *mut c_void);
        pub fn gguf_get_n_tensors(ctx: *const c_void) -> c_int;
        pub fn gguf_get_tensor_name(ctx: *const c_void, i: c_int) -> *const c_char;
        pub fn gguf_get_tensor(ctx: *const c_void, name: *const c_char) -> *mut c_void;
    }

    // ---- Ainos Runtime FFI (C++ 包装) ----

    #[link(name = "ainos_ai_runtime")]
    extern "C" {
        pub fn ainos_engine_create() -> *mut c_void;
        pub fn ainos_engine_destroy(engine: *mut c_void);
        pub fn ainos_engine_load_model(
            engine: *mut c_void, model_path: *const c_char, model_id: *const c_char,
        ) -> c_int;
        pub fn ainos_engine_unload_model(engine: *mut c_void, model_id: *const c_char) -> c_int;
        pub fn ainos_engine_inference(
            engine: *mut c_void,
            model_id: *const c_char,
            prompt: *const c_char,
            output: *mut *mut c_char,
            max_tokens: c_int,
            temperature: c_float,
            top_p: c_float,
            top_k: c_int,
            num_threads: c_int,
        ) -> c_int;
        pub fn ainos_engine_free_string(s: *mut c_char);
        pub fn ainos_engine_get_model_info(
            engine: *mut c_void,
            model_id: *const c_char,
            out_model_path: *mut *mut c_char,
            out_loaded_time: *mut i64,
            out_memory_usage: *mut u64,
            out_device: *mut c_int,
        ) -> c_int;
        pub fn ainos_onnx_service_create() -> *mut c_void;
        pub fn ainos_onnx_service_destroy(service: *mut c_void);
        pub fn ainos_onnx_service_load_model(
            service: *mut c_void, model_path: *const c_char, model_id: *const c_char,
        ) -> c_int;
        pub fn ainos_onnx_service_unload_model(
            service: *mut c_void, model_id: *const c_char,
        ) -> c_int;
        pub fn ainos_model_manager_create() -> *mut c_void;
        pub fn ainos_model_manager_destroy(mgr: *mut c_void);
        pub fn ainos_model_manager_register(
            mgr: *mut c_void, model_id: *const c_char,
            model_path: *const c_char, framework: *const c_char,
        ) -> c_int;
        pub fn ainos_model_manager_unregister(mgr: *mut c_void, model_id: *const c_char) -> c_int;
        pub fn ainos_model_manager_load(mgr: *mut c_void, model_id: *const c_char) -> c_int;
        pub fn ainos_model_manager_unload(mgr: *mut c_void, model_id: *const c_char) -> c_int;
        pub fn ainos_model_manager_optimize_memory(mgr: *mut c_void) -> c_int;
    }

    /// 将 C++ Status 转换为 Rust 结果
    pub fn status_to_result(status: c_int) -> Result<(), RuntimeError> {
        match status {
            0 => Ok(()),
            -1 => Err(RuntimeError::InvalidParameter("FFI call failed".into())),
            -2 => Err(RuntimeError::ModelNotFound("FFI: model not found".into())),
            -3 => Err(RuntimeError::InferenceFailed("FFI: inference failed".into())),
            -4 => Err(RuntimeError::OutOfMemory("FFI: out of memory".into())),
            -5 => Err(RuntimeError::EngineNotInitialized("FFI: device not available".into())),
            -6 => Err(RuntimeError::ContextOverflow("FFI: context overflow".into())),
            -7 => Err(RuntimeError::InferenceFailed("FFI: serialization failed".into())),
            _ => Err(RuntimeError::InferenceFailed(format!("FFI: unknown error {}", status))),
        }
    }
}

// ============================================================================
// Tokenizer (feature-gated with tokenizers crate)
// ============================================================================

/// 分词器抽象
#[cfg(feature = "ggml")]
mod tokenizer {
    use std::path::Path;
    use tracing::debug;

    /// 简化的 BPE 分词器
    pub struct Tokenizer {
        vocab_size: usize,
        // 生产环境使用 `tokenizers` crate 或 SentencePiece
        // _tokenizer: tokenizers::Tokenizer,
    }

    impl Tokenizer {
        pub fn new(model_path: &Path) -> Result<Self, String> {
            // 尝试从模型文件加载 tokenizer
            let vocab_size = 32000; // 默认值，实际应从模型元数据读取
            debug!("[Tokenizer] Created for model: {:?}", model_path);
            Ok(Self { vocab_size })
        }

        pub fn encode(&self, text: &str) -> Result<Vec<u32>, String> {
            debug!("[Tokenizer] Encoding {} chars", text.len());
            // 简化实现：UTF-8 字节级编码
            // 生产环境使用实际 tokenizer（如 SentencePiece BPE）
            let tokens: Vec<u32> = text.bytes().map(|b| b as u32).collect();
            if tokens.is_empty() {
                return Err("Empty input after tokenization".to_string());
            }
            Ok(tokens)
        }

        pub fn decode(&self, tokens: &[u32]) -> Result<String, String> {
            let bytes: Vec<u8> = tokens.iter().map(|&t| t as u8).collect();
            String::from_utf8(bytes).map_err(|e| format!("Decode error: {}", e))
        }

        pub fn vocab_size(&self) -> usize {
            self.vocab_size
        }
    }
}

// ============================================================================
// 采样器
// ============================================================================

/// 基于 logits 的采样器
pub struct Sampler {
    rng: fastrand::Rng,
}

impl Sampler {
    pub fn new() -> Self {
        Self {
            rng: fastrand::Rng::new(),
        }
    }

    /// 用温度 + top-p + top-k 采样
    /// 在 mock 模式下返回模拟 logits 的采样结果
    #[cfg(not(feature = "ggml"))]
    pub fn sample(&mut self, _logits: &[f32], config: &SamplingConfig) -> u32 {
        // Mock 模式下，返回一个模拟 token ID
        let _ = config;
        0
    }

    /// 真实采样（GGML 启用时）
    #[cfg(feature = "ggml")]
    pub fn sample(&mut self, logits: &[f32], config: &SamplingConfig) -> u32 {
        use std::cmp::Ordering;

        let mut logits = logits.to_vec();

        // 1. 温度缩放
        if config.temperature > 0.0 {
            let inv_temp = 1.0 / config.temperature;
            for logit in logits.iter_mut() {
                *logit *= inv_temp;
            }
        }

        // 2. Top-K 过滤
        if config.top_k > 0 && (config.top_k as usize) < logits.len() {
            let k = config.top_k as usize;
            let mut indices: Vec<usize> = (0..logits.len()).collect();
            indices.partial_sort_by(|&a, &b| logits[b].partial_cmp(&logits[a]).unwrap_or(Ordering::Equal));
            let threshold = logits[indices[k - 1]];
            for logit in logits.iter_mut() {
                if *logit < threshold {
                    *logit = f32::NEG_INFINITY;
                }
            }
        }

        // 3. Top-P (nucleus) 过滤
        if config.top_p > 0.0 && config.top_p < 1.0 {
            // Softmax 求概率
            let max_logit = logits.iter().cloned().fold(f32::NEG_INFINITY, f32::max);
            let exp_sum: f32 = logits.iter().map(|l| (l - max_logit).exp()).sum();
            let mut probs: Vec<(usize, f32)> = logits.iter().enumerate().map(|(i, l)| {
                (i, (l - max_logit).exp() / exp_sum)
            }).collect();
            probs.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(Ordering::Equal));

            let mut cumsum = 0.0;
            let mut threshold = 0.0;
            for (i, &(_, prob)) in probs.iter().enumerate() {
                cumsum += prob;
                if cumsum > config.top_p {
                    threshold = prob;
                    break;
                }
            }
            if threshold > 0.0 {
                for (i, logit) in logits.iter_mut().enumerate() {
                    let prob = (*logit - max_logit).exp() / exp_sum;
                    if prob < threshold {
                        *logit = f32::NEG_INFINITY;
                    }
                }
            }
        }

        // 4. 从剩余 logits 中采样
        let max_logit = logits.iter().cloned().fold(f32::NEG_INFINITY, f32::max);
        let exp_sum: f32 = logits.iter().map(|l| (l - max_logit).exp()).sum();

        if exp_sum <= 0.0 || exp_sum.is_nan() {
            return 0; // 无有效 token
        }

        let r: f32 = self.rng.f32();
        let mut cumulative = 0.0;
        for (i, logit) in logits.iter().enumerate() {
            cumulative += (logit - max_logit).exp() / exp_sum;
            if r <= cumulative {
                return i as u32;
            }
        }

        (logits.len() - 1) as u32 // fallback
    }
}

// ============================================================================
// Runtime Manager
// ============================================================================

/// 运行时管理器 - 管理推理引擎和模型生命周期
///
/// RuntimeManager 是 AI 推理的核心组件，提供：
/// - 模型加载/卸载（带引用计数）
/// - 推理管线（分词、生成、采样）
/// - 多种量化格式支持
/// - 流式推理和批处理
/// - 性能统计
pub struct RuntimeManager {
    /// 已加载的模型
    models: HashMap<String, ModelHandle>,
    /// 当前活跃引擎
    active_engine: EngineType,
    /// 最大加载模型数
    max_loaded_models: u32,
    /// 最大上下文长度
    max_context_length: u32,
    /// 模型加载顺序（LRU 淘汰）
    load_order: Vec<String>,
    // GGML 引擎指针
    #[cfg(feature = "ggml")]
    ggml_engine: Option<std::ptr::NonNull<std::ffi::c_void>>,
    // ONNX 服务指针
    #[cfg(feature = "onnx")]
    onnx_service: Option<std::ptr::NonNull<std::ffi::c_void>>,
    // 统计
    total_inferences: AtomicU64,
    total_tokens_generated: AtomicU64,
    total_inference_ms: AtomicU64,
    total_prompt_tokens: AtomicU64,
    total_model_loads: AtomicU64,
    total_model_unloads: AtomicU64,
    total_errors: AtomicU64,
}

impl std::fmt::Debug for RuntimeManager {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RuntimeManager")
            .field("models", &self.models.keys())
            .field("active_engine", &self.active_engine)
            .field("max_loaded_models", &self.max_loaded_models)
            .field("loaded_count", &self.models.len())
            .field("total_inferences", &self.total_inferences.load(Ordering::Relaxed))
            .field("total_tokens_generated", &self.total_tokens_generated.load(Ordering::Relaxed))
            .finish()
    }
}

impl RuntimeManager {
    /// 创建新的 RuntimeManager
    pub fn new() -> Self {
        #[cfg(feature = "ggml")]
        let ggml_engine = Self::init_ggml_engine();

        info!("[RuntimeManager] Initialized (ggml={}, onnx={})",
            cfg!(feature = "ggml"), cfg!(feature = "onnx"));

        Self {
            models: HashMap::new(),
            active_engine: EngineType::GGML,
            max_loaded_models: 8,
            max_context_length: 4096,
            load_order: Vec::new(),
            #[cfg(feature = "ggml")]
            ggml_engine,
            #[cfg(feature = "onnx")]
            onnx_service: None,
            total_inferences: AtomicU64::new(0),
            total_tokens_generated: AtomicU64::new(0),
            total_inference_ms: AtomicU64::new(0),
            total_prompt_tokens: AtomicU64::new(0),
            total_model_loads: AtomicU64::new(0),
            total_model_unloads: AtomicU64::new(0),
            total_errors: AtomicU64::new(0),
        }
    }

    /// 初始化 GGML 引擎
    #[cfg(feature = "ggml")]
    fn init_ggml_engine() -> Option<std::ptr::NonNull<std::ffi::c_void>> {
        unsafe {
            let ptr = ggml_ffi::ainos_engine_create();
            if ptr.is_null() {
                error!("[RuntimeManager] Failed to create GGML engine");
                None
            } else {
                info!("[RuntimeManager] GGML engine initialized");
                Some(std::ptr::NonNull::new_unchecked(ptr))
            }
        }
    }

    // ========================================================================
    // 模型管理
    // ========================================================================

    /// 加载模型
    pub fn load_model(&mut self, path: &str, model_id: &str) -> Result<ModelMetadata, RuntimeError> {
        if self.models.len() >= self.max_loaded_models as usize {
            // LRU 淘汰
            self.evict_lru();
        }

        if self.models.contains_key(model_id) {
            // 已加载，增加引用计数
            if let Some(handle) = self.models.get(model_id) {
                handle.ref_count.fetch_add(1, Ordering::Relaxed);
                info!("[RuntimeManager] Model '{}' ref_count increased to {}", model_id,
                    handle.ref_count.load(Ordering::Relaxed));
            }
            return self.get_model_info(model_id);
        }

        // 检测量化类型
        let quantization = Self::detect_quantization(path);

        // 验证模型文件存在
        let path_obj = std::path::Path::new(path);
        if !path_obj.exists() {
            return Err(RuntimeError::ModelNotFound(format!("File not found: {}", path)));
        }
        let file_size = std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);

        // 初始化模型句柄
        #[cfg_attr(not(feature = "ggml"), allow(unused_mut))]
        let mut handle = ModelHandle {
            id: model_id.to_string(),
            path: path.to_string(),
            quantization,
            architecture: Self::detect_architecture(path).to_string(),
            loaded_time: Instant::now(),
            memory_usage: file_size,
            ref_count: AtomicU64::new(1),
            n_layers: 32,
            n_heads: 32,
            n_embd: 4096,
            n_vocab: 32000,
            #[cfg(feature = "ggml")]
            ggml_context: None,
            kv_cache: Some(KVCacheState::new(32, 32, 4096, self.max_context_length as usize)),
        };

        // 通过 FFI 加载
        #[cfg(feature = "ggml")]
        {
            if let Some(engine_ptr) = self.ggml_engine {
                let c_path = std::ffi::CString::new(path).map_err(|e| {
                    RuntimeError::InvalidParameter(format!("Invalid path: {}", e))
                })?;
                let c_id = std::ffi::CString::new(model_id).map_err(|e| {
                    RuntimeError::InvalidParameter(format!("Invalid model_id: {}", e))
                })?;

                let status = unsafe {
                    ggml_ffi::ainos_engine_load_model(engine_ptr.as_ptr(), c_path.as_ptr(), c_id.as_ptr())
                };
                if status != 0 {
                    return Err(RuntimeError::ModelNotFound(
                        format!("GGML load failed with status {}", status)
                    ));
                }

                // 获取模型信息
                let mut out_path: *mut std::os::raw::c_char = std::ptr::null_mut();
                let mut loaded_time: i64 = 0;
                let mut mem_usage: u64 = 0;
                let mut device: i32 = 0;
                let info_status = unsafe {
                    ggml_ffi::ainos_engine_get_model_info(
                        engine_ptr.as_ptr(),
                        c_id.as_ptr(),
                        &mut out_path,
                        &mut loaded_time,
                        &mut mem_usage,
                        &mut device,
                    )
                };
                if info_status == 0 && !out_path.is_null() {
                    handle.memory_usage = mem_usage;
                    let _ = unsafe { std::ffi::CStr::from_ptr(out_path) }.to_str();
                    unsafe { ggml_ffi::ainos_engine_free_string(out_path) };
                }

                handle.ggml_context = Some(engine_ptr);
            } else {
                return Err(RuntimeError::EngineNotInitialized("GGML engine not available".into()));
            }
        }

        // 预热模型
        #[cfg(feature = "ggml")]
        {
            if let Err(e) = self.warmup_model(model_id) {
                warn!("[RuntimeManager] Model warmup failed (non-fatal): {}", e);
            }
        }

        // 更新 LRU 顺序
        self.load_order.push(model_id.to_string());
        self.total_model_loads.fetch_add(1, Ordering::Relaxed);

        info!("[RuntimeManager] Model loaded: {} (quant={:?}, mem={}MB, arch={})",
            model_id, quantization, handle.memory_usage / (1024 * 1024), handle.architecture);

        Ok(self.build_metadata(&handle))
    }

    /// 卸载模型（带引用计数）
    pub fn unload_model(&mut self, model_id: &str) -> Result<(), RuntimeError> {
        let handle = self.models.get(model_id).ok_or_else(|| {
            RuntimeError::ModelNotLoaded(format!("Model not loaded: {}", model_id))
        })?;

        let remaining = handle.ref_count.fetch_sub(1, Ordering::Relaxed);
        if remaining > 1 {
            info!("[RuntimeManager] Model '{}' ref_count decreased to {}", model_id, remaining - 1);
            return Ok(());
        }

        // 引用计数为 0，真正卸载
        #[cfg(feature = "ggml")]
        {
            if let Some(engine_ptr) = self.ggml_engine {
                let c_id = std::ffi::CString::new(model_id)
                    .map_err(|e| RuntimeError::InvalidParameter(format!("Invalid model_id: {}", e)))?;
                unsafe {
                    ggml_ffi::ainos_engine_unload_model(engine_ptr.as_ptr(), c_id.as_ptr());
                }
            }
        }

        self.models.remove(model_id);
        self.load_order.retain(|id| id != model_id);
        self.total_model_unloads.fetch_add(1, Ordering::Relaxed);

        info!("[RuntimeManager] Model unloaded: {}", model_id);
        Ok(())
    }

    /// 获取模型信息
    pub fn get_model_info(&self, model_id: &str) -> Result<ModelMetadata, RuntimeError> {
        let handle = self.models.get(model_id).ok_or_else(|| {
            RuntimeError::ModelNotLoaded(format!("Model not loaded: {}", model_id))
        })?;
        Ok(self.build_metadata(handle))
    }

    /// 获取所有已加载模型信息
    pub fn get_loaded_models(&self) -> Vec<ModelMetadata> {
        self.models.values().map(|h| self.build_metadata(h)).collect()
    }

    /// 获取已加载模型数量
    pub fn loaded_count(&self) -> usize {
        self.models.len()
    }

    // ========================================================================
    // 推理管线
    // ========================================================================

    /// 执行推理
    pub async fn infer(&mut self, request: InferenceRequest) -> Result<InferenceResult, RuntimeError> {
        let start = Instant::now();

        // 检查模型是否已加载
        if !self.models.contains_key(&request.model) {
            return Err(RuntimeError::ModelNotLoaded(format!(
                "Model '{}' not loaded. Call load_model() first.", request.model
            )));
        }

        // 更新 LRU
        self.update_lru(&request.model);

        // 更新统计
        self.total_inferences.fetch_add(1, Ordering::Relaxed);

        let result = self.infer_inner(&request).await?;

        let elapsed = start.elapsed().as_millis() as u64;
        self.total_inference_ms.fetch_add(elapsed, Ordering::Relaxed);
        self.total_tokens_generated.fetch_add(result.tokens_generated as u64, Ordering::Relaxed);
        self.total_prompt_tokens.fetch_add(result.prompt_tokens as u64, Ordering::Relaxed);

        debug!("[RuntimeManager] Inference complete: {} tokens in {}ms ({:.1} tok/s)",
            result.tokens_generated, elapsed, result.tokens_per_second);

        Ok(result)
    }

    /// 流式推理
    pub async fn infer_streaming<F: FnMut(&str)>(
        &mut self,
        request: InferenceRequest,
        mut callback: F,
    ) -> Result<InferenceResult, RuntimeError> {
        let start = Instant::now();

        if !self.models.contains_key(&request.model) {
            return Err(RuntimeError::ModelNotLoaded(format!(
                "Model '{}' not loaded.", request.model
            )));
        }

        self.update_lru(&request.model);
        self.total_inferences.fetch_add(1, Ordering::Relaxed);

        let result = self.infer_streaming_inner(&request, &mut callback).await?;

        let elapsed = start.elapsed().as_millis() as u64;
        self.total_inference_ms.fetch_add(elapsed, Ordering::Relaxed);
        self.total_tokens_generated.fetch_add(result.tokens_generated as u64, Ordering::Relaxed);

        Ok(result)
    }

    /// 批处理推理
    pub async fn batch_infer(
        &mut self,
        requests: Vec<InferenceRequest>,
    ) -> Vec<Result<InferenceResult, RuntimeError>> {
        let mut results = Vec::with_capacity(requests.len());
        for req in requests {
            results.push(self.infer(req).await);
        }
        results
    }

    // ========================================================================
    // 内部推理实现
    // ========================================================================

    /// 内部推理（非流式）
    async fn infer_inner(&mut self, request: &InferenceRequest) -> Result<InferenceResult, RuntimeError> {
        let prompt_tokens = self.estimate_token_count(&request.prompt);

        #[cfg(feature = "ggml")]
        {
            return self.ggml_infer(request, prompt_tokens).await;
        }

        #[cfg(not(feature = "ggml"))]
        {
            return self.mock_infer(request, prompt_tokens).await;
        }
    }

    /// 内部流式推理
    async fn infer_streaming_inner<F: FnMut(&str)>(
        &mut self,
        request: &InferenceRequest,
        callback: &mut F,
    ) -> Result<InferenceResult, RuntimeError> {
        let prompt_tokens = self.estimate_token_count(&request.prompt);

        #[cfg(feature = "ggml")]
        {
            return self.ggml_infer_streaming(request, prompt_tokens, callback).await;
        }

        #[cfg(not(feature = "ggml"))]
        {
            return self.mock_infer_streaming(request, prompt_tokens, callback).await;
        }
    }

    // ---- GGML 推理 ----

    /// GGML 真实验证推理（FFI）
    #[cfg(feature = "ggml")]
    async fn ggml_infer(
        &mut self, request: &InferenceRequest, prompt_tokens: u32,
    ) -> Result<InferenceResult, RuntimeError> {
        let engine_ptr = self.ggml_engine.ok_or_else(|| {
            RuntimeError::EngineNotInitialized("GGML engine not available".into())
        })?;

        let c_id = std::ffi::CString::new(request.model.as_str())
            .map_err(|e| RuntimeError::InvalidParameter(format!("model_id: {}", e)))?;
        let c_prompt = std::ffi::CString::new(request.prompt.as_str())
            .map_err(|e| RuntimeError::InvalidParameter(format!("prompt: {}", e)))?;

        let mut output: *mut std::os::raw::c_char = std::ptr::null_mut();
        let num_threads = request.num_threads.unwrap_or_else(|| {
            std::thread::available_parallelism().map(|n| n.get() as u32).unwrap_or(4)
        }) as i32;

        let status = unsafe {
            ggml_ffi::ainos_engine_inference(
                engine_ptr.as_ptr(),
                c_id.as_ptr(),
                c_prompt.as_ptr(),
                &mut output,
                request.max_tokens as i32,
                request.temperature,
                request.top_p,
                request.top_k as i32,
                num_threads,
            )
        };

        if status != 0 {
            self.total_errors.fetch_add(1, Ordering::Relaxed);
            return Err(ggml_ffi::status_to_result(status));
        }

        let result_str = if !output.is_null() {
            let s = unsafe { std::ffi::CStr::from_ptr(output) }
                .to_string_lossy()
                .into_owned();
            unsafe { ggml_ffi::ainos_engine_free_string(output) };
            s
        } else {
            String::new()
        };

        let tokens_generated = self.estimate_token_count(&result_str);
        let inference_ms = 0; // 实际时间由调用方计算

        Ok(InferenceResult {
            output: result_str,
            tokens_generated,
            prompt_tokens,
            inference_ms,
            tokens_per_second: if inference_ms > 0 {
                tokens_generated as f64 / inference_ms as f64 * 1000.0
            } else {
                0.0
            },
            engine: EngineType::GGML,
        })
    }

    /// GGML 流式推理
    #[cfg(feature = "ggml")]
    async fn ggml_infer_streaming<F: FnMut(&str)>(
        &mut self, request: &InferenceRequest, prompt_tokens: u32, _callback: &mut F,
    ) -> Result<InferenceResult, RuntimeError> {
        // 流式推理通过多次调用同步推理模拟
        // 生产环境应使用 C++ 端的 InferenceStream
        let result = self.ggml_infer(request, prompt_tokens).await?;
        // TODO: 逐 token 回调
        Ok(result)
    }

    // ---- Mock 推理（GGML 未启用时） ----

    /// Mock 推理（用于开发和测试）
    #[cfg(not(feature = "ggml"))]
    async fn mock_infer(
        &mut self, request: &InferenceRequest, prompt_tokens: u32,
    ) -> Result<InferenceResult, RuntimeError> {
        let max_tokens = request.max_tokens.min(2048) as u32;
        let simulated_delay = (max_tokens as u64) * 5; // 5ms per token

        // 模拟带延迟
        if simulated_delay > 0 {
            tokio::time::sleep(std::time::Duration::from_millis(simulated_delay.min(500))).await;
        }

        let output = format!(
            "[{}] Processed '{}' ({} tokens, temp={}, top_p={}, top_k={})",
            match self.active_engine {
                EngineType::GGML => "GGML",
                EngineType::ONNX => "ONNX",
            },
            if request.prompt.len() > 50 { &request.prompt[..50] } else { &request.prompt },
            max_tokens,
            request.temperature,
            request.top_p,
            request.top_k,
        );

        let tokens_generated = max_tokens;
        let inference_ms = simulated_delay;

        Ok(InferenceResult {
            output,
            tokens_generated,
            prompt_tokens,
            inference_ms,
            tokens_per_second: if inference_ms > 0 {
                tokens_generated as f64 / inference_ms as f64 * 1000.0
            } else {
                0.0
            },
            engine: self.active_engine.clone(),
        })
    }

    /// Mock 流式推理
    #[cfg(not(feature = "ggml"))]
    async fn mock_infer_streaming<F: FnMut(&str)>(
        &mut self, request: &InferenceRequest, prompt_tokens: u32, callback: &mut F,
    ) -> Result<InferenceResult, RuntimeError> {
        let max_tokens = request.max_tokens.min(256) as u32;
        let start = Instant::now();

        // 模拟逐 token 生成
        for i in 0..max_tokens {
            let token = format!("token_{} ", i + 1);
            callback(&token);
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }

        let elapsed = start.elapsed().as_millis() as u64;
        let output = format!("[Streaming] Generated {} tokens for prompt: {}",
            max_tokens, &request.prompt[..request.prompt.len().min(30)]);

        Ok(InferenceResult {
            output,
            tokens_generated: max_tokens,
            prompt_tokens,
            inference_ms: elapsed,
            tokens_per_second: if elapsed > 0 {
                max_tokens as f64 / elapsed as f64 * 1000.0
            } else {
                0.0
            },
            engine: self.active_engine.clone(),
        })
    }

    // ========================================================================
    // 辅助方法
    // ========================================================================

    /// 切换到指定引擎
    pub fn switch_engine(&mut self, engine_type: EngineType) {
        self.active_engine = engine_type;
        info!("[RuntimeManager] Switched to {:?} engine", self.active_engine);
    }

    /// 获取当前引擎
    pub fn active_engine(&self) -> &EngineType {
        &self.active_engine
    }

    /// 设置最大上下文长度
    pub fn set_max_context_length(&mut self, length: u32) {
        self.max_context_length = length;
        info!("[RuntimeManager] Max context length set to {}", length);
    }

    /// 设置最大加载模型数
    pub fn set_max_loaded_models(&mut self, count: u32) {
        self.max_loaded_models = count;
        info!("[RuntimeManager] Max loaded models set to {}", count);
    }

    /// 预热模型
    #[cfg(feature = "ggml")]
    fn warmup_model(&mut self, model_id: &str) -> Result<(), RuntimeError> {
        debug!("[RuntimeManager] Warming up model: {}", model_id);
        // 发送一个短推理请求以预热
        let warmup_req = InferenceRequest {
            model: model_id.to_string(),
            prompt: "Hi".to_string(),
            max_tokens: 1,
            temperature: 0.0,
            ..Default::default()
        };
        // 同步执行预热
        // 生产环境：使用 GGML 的预热 API
        let _ = warmup_req;
        Ok(())
    }

    /// 检测量化类型
    pub(crate) fn detect_quantization(path: &str) -> Option<QuantizationType> {
        let lower = path.to_lowercase();
        if lower.contains("q4_0") || lower.contains("q4-0") { Some(QuantizationType::Q4_0) }
        else if lower.contains("q4_1") || lower.contains("q4-1") { Some(QuantizationType::Q4_1) }
        else if lower.contains("q5_0") || lower.contains("q5-0") { Some(QuantizationType::Q5_0) }
        else if lower.contains("q5_1") || lower.contains("q5-1") { Some(QuantizationType::Q5_1) }
        else if lower.contains("q8_0") || lower.contains("q8-0") { Some(QuantizationType::Q8_0) }
        else if lower.contains("f16") || lower.contains("fp16") { Some(QuantizationType::F16) }
        else if lower.contains("f32") || lower.contains("fp32") { Some(QuantizationType::F32) }
        else { None }
    }

    /// 检测模型架构
    pub(crate) fn detect_architecture(path: &str) -> &'static str {
        let lower = path.to_lowercase();
        if lower.contains("llama") { "llama" }
        else if lower.contains("phi") { "phi3" }
        else if lower.contains("mistral") { "mistral" }
        else if lower.contains("falcon") { "falcon" }
        else if lower.contains("gemma") { "gemma" }
        else if lower.contains("qwen") { "qwen2" }
        else if lower.contains("chatglm") || lower.contains("glm") { "chatglm" }
        else if lower.contains("starcoder") || lower.contains("codellama") { "starcoder" }
        else { "auto" }
    }

    /// 估算 token 数量（简化：4 字符 ≈ 1 token）
    pub(crate) fn estimate_token_count(&self, text: &str) -> u32 {
        (text.len() as u32 + 3) / 4
    }

    /// 构建模型元数据
    fn build_metadata(&self, handle: &ModelHandle) -> ModelMetadata {
        ModelMetadata {
            model_id: handle.id.clone(),
            model_path: handle.path.clone(),
            framework: "ggml".to_string(),
            quantization: handle.quantization,
            loaded_time: 0,
            memory_usage: handle.memory_usage,
            device: "CPU".to_string(),
            ref_count: handle.ref_count.load(Ordering::Relaxed),
            architecture: handle.architecture.clone(),
            n_layers: handle.n_layers,
            n_heads: handle.n_heads,
            n_embd: handle.n_embd,
            n_vocab: handle.n_vocab,
        }
    }

    /// LRU 淘汰
    fn evict_lru(&mut self) {
        if self.load_order.is_empty() {
            return;
        }
        let lru_id = self.load_order.remove(0);
        if let Some(handle) = self.models.get(&lru_id) {
            info!("[RuntimeManager] LRU evicting model: {} (ref_count={})",
                lru_id, handle.ref_count.load(Ordering::Relaxed));
        }
        let _ = self.unload_model(&lru_id);
        self.evict_lru(); // 可能需要继续淘汰
    }

    /// 更新 LRU 顺序
    fn update_lru(&mut self, model_id: &str) {
        if let Some(pos) = self.load_order.iter().position(|id| id == model_id) {
            self.load_order.remove(pos);
        }
        self.load_order.push(model_id.to_string());
    }

    // ========================================================================
    // 统计信息
    // ========================================================================

    /// 获取运行时统计
    pub fn get_stats(&self) -> HashMap<String, u64> {
        let mut stats = HashMap::new();
        stats.insert("total_inferences".to_string(), self.total_inferences.load(Ordering::Relaxed));
        stats.insert("total_tokens_generated".to_string(), self.total_tokens_generated.load(Ordering::Relaxed));
        stats.insert("total_inference_ms".to_string(), self.total_inference_ms.load(Ordering::Relaxed));
        stats.insert("total_prompt_tokens".to_string(), self.total_prompt_tokens.load(Ordering::Relaxed));
        stats.insert("total_model_loads".to_string(), self.total_model_loads.load(Ordering::Relaxed));
        stats.insert("total_model_unloads".to_string(), self.total_model_unloads.load(Ordering::Relaxed));
        stats.insert("total_errors".to_string(), self.total_errors.load(Ordering::Relaxed));
        stats.insert("models_loaded".to_string(), self.models.len() as u64);
        stats.insert("max_loaded_models".to_string(), self.max_loaded_models as u64);
        stats.insert("max_context_length".to_string(), self.max_context_length as u64);
        stats
    }

    /// 获取引擎统计（旧接口兼容）
    pub fn get_engine_stats(&self) -> HashMap<String, u64> {
        self.get_stats()
    }

    /// 初始化引擎 (IPC handler 使用)
    pub fn init_engine(&mut self, engine_type: EngineType, _model_path: &str) -> Result<(), String> {
        self.active_engine = engine_type;
        info!("[RuntimeManager] Engine initialized: {:?}", self.active_engine);
        Ok(())
    }
}

impl Default for RuntimeManager {
    fn default() -> Self {
        Self::new()
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    // ---- 基本类型测试 ----

    #[test]
    fn test_quantization_from_str() {
        assert_eq!(QuantizationType::from_str("q4_0"), Some(QuantizationType::Q4_0));
        assert_eq!(QuantizationType::from_str("Q8_0"), Some(QuantizationType::Q8_0));
        assert_eq!(QuantizationType::from_str("fp16"), Some(QuantizationType::F16));
        assert_eq!(QuantizationType::from_str("invalid"), None);
    }

    #[test]
    fn test_quantization_size_multiplier() {
        assert!((QuantizationType::Q4_0.size_multiplier() - 0.25).abs() < 0.01);
        assert!((QuantizationType::F32.size_multiplier() - 1.0).abs() < 0.01);
        assert!((QuantizationType::F16.size_multiplier() - 0.5).abs() < 0.01);
    }

    #[test]
    fn test_detect_quantization() {
        assert_eq!(RuntimeManager::detect_quantization("model-q4_0.gguf"),
            Some(QuantizationType::Q4_0));
        assert_eq!(RuntimeManager::detect_quantization("model-fp16.gguf"),
            Some(QuantizationType::F16));
        assert_eq!(RuntimeManager::detect_quantization("model.gguf"), None);
    }

    #[test]
    fn test_detect_architecture() {
        assert_eq!(RuntimeManager::detect_architecture("llama-2-7b.gguf"), "llama");
        assert_eq!(RuntimeManager::detect_architecture("phi-3-mini.gguf"), "phi3");
        assert_eq!(RuntimeManager::detect_architecture("mistral-7b.gguf"), "mistral");
        assert_eq!(RuntimeManager::detect_architecture("unknown.gguf"), "auto");
    }

    #[test]
    fn test_estimate_token_count() {
        let rm = RuntimeManager::new();
        assert_eq!(rm.estimate_token_count("hello"), 2); // 5/4 = 1.25 -> 2
        assert_eq!(rm.estimate_token_count("a"), 1);
        assert_eq!(rm.estimate_token_count(""), 0);
    }

    // ---- 模型管理测试 ----

    #[test]
    fn test_new_runtime_manager() {
        let rm = RuntimeManager::new();
        assert_eq!(rm.loaded_count(), 0);
        assert_eq!(rm.active_engine(), &EngineType::GGML);
    }

    #[test]
    fn test_load_model_missing_file() {
        let mut rm = RuntimeManager::new();
        let result = rm.load_model("/nonexistent/model.gguf", "test_model");
        assert!(result.is_err());
        match result {
            Err(RuntimeError::ModelNotFound(_)) => {} // expected
            _ => panic!("Expected ModelNotFound error"),
        }
    }

    #[test]
    fn test_switch_engine() {
        let mut rm = RuntimeManager::new();
        assert_eq!(rm.active_engine(), &EngineType::GGML);
        rm.switch_engine(EngineType::ONNX);
        assert_eq!(rm.active_engine(), &EngineType::ONNX);
    }

    #[test]
    fn test_get_stats() {
        let rm = RuntimeManager::new();
        let stats = rm.get_stats();
        assert_eq!(stats.get("models_loaded"), Some(&0));
        assert_eq!(stats.get("total_inferences"), Some(&0));
        assert!(stats.contains_key("total_errors"));
        assert!(stats.contains_key("max_context_length"));
    }

    #[test]
    fn test_get_loaded_models_empty() {
        let rm = RuntimeManager::new();
        assert!(rm.get_loaded_models().is_empty());
    }

    #[test]
    fn test_set_max_context_length() {
        let mut rm = RuntimeManager::new();
        rm.set_max_context_length(8192);
        let stats = rm.get_stats();
        assert_eq!(stats.get("max_context_length"), Some(&8192));
    }

    #[test]
    fn test_set_max_loaded_models() {
        let mut rm = RuntimeManager::new();
        rm.set_max_loaded_models(4);
        let stats = rm.get_stats();
        assert_eq!(stats.get("max_loaded_models"), Some(&4));
    }

    // ---- 推理请求默认值测试 ----

    #[test]
    fn test_inference_request_default() {
        let req = InferenceRequest::default();
        assert_eq!(req.model, "default");
        assert_eq!(req.temperature, 0.7);
        assert_eq!(req.top_p, 0.9);
        assert_eq!(req.top_k, 40);
        assert_eq!(req.max_tokens, 512);
        assert_eq!(req.repeat_penalty, 1.1);
    }

    #[test]
    fn test_inference_request_new() {
        let req = InferenceRequest::new(
            "test_model".into(),
            "Hello".into(),
            Some(0.5),
            Some(100),
            Some("sess1".into()),
        );
        assert_eq!(req.model, "test_model");
        assert_eq!(req.prompt, "Hello");
        assert_eq!(req.temperature, 0.5);
        assert_eq!(req.max_tokens, 100);
        assert_eq!(req.session_id, Some("sess1".into()));
    }

    #[test]
    fn test_inference_request_new_defaults() {
        let req = InferenceRequest::new(
            "m".into(),
            "test".into(),
            None,
            None,
            None,
        );
        assert_eq!(req.temperature, 0.7);
        assert_eq!(req.max_tokens, 512);
        assert_eq!(req.session_id, None);
    }

    // ---- 采样配置测试 ----

    #[test]
    fn test_sampling_config_default() {
        let cfg = SamplingConfig::default();
        assert!((cfg.temperature - 0.7).abs() < 0.001);
        assert!((cfg.top_p - 0.9).abs() < 0.001);
        assert_eq!(cfg.top_k, 40);
    }

    #[test]
    fn test_sampling_config_from_request() {
        let req = InferenceRequest {
            temperature: 0.3,
            top_p: 0.8,
            top_k: 20,
            ..Default::default()
        };
        let cfg = SamplingConfig::from(&req);
        assert!((cfg.temperature - 0.3).abs() < 0.001);
        assert!((cfg.top_p - 0.8).abs() < 0.001);
        assert_eq!(cfg.top_k, 20);
    }

    // ---- 推理测试（Mock 模式） ----

    #[tokio::test]
    async fn test_infer_model_not_loaded() {
        let mut rm = RuntimeManager::new();
        let req = InferenceRequest::default();
        let result = rm.infer(req).await;
        assert!(result.is_err());
        match result {
            Err(RuntimeError::ModelNotLoaded(_)) => {} // expected
            _ => panic!("Expected ModelNotLoaded error"),
        }
    }

    #[tokio::test]
    async fn test_infer_with_custom_params() {
        let mut rm = RuntimeManager::new();
        let req = InferenceRequest {
            model: "nonexistent".to_string(),
            prompt: "Hello".to_string(),
            temperature: 0.5,
            top_p: 0.95,
            top_k: 50,
            max_tokens: 10,
            ..Default::default()
        };
        let result = rm.infer(req).await;
        assert!(result.is_err()); // model not loaded
    }

    #[tokio::test]
    async fn test_batch_infer() {
        let mut rm = RuntimeManager::new();
        let requests = vec![
            InferenceRequest { model: "m1".into(), prompt: "Hello".into(), ..Default::default() },
            InferenceRequest { model: "m2".into(), prompt: "World".into(), ..Default::default() },
        ];
        let results = rm.batch_infer(requests).await;
        assert_eq!(results.len(), 2);
        for result in results {
            assert!(result.is_err()); // models not loaded
        }
    }

    #[tokio::test]
    async fn test_infer_streaming_model_not_loaded() {
        let mut rm = RuntimeManager::new();
        let req = InferenceRequest::default();
        let tokens: std::sync::Arc<std::sync::Mutex<Vec<String>>> =
            std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
        let tokens_clone = tokens.clone();
        let result = rm.infer_streaming(req, move |token| {
            tokens_clone.lock().unwrap().push(token.to_string());
        }).await;
        assert!(result.is_err());
    }

    // ---- 模型句柄测试 ----

    #[test]
    fn test_kv_cache_state() {
        let cache = KVCacheState::new(32, 32, 4096, 2048);
        assert_eq!(cache.max_seq_len, 2048);
        assert_eq!(cache.n_layers, 32);
        assert_eq!(cache.n_heads, 32);
        assert_eq!(cache.n_embd, 4096);
        assert!(cache.memory_usage > 0);
    }

    // ---- 错误类型测试 ----

    #[test]
    fn test_runtime_error_display() {
        let err = RuntimeError::ModelNotFound("test.gguf".into());
        assert_eq!(err.to_string(), "Model not found: test.gguf");

        let err = RuntimeError::InferenceFailed("OOM".into());
        assert_eq!(err.to_string(), "Inference failed: OOM");
    }

    #[test]
    fn test_runtime_error_into_string() {
        let err = RuntimeError::ModelNotLoaded("m1".into());
        let s: String = err.into();
        assert_eq!(s, "Model not loaded: m1");
    }

    // ---- 统计测试 ----

    #[test]
    fn test_stats_after_operations() {
        let mut rm = RuntimeManager::new();
        // 试图加载不存在的模型（应计入错误）
        let _ = rm.load_model("/nonexistent", "err");
        let stats = rm.get_stats();
        // 统计应该正确反映状态
        assert_eq!(stats.get("models_loaded"), Some(&0));
    }
}