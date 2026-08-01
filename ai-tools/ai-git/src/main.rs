// Ainos AI Git - 语义版本控制
// AI 增强的版本控制工具

use clap::{Parser, Subcommand};

mod diff;
mod merge;

#[derive(Parser)]
#[command(name = "ai-git", version, about = "AI-enhanced version control")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// AI 生成提交信息
    Commit {
        /// 自动生成提交信息
        #[arg(short, long)]
        auto: bool,
        /// 提交信息
        #[arg(short, long)]
        message: Option<String>,
    },
    /// AI 智能合并冲突
    Merge {
        /// 要合并的分支
        branch: String,
        /// AI 自动解决冲突
        #[arg(short, long)]
        auto_resolve: bool,
        /// 合并策略: ours|theirs|union|smart|manual
        #[arg(short, long, default_value = "smart")]
        strategy: String,
    },
    /// AI 语义 diff
    Diff {
        /// 对比的提交范围
        range: Option<String>,
        /// 显示语义分析
        #[arg(short, long)]
        semantic: bool,
    },
    /// AI 分析提交历史
    Log {
        /// 显示条数
        #[arg(short, long, default_value = "10")]
        count: usize,
    },
    /// AI 分析代码变更影响
    Analyze {
        /// 提交范围
        range: Option<String>,
    },
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();

    match cli.command {
        Commands::Commit { auto, message } => {
            handle_commit(auto, message).await?;
        }
        Commands::Merge { branch, auto_resolve, strategy } => {
            handle_merge(&branch, auto_resolve, &strategy).await?;
        }
        Commands::Diff { range, semantic } => {
            handle_diff(range.as_deref(), semantic).await?;
        }
        Commands::Log { count } => {
            handle_log(count).await?;
        }
        Commands::Analyze { range } => {
            handle_analyze(range.as_deref()).await?;
        }
    }

    Ok(())
}

/// 处理提交
async fn handle_commit(auto: bool, message: Option<String>) -> anyhow::Result<()> {
    // 获取 git diff
    let diff_output = std::process::Command::new("git")
        .args(["diff", "--cached"])
        .output()?;

    if !diff_output.status.success() {
        anyhow::bail!("No staged changes found");
    }

    let diff_text = String::from_utf8_lossy(&diff_output.stdout);

    if auto {
        // 调用 AI 生成提交信息
        println!("[ai-git] Analyzing changes...");
        let ai_msg = generate_commit_message(&diff_text).await?;
        println!("[ai-git] Suggested commit message:");
        println!("{}", ai_msg);

        // 使用生成的提交信息提交
        let commit = std::process::Command::new("git")
            .args(["commit", "-m", &ai_msg])
            .output()?;

        if commit.status.success() {
            println!("[ai-git] Commit created successfully");
        } else {
            anyhow::bail!("Commit failed: {}", String::from_utf8_lossy(&commit.stderr));
        }
    } else if let Some(msg) = message {
        let commit = std::process::Command::new("git")
            .args(["commit", "-m", &msg])
            .output()?;

        if commit.status.success() {
            println!("[ai-git] Commit created successfully");
        } else {
            anyhow::bail!("Commit failed: {}", String::from_utf8_lossy(&commit.stderr));
        }
    }

    Ok(())
}

/// 生成提交信息
async fn generate_commit_message(diff: &str) -> anyhow::Result<String> {
    // 简单分析 diff 生成提交信息
    let lines: Vec<&str> = diff.lines().collect();
    let mut added = 0;
    let mut removed = 0;
    let mut files = Vec::new();

    for line in &lines {
        if line.starts_with("+++") {
            let file = line.trim_start_matches("+++ b/").trim();
            if !file.is_empty() {
                files.push(file.to_string());
            }
        } else if line.starts_with('+') && !line.starts_with("+++") {
            added += 1;
        } else if line.starts_with('-') && !line.starts_with("---") {
            removed += 1;
        }
    }

    let file_count = files.len();
    let msg = format!(
        "chore: update {} file(s) (+{} -{})\n\nFiles:\n{}",
        file_count,
        added,
        removed,
        files.iter().map(|f| format!("  - {}", f)).collect::<Vec<_>>().join("\n")
    );

    Ok(msg)
}

/// 处理合并
async fn handle_merge(branch: &str, auto_resolve: bool, strategy: &str) -> anyhow::Result<()> {
    println!("[ai-git] Merging branch: {} (strategy: {})", branch, strategy);
    let strat = merge::MergeStrategy::from_str(strategy);

    if auto_resolve {
        // 先尝试自动合并
        let merge = std::process::Command::new("git")
            .args(["merge", branch])
            .output()?;

        if merge.status.success() {
            println!("[ai-git] Merge completed successfully");
            return Ok(());
        }

        // 合并冲突，AI 尝试解决
        println!("[ai-git] Conflict detected, attempting AI resolution (strategy: {})...", strategy);
        let conflicts = get_conflict_files()?;
        for file in &conflicts {
            println!("[ai-git] Resolving conflict in: {}", file);
            resolve_conflict(file, strat)?;
        }

        // 提交合并结果
        std::process::Command::new("git")
            .args(["add", "-A"])
            .output()?;

        let msg = format!("Merge branch '{}' (AI resolved)", branch);
        std::process::Command::new("git")
            .args(["commit", "-m", &msg, "--no-edit"])
            .output()?;

        println!("[ai-git] Merge conflicts resolved by AI");
    } else {
        let merge = std::process::Command::new("git")
            .args(["merge", branch])
            .output()?;

        if merge.status.success() {
            println!("[ai-git] Merge completed successfully");
        } else {
            println!("[ai-git] Merge conflicts detected. Use --auto-resolve for AI resolution.");
            println!("{}", String::from_utf8_lossy(&merge.stderr));
        }
    }

    Ok(())
}

/// 获取冲突文件列表
fn get_conflict_files() -> anyhow::Result<Vec<String>> {
    let output = std::process::Command::new("git")
        .args(["diff", "--name-only", "--diff-filter=U"])
        .output()?;

    let files: Vec<String> = String::from_utf8_lossy(&output.stdout)
        .lines()
        .map(|s| s.to_string())
        .filter(|s| !s.is_empty())
        .collect();

    Ok(files)
}

/// 解决冲突
fn resolve_conflict(file: &str, strategy: merge::MergeStrategy) -> anyhow::Result<()> {
    let content = std::fs::read_to_string(file)?;
    let result = merge::resolve_conflict_with_strategy(
        &content, Some(strategy), Some(file));

    println!("[ai-git]   {} conflicts: {} resolved, {} unresolved",
             result.resolved + result.unresolved,
             result.resolved, result.unresolved);

    for res in &result.resolutions {
        println!("[ai-git]   Conflict #{}: {} ({})",
                 res.id,
                 if res.resolved { "resolved" } else { "unresolved" },
                 res.reason);
    }

    std::fs::write(file, &result.content)?;
    Ok(())
}

/// 处理 diff
async fn handle_diff(range: Option<&str>, semantic: bool) -> anyhow::Result<()> {
    let mut args = vec!["diff"];
    if let Some(r) = range {
        args.push(r);
    }

    let output = std::process::Command::new("git")
        .args(&args)
        .output()?;

    let diff_text = String::from_utf8_lossy(&output.stdout);

    if semantic {
        println!("[ai-git] Semantic diff analysis:");
        let analysis = diff::analyze_diff(&diff_text);
        println!("{}", analysis);
    } else {
        println!("{}", diff_text);
    }

    Ok(())
}

/// 处理日志
async fn handle_log(count: usize) -> anyhow::Result<()> {
    let output = std::process::Command::new("git")
        .args([
            "log",
            &format!("-{}", count),
            "--oneline",
            "--stat",
        ])
        .output()?;

    if output.status.success() {
        println!("{}", String::from_utf8_lossy(&output.stdout));
    }

    Ok(())
}

/// 分析变更影响
async fn handle_analyze(range: Option<&str>) -> anyhow::Result<()> {
    let mut args = vec!["diff"];
    if let Some(r) = range {
        args.push(r);
    }

    let output = std::process::Command::new("git")
        .args(&args)
        .output()?;

    let diff_text = String::from_utf8_lossy(&output.stdout);
    let analysis = diff::analyze_diff(&diff_text);

    println!("[ai-git] Change Impact Analysis:");
    println!("{}", analysis);

    Ok(())
}