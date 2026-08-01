// AI Borrow Checker - 分析器模块

use std::collections::HashMap;

/// 借用错误分析
pub struct BorrowAnalyzer {
    error_patterns: Vec<ErrorPattern>,
}

/// 错误模式
struct ErrorPattern {
    pattern: &'static str,
    category: ErrorCategory,
    fix: &'static str,
    example: &'static str,
}

/// 错误类别
#[derive(Debug, PartialEq)]
pub enum ErrorCategory {
    Mutability,
    Ownership,
    Lifetime,
    Borrowing,
    Other,
}

impl BorrowAnalyzer {
    pub fn new() -> Self {
        Self {
            error_patterns: vec![
                ErrorPattern {
                    pattern: "cannot borrow .* as immutable",
                    category: ErrorCategory::Borrowing,
                    fix: "Change to let mut or use RefCell",
                    example: "let mut x = value;",
                },
                ErrorPattern {
                    pattern: "cannot move out of",
                    category: ErrorCategory::Ownership,
                    fix: "Clone or use reference",
                    example: "value.clone()",
                },
                ErrorPattern {
                    pattern: "does not live long enough",
                    category: ErrorCategory::Lifetime,
                    fix: "Extend lifetime or restructure scope",
                    example: "move definition outside block",
                },
                ErrorPattern {
                    pattern: "lifetime mismatch",
                    category: ErrorCategory::Lifetime,
                    fix: "Add explicit lifetime annotations",
                    example: "fn foo<'a>(x: &'a str) -> &'a str",
                },
                ErrorPattern {
                    pattern: "as mutable more than once",
                    category: ErrorCategory::Borrowing,
                    fix: "Use RefCell for runtime borrow checking",
                    example: "let cell = RefCell::new(value);",
                },
                ErrorPattern {
                    pattern: "dereference of raw pointer",
                    category: ErrorCategory::Other,
                    fix: "Ensure pointer is valid before dereferencing",
                    example: "unsafe { ... }",
                },
            ],
        }
    }

    /// 分析错误并返回建议
    pub fn analyze(&self, error_text: &str) -> Vec<String> {
        let mut suggestions = Vec::new();

        for pattern in &self.error_patterns {
            if error_text.contains(pattern.pattern.trim_end_matches('*')) {
                suggestions.push(format!("  Category: {:?}", pattern.category));
                suggestions.push(format!("  Fix: {}", pattern.fix));
                suggestions.push(format!("  Example: {}", pattern.example));
            }
        }

        if suggestions.is_empty() {
            suggestions.push("  No specific pattern found. General advice:".to_string());
            suggestions.push("  - Check ownership rules".to_string());
            suggestions.push("  - Verify lifetime annotations".to_string());
            suggestions.push("  - Ensure correct mutability".to_string());
        }

        suggestions
    }

    /// 分析代码文件
    pub fn analyze_file(&self, path: &str) -> anyhow::Result<AnalysisResult> {
        let content = std::fs::read_to_string(path)?;
        let mut result = AnalysisResult::new(path.to_string());

        // 扫描代码中的潜在问题
        for (i, line) in content.lines().enumerate() {
            if line.contains("unsafe ") {
                result.unsafe_blocks.push(i + 1);
            }
            if line.contains("clone()") {
                result.clone_calls.push(i + 1);
            }
            if line.contains("RefCell") || line.contains("Mutex") {
                result.interior_mutability.push(i + 1);
            }
            if line.contains("'static") {
                result.static_lifetimes.push(i + 1);
            }
        }

        Ok(result)
    }
}

/// 分析结果
pub struct AnalysisResult {
    pub file: String,
    pub unsafe_blocks: Vec<usize>,
    pub clone_calls: Vec<usize>,
    pub interior_mutability: Vec<usize>,
    pub static_lifetimes: Vec<usize>,
}

impl AnalysisResult {
    fn new(file: String) -> Self {
        Self {
            file,
            unsafe_blocks: Vec::new(),
            clone_calls: Vec::new(),
            interior_mutability: Vec::new(),
            static_lifetimes: Vec::new(),
        }
    }

    pub fn summary(&self) -> String {
        format!(
            "File: {}\n  Unsafe blocks: {}\n  Clone calls: {}\n  Interior mutability: {}\n  Static lifetimes: {}",
            self.file,
            self.unsafe_blocks.len(),
            self.clone_calls.len(),
            self.interior_mutability.len(),
            self.static_lifetimes.len(),
        )
    }
}