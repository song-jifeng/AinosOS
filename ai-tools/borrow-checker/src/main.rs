// AI Borrow Checker - Rust 编译器辅助工具
// 提供更好的借用检查错误信息，AI 修复建议

use clap::{Parser, Subcommand};
use std::process::Command;

#[derive(Parser)]
#[command(name = "cargo-ainos-borrow", version, about = "AI-assisted Rust borrow checker")]
struct Cli {
    #[command(subcommand)]
    command: Commands,

    /// 项目路径
    #[arg(short, long, default_value = ".")]
    path: String,
}

#[derive(Subcommand)]
enum Commands {
    /// 检查当前项目
    Check,
    /// 分析借用错误
    Analyze {
        /// 错误信息文件
        file: Option<String>,
    },
    /// 修复建议
    Fix {
        /// 错误信息
        error: String,
    },
}

fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();

    match cli.command {
        Commands::Check => {
            check_project(&cli.path)?;
        }
        Commands::Analyze { file } => {
            analyze_errors(file.as_deref())?;
        }
        Commands::Fix { error } => {
            match suggest_fix(&error) {
                Some(suggestion) => println!("{}", suggestion),
                None => println!("No specific suggestion for this error."),
            }
        }
    }

    Ok(())
}

/// 检查项目
fn check_project(path: &str) -> anyhow::Result<()> {
    println!("[borrow-checker] Analyzing project: {}", path);

    let output = Command::new("cargo")
        .args(["check", "--message-format=json"])
        .current_dir(path)
        .output()?;

    let stderr = String::from_utf8_lossy(&output.stderr);

    // 提取借用错误
    let borrow_errors: Vec<&str> = stderr
        .lines()
        .filter(|l| l.contains("borrow") || l.contains("lifetime") || l.contains("ownership"))
        .collect();

    if borrow_errors.is_empty() {
        println!("[borrow-checker] No borrow errors found!");
        return Ok(());
    }

    println!("[borrow-checker] Found {} borrow-related issues:", borrow_errors.len());

    for (i, err) in borrow_errors.iter().enumerate() {
        println!("\n--- Issue #{} ---", i + 1);
        println!("{}", err);
        println!("[borrow-checker] Suggestion: {}", suggest_fix(err).unwrap_or_default());
    }

    Ok(())
}

/// 分析错误
fn analyze_errors(file: Option<&str>) -> anyhow::Result<()> {
    let content = if let Some(f) = file {
        std::fs::read_to_string(f)?
    } else {
        let mut s = String::new();
        std::io::stdin().read_line(&mut s)?;
        s
    };

    let suggestions = analyze_borrow_errors(&content);
    for s in suggestions {
        println!("{}", s);
    }

    Ok(())
}

/// 分析借用错误并给出建议
fn analyze_borrow_errors(error_text: &str) -> Vec<String> {
    let mut suggestions = Vec::new();

    // 常见借用错误模式
    if error_text.contains("cannot borrow") && error_text.contains("as immutable") {
        suggestions.push("  Fix: Change the binding to `let mut` or use `RefCell` for interior mutability.".to_string());
        suggestions.push("  Example: `let mut x = value;` instead of `let x = value;`".to_string());
    }

    if error_text.contains("cannot move out of") {
        suggestions.push("  Fix: Clone the value or use a reference instead of moving.".to_string());
        suggestions.push("  Example: `value.clone()` or `&value`".to_string());
    }

    if error_text.contains("borrowed value does not live long enough") {
        suggestions.push("  Fix: Ensure the borrowed value outlives the reference.".to_string());
        suggestions.push("  Example: Move the value definition outside the inner scope.".to_string());
    }

    if error_text.contains("lifetime mismatch") {
        suggestions.push("  Fix: Add explicit lifetime annotations.".to_string());
        suggestions.push("  Example: `fn foo<'a>(x: &'a str) -> &'a str`".to_string());
    }

    if error_text.contains("use after free") || error_text.contains("dangling") {
        suggestions.push("  Fix: The value is dropped before its reference. Reorder the code.".to_string());
    }

    if error_text.contains("cannot borrow") && error_text.contains("as mutable more than once") {
        suggestions.push("  Fix: Use `RefCell` for runtime borrow checking, or restructure to avoid simultaneous mutable references.".to_string());
        suggestions.push("  Example: `let cell = RefCell::new(value);`".to_string());
    }

    if suggestions.is_empty() {
        suggestions.push("  No specific pattern matched. General advice: check ownership rules, lifetimes, and mutability.".to_string());
    }

    suggestions
}

/// 生成修复建议
fn suggest_fix(error: &str) -> Option<String> {
    let suggestions = analyze_borrow_errors(error);
    if suggestions.is_empty() {
        None
    } else {
        Some(suggestions.join("\n"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_immutable_borrow() {
        let err = "cannot borrow `x` as immutable because it is also borrowed as mutable";
        let suggestions = analyze_borrow_errors(err);
        assert!(!suggestions.is_empty());
        assert!(suggestions[0].contains("mut"));
    }

    #[test]
    fn test_move_error() {
        let err = "cannot move out of `value` because it is borrowed";
        let suggestions = analyze_borrow_errors(err);
        assert!(!suggestions.is_empty());
        assert!(suggestions[0].contains("Clone"));
    }

    #[test]
    fn test_lifetime() {
        let err = "borrowed value does not live long enough";
        let suggestions = analyze_borrow_errors(err);
        assert!(!suggestions.is_empty());
        assert!(suggestions[0].contains("lives"));
    }
}