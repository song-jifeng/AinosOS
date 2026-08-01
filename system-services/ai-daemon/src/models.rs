// Ainos AI Daemon - Model Registry

use std::collections::HashMap;
use tracing::info;

use crate::ipc::ModelInfo;

/// 模型注册表 - 管理已安装和已加载的模型
#[derive(Debug)]
pub struct ModelRegistry {
    /// 所有可用模型 (path -> info)
    available: HashMap<String, ModelInfo>,
    /// 已加载模型 (id -> info)
    loaded: HashMap<String, ModelInfo>,
    /// 模型缓存最近使用
    lru_order: Vec<String>,
}

impl ModelRegistry {
    pub fn new() -> Self {
        Self {
            available: HashMap::new(),
            loaded: HashMap::new(),
            lru_order: Vec::new(),
        }
    }

    /// 扫描模型目录
    pub fn scan_directory(&mut self, path: &str) -> std::io::Result<()> {
        let dir = std::fs::read_dir(path)?;
        for entry in dir.flatten() {
            let path = entry.path();
            if let Some(ext) = path.extension() {
                let ext = ext.to_string_lossy().to_lowercase();
                if matches!(ext.as_str(), "gguf" | "ggml" | "onnx" | "bin") {
                    let file_name = path.file_name()
                        .map(|n| n.to_string_lossy().to_string())
                        .unwrap_or_default();
                    let metadata = std::fs::metadata(&path)?;
                    let size_mb = metadata.len() / (1024 * 1024);
                    let model_id = file_name.replace('.', "_");

                    let info = ModelInfo {
                        id: model_id.clone(),
                        name: file_name,
                        path: path.to_string_lossy().to_string(),
                        size_mb,
                        loaded: false,
                        architecture: "auto".to_string(),
                    };
                    self.available.insert(model_id, info);
                }
            }
        }
        info!("Scanned models directory: {} models found", self.available.len());
        Ok(())
    }

    /// 加载模型
    pub fn load(&mut self, model_id: &str) -> Result<(), String> {
        if let Some(info) = self.available.get(model_id) {
            if self.loaded.contains_key(model_id) {
                return Ok(()); // 已加载
            }
            let mut loaded_info = info.clone();
            loaded_info.loaded = true;
            self.loaded.insert(model_id.to_string(), loaded_info);
            self.lru_order.push(model_id.to_string());
            info!("Model loaded: {}", model_id);
            Ok(())
        } else {
            Err(format!("Model not found: {}", model_id))
        }
    }

    /// 卸载模型
    pub fn unload(&mut self, model_id: &str) -> Result<(), String> {
        if self.loaded.remove(model_id).is_some() {
            self.lru_order.retain(|id| id != model_id);
            info!("Model unloaded: {}", model_id);
            Ok(())
        } else {
            Err(format!("Model not loaded: {}", model_id))
        }
    }

    /// 获取已加载模型数
    pub fn count_loaded(&self) -> u32 {
        self.loaded.len() as u32
    }

    /// 列出所有模型
    pub fn list(&self) -> Vec<ModelInfo> {
        let mut all: Vec<ModelInfo> = self.available.values().cloned().collect();
        // 标记已加载的
        for info in &mut all {
            if self.loaded.contains_key(&info.id) {
                info.loaded = true;
            }
        }
        all.sort_by(|a, b| a.name.cmp(&b.name));
        all
    }
}