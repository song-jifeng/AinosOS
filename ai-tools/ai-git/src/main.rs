// Ainos AI Git - 语义版本控制
// AI 增强的版本控制工具

use clap::{Parser, Subcommand};
use std::io::{self, Write};
use std::process::Command;

mod diff;
mod merge;

// ================================================================
// CLI Structure
// ================================================================

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

// ================================================================
// Diff Analysis Types
// ================================================================

/// Conventional commit type.
#[derive(Debug, Clone, Copy, PartialEq)]
enum CommitType {
    Feat,
    Fix,
    Chore,
    Refactor,
    Docs,
    Test,
    Style,
    Perf,
    Revert,
}

impl CommitType {
    fn as_str(&self) -> &'static str {
        match self {
            CommitType::Feat => "feat",
            CommitType::Fix => "fix",
            CommitType::Chore => "chore",
            CommitType::Refactor => "refactor",
            CommitType::Docs => "docs",
            CommitType::Test => "test",
            CommitType::Style => "style",
            CommitType::Perf => "perf",
            CommitType::Revert => "revert",
        }
    }
}

/// Analysis of a single file's diff.
#[derive(Debug, Default)]
struct DiffFile {
    path: String,
    additions: usize,
    deletions: usize,
    functions_added: Vec<String>,
    functions_removed: Vec<String>,
    structs_added: Vec<String>,
    structs_removed: Vec<String>,
    imports_added: Vec<String>,
    tests_added: Vec<String>,
    doc_comments_added: usize,
    is_new_file: bool,
    is_deleted_file: bool,
}

/// Full analysis of a diff.
#[derive(Debug, Default)]
struct DiffAnalysis {
    files: Vec<DiffFile>,
    total_additions: usize,
    total_deletions: usize,
    has_breaking_changes: bool,
}

// ================================================================
// Entry Point
// ================================================================

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

// ================================================================
// Commit Handler
// ================================================================

/// Handle the `commit` subcommand.
async fn handle_commit(auto: bool, message: Option<String>) -> anyhow::Result<()> {
    // 1. Check git availability
    check_git_available()?;

    // 2. Get staged diff
    let diff_text = get_staged_diff()?;

    // 3. Direct message mode (non-interactive)
    if !auto {
        if let Some(msg) = message {
            do_commit(&msg)?;
        }
        return Ok(());
    }

    // 4. Auto mode: generate commit message
    let generated = if let Some(provided_msg) = message {
        // If both --auto and -m are given, use -m as the message but still
        // show it for confirmation before committing
        provided_msg
    } else {
        println!("[ai-git] Analyzing changes...");
        let analysis = parse_diff(&diff_text);
        let msg = generate_commit_message(&analysis);
        println!();
        msg
    };

    // 5. Interactive confirmation
    interactive_commit(&generated)
}

/// Check if git is available on the system. Returns a user-friendly error
/// if git is not found or not functional.
fn check_git_available() -> anyhow::Result<()> {
    match Command::new("git").arg("--version").output() {
        Ok(output) if output.status.success() => Ok(()),
        Ok(_) => anyhow::bail!(
            "git is installed but returned an error.\n\
             Suggestion: Run `git --version` to diagnose the issue."
        ),
        Err(e) => {
            if e.kind() == io::ErrorKind::NotFound {
                anyhow::bail!(
                    "git is not installed or not in PATH.\n\
                     Suggestion: Install git from https://git-scm.com/downloads\n\
                     Or use a package manager: `apt install git`, `brew install git`, etc."
                );
            }
            anyhow::bail!("Failed to run git: {}. Check your git installation.", e);
        }
    }
}

/// Get the staged diff (`git diff --cached`). Returns a detailed error
/// message when no changes are staged.
fn get_staged_diff() -> anyhow::Result<String> {
    let output = Command::new("git")
        .args(["diff", "--cached"])
        .output()
        .map_err(|e| anyhow::anyhow!("Failed to run git diff: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        if !stderr.trim().is_empty() {
            anyhow::bail!("git error: {}", stderr.trim());
        }
        // No staged changes -- give helpful suggestions
        return suggest_git_commands();
    }

    let diff_text = String::from_utf8_lossy(&output.stdout).to_string();

    if diff_text.trim().is_empty() {
        return suggest_git_commands();
    }

    Ok(diff_text)
}

/// Check git status and suggest appropriate commands when there are
/// no staged changes.
fn suggest_git_commands() -> anyhow::Result<String> {
    let status = Command::new("git")
        .args(["status", "--porcelain"])
        .output()
        .ok();

    if let Some(status_out) = status {
        let status_text = String::from_utf8_lossy(&status_out.stdout);
        let status_text = status_text.trim();

        if status_text.is_empty() {
            anyhow::bail!(
                "No changes found in the working directory. Nothing to commit."
            );
        }

        let lines: Vec<&str> = status_text.lines().collect();
        let has_staged = lines.iter().any(|l| {
            l.starts_with('M') || l.starts_with('A') || l.starts_with('D')
                || l.starts_with('R') || l.starts_with('C')
        });
        let has_unstaged = lines.iter().any(|l| {
            l.starts_with(' ') || l.starts_with("??") || l.starts_with(" M")
                || l.starts_with(" D") || l.starts_with(" A")
        });

        if has_staged {
            // This is unexpected -- staged changes exist but diff --cached was empty
            anyhow::bail!(
                "Unexpected: staged changes detected but diff is empty.\n\
                 Suggestion: Try `git status` to see what is staged."
            );
        }

        if has_unstaged {
            let untracked = lines.iter().any(|l| l.starts_with("??"));
            let modified = lines.iter().any(|l| l.starts_with(' ') || l.starts_with(" M") || l.starts_with(" D"));

            let mut msg = String::from("No staged changes found.");
            if modified && untracked {
                msg.push_str(
                    "\n  Unstaged changes and untracked files exist.\n\
                     Suggestion: Stage them with `git add <file>` or `git add -A`.",
                );
            } else if modified {
                msg.push_str(
                    "\n  Unstaged changes exist.\n\
                     Suggestion: Stage them with `git add <file>` or `git add -A`.",
                );
            } else if untracked {
                msg.push_str(
                    "\n  Untracked files exist.\n\
                     Suggestion: Stage them with `git add <file>` or `git add -A`.",
                );
            }
            anyhow::bail!(msg);
        }

        anyhow::bail!("No changes found. Nothing to commit.");
    }

    anyhow::bail!(
        "No staged changes found.\n\
         Suggestion: Stage your changes first with `git add <file>` or `git add -A`."
    );
}

/// Execute `git commit -m "<message>"`.
fn do_commit(message: &str) -> anyhow::Result<()> {
    let output = Command::new("git")
        .args(["commit", "-m", message])
        .output()?;

    if output.status.success() {
        let stdout = String::from_utf8_lossy(&output.stdout);
        let trimmed = stdout.trim();
        if !trimmed.is_empty() {
            println!("{}", trimmed);
        } else {
            println!("[ai-git] Commit created successfully");
        }
        Ok(())
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("Commit failed: {}", stderr.trim());
    }
}

/// Show the generated message and ask for confirmation / editing.
fn interactive_commit(generated: &str) -> anyhow::Result<()> {
    println!("[ai-git] Suggested commit message:");
    println!("{}", generated);
    println!();

    loop {
        print!("Confirm? [Y/n/e] ");
        io::stdout().flush()?;

        let mut input = String::new();
        io::stdin().read_line(&mut input)?;
        let input = input.trim().to_lowercase();

        match input.as_str() {
            "" | "y" | "yes" => {
                return do_commit(generated);
            }
            "n" | "no" => {
                println!("[ai-git] Commit aborted.");
                return Ok(());
            }
            "e" | "edit" => {
                let edited = edit_message(generated)?;
                if edited.trim().is_empty() {
                    println!("[ai-git] Empty message, aborting commit.");
                    return Ok(());
                }
                println!();
                return do_commit(&edited);
            }
            other => {
                // If the user types something else, prompt again
                if other.is_empty() {
                    return do_commit(generated);
                }
                println!("Please enter 'y' (confirm), 'n' (abort), or 'e' (edit).");
            }
        }
    }
}

/// Open an editor to allow the user to modify the generated message.
///
/// Uses `$EDITOR`, `$VISUAL`, or a platform-appropriate fallback.
fn edit_message(default: &str) -> anyhow::Result<String> {
    let editor = std::env::var("EDITOR")
        .or_else(|_| std::env::var("VISUAL"))
        .unwrap_or_else(|_| {
            if cfg!(target_os = "windows") {
                "notepad".to_string()
            } else {
                "vi".to_string()
            }
        });

    // Write the default message to a temporary file
    let tmp_dir = std::env::temp_dir();
    let tmp_file = tmp_dir.join("ai-git-commit-msg.txt");
    std::fs::write(&tmp_file, default)?;

    // Open the editor
    let status = Command::new(&editor)
        .arg(&tmp_file)
        .status()
        .map_err(|e| {
            if e.kind() == io::ErrorKind::NotFound {
                anyhow::anyhow!(
                    "Editor '{}' not found.\n\
                     Set the EDITOR environment variable, or type your message manually.\n\
                     Current message: {}",
                    editor,
                    default
                )
            } else {
                anyhow::anyhow!("Failed to open editor '{}': {}", editor, e)
            }
        })?;

    if !status.success() {
        anyhow::bail!("Editor exited with error (status: {})", status);
    }

    // Read back the edited message
    let edited = std::fs::read_to_string(&tmp_file)?;
    let _ = std::fs::remove_file(&tmp_file);
    Ok(edited.trim().to_string())
}

// ================================================================
// Diff Parsing Engine
// ================================================================

/// Parse a git diff text and extract semantic information:
/// function additions/removals, struct/type changes, imports, tests, etc.
fn parse_diff(diff: &str) -> DiffAnalysis {
    let mut analysis = DiffAnalysis::default();
    let mut current_file: Option<DiffFile> = None;

    for line in diff.lines() {
        // File header: "diff --git a/oldpath b/newpath"
        if line.starts_with("diff --git ") {
            flush_file(&mut analysis, &mut current_file);

            let parts: Vec<&str> = line.splitn(4, ' ').collect();
            if parts.len() >= 4 {
                let new_path = parts[3].trim_start_matches("b/");
                current_file = Some(DiffFile {
                    path: new_path.to_string(),
                    ..Default::default()
                });
            }
            continue;
        }

        // New file
        if line.starts_with("new file mode") {
            if let Some(ref mut file) = current_file {
                file.is_new_file = true;
            }
            continue;
        }

        // Deleted file
        if line.starts_with("deleted file mode") {
            if let Some(ref mut file) = current_file {
                file.is_deleted_file = true;
            }
            continue;
        }

        // Hunk header, metadata lines -- skip
        if line.starts_with("@@") || line.starts_with("--- ") || line.starts_with("+++ ") || line.starts_with("index ") {
            continue;
        }

        // Process added lines
        if line.starts_with('+') && !line.starts_with("+++") {
            if let Some(ref mut file) = current_file {
                file.additions += 1;
                let content = &line[1..];

                // Detect function additions
                if is_function_definition(content) {
                    if let Some(name) = extract_function_name(content) {
                        file.functions_added.push(name);
                    }
                }

                // Detect struct/type additions
                if is_struct_definition(content) {
                    if let Some(name) = extract_struct_name(content) {
                        file.structs_added.push(name);
                    }
                }

                // Detect import additions
                if is_import_line(content) {
                    file.imports_added.push(content.trim().to_string());
                }

                // Detect test function additions
                if content.trim().starts_with("fn test_") || content.trim().starts_with("pub fn test_") {
                    if let Some(name) = extract_function_name(content) {
                        file.tests_added.push(name);
                    }
                }
                // Also detect #[test] followed by a function
                if content.trim() == "#[test]" || content.trim().starts_with("#[test(") {
                    // The next function on the next line will be a test --
                    // we handle this via the general function detection above
                }

                // Detect doc comment additions
                if content.trim_start().starts_with("///") || content.trim_start().starts_with("//!") {
                    file.doc_comments_added += 1;
                }
            }
        } else if line.starts_with('-') && !line.starts_with("---") {
            // Process removed lines
            if let Some(ref mut file) = current_file {
                file.deletions += 1;
                let content = &line[1..];

                // Detect function removals
                if is_function_definition(content) {
                    if let Some(name) = extract_function_name(content) {
                        file.functions_removed.push(name);
                    }
                }

                // Detect struct/type removals
                if is_struct_definition(content) {
                    if let Some(name) = extract_struct_name(content) {
                        file.structs_removed.push(name);
                    }
                }
            }
        }
    }

    // Flush the last file
    flush_file(&mut analysis, &mut current_file);

    // Detect breaking changes: removal of public API items
    analysis.has_breaking_changes = analysis.files.iter().any(|f| {
        !f.functions_removed.is_empty() || !f.structs_removed.is_empty()
    });

    analysis
}

/// Flush the current in-progress file into the analysis accumulator.
fn flush_file(analysis: &mut DiffAnalysis, current_file: &mut Option<DiffFile>) {
    if let Some(file) = current_file.take() {
        analysis.total_additions += file.additions;
        analysis.total_deletions += file.deletions;
        analysis.files.push(file);
    }
}

/// Check if a line is a function/method definition in any of the
/// supported languages.
fn is_function_definition(line: &str) -> bool {
    let trimmed = line.trim();
    // Rust
    trimmed.starts_with("fn ")
        || trimmed.starts_with("pub fn ")
        || trimmed.starts_with("pub(crate) fn ")
        || trimmed.starts_with("pub(super) fn ")
        || trimmed.starts_with("unsafe fn ")
        || trimmed.starts_with("pub unsafe fn ")
        || trimmed.starts_with("async fn ")
        || trimmed.starts_with("pub async fn ")
    // Python
        || trimmed.starts_with("def ")
        || trimmed.starts_with("async def ")
    // JavaScript / TypeScript
        || trimmed.starts_with("function ")
        || trimmed.starts_with("async function ")
        || trimmed.starts_with("export function ")
        || trimmed.starts_with("export async function ")
        || trimmed.starts_with("export default function ")
    // Go
        || trimmed.starts_with("func ")
    // Java / C# / C++ (heuristic: access modifier + parens)
        || (trimmed.contains('(') && trimmed.contains(')')
            && (trimmed.starts_with("public ")
                || trimmed.starts_with("private ")
                || trimmed.starts_with("protected ")
                || trimmed.starts_with("static ")
                || trimmed.starts_with("virtual ")
                || trimmed.starts_with("override ")
                || trimmed.starts_with("abstract ")))
}

/// Check if a line is a struct / class / enum / trait / type definition.
fn is_struct_definition(line: &str) -> bool {
    let trimmed = line.trim();
    trimmed.starts_with("struct ")
        || trimmed.starts_with("pub struct ")
        || trimmed.starts_with("pub(crate) struct ")
        || trimmed.starts_with("enum ")
        || trimmed.starts_with("pub enum ")
        || trimmed.starts_with("trait ")
        || trimmed.starts_with("pub trait ")
        || trimmed.starts_with("class ")
        || trimmed.starts_with("interface ")
        || trimmed.starts_with("type ")
        || trimmed.starts_with("pub type ")
}

/// Check if a line is an import / use / include statement.
fn is_import_line(line: &str) -> bool {
    let trimmed = line.trim();
    trimmed.starts_with("use ")
        || trimmed.starts_with("pub use ")
        || trimmed.starts_with("pub(crate) use ")
        || trimmed.starts_with("import ")
        || trimmed.starts_with("#include")
        || trimmed.starts_with("require(")
        || trimmed.starts_with("from ")
}

/// Extract a function/method name from a definition line.
fn extract_function_name(line: &str) -> Option<String> {
    let trimmed = line.trim();
    let after_keyword = trimmed
        .strip_prefix("pub async fn ")
        .or_else(|| trimmed.strip_prefix("pub unsafe fn "))
        .or_else(|| trimmed.strip_prefix("pub(crate) fn "))
        .or_else(|| trimmed.strip_prefix("pub(super) fn "))
        .or_else(|| trimmed.strip_prefix("pub fn "))
        .or_else(|| trimmed.strip_prefix("async fn "))
        .or_else(|| trimmed.strip_prefix("unsafe fn "))
        .or_else(|| trimmed.strip_prefix("fn "))
        .or_else(|| trimmed.strip_prefix("export default function "))
        .or_else(|| trimmed.strip_prefix("export async function "))
        .or_else(|| trimmed.strip_prefix("export function "))
        .or_else(|| trimmed.strip_prefix("async function "))
        .or_else(|| trimmed.strip_prefix("function "))
        .or_else(|| trimmed.strip_prefix("def "))
        .or_else(|| trimmed.strip_prefix("async def "))
        .or_else(|| trimmed.strip_prefix("func "))?;

    // The name ends at '(', '<', whitespace, or ':' (for Python)
    let name_end = after_keyword
        .find(|c: char| c == '(' || c == '<' || c == ' ' || c == ':')
        .unwrap_or(after_keyword.len());
    let name = after_keyword[..name_end].trim().to_string();
    if name.is_empty() { None } else { Some(name) }
}

/// Extract a struct/class/enum/trait name from a definition line.
fn extract_struct_name(line: &str) -> Option<String> {
    let trimmed = line.trim();
    let after_keyword = trimmed
        .strip_prefix("pub struct ")
        .or_else(|| trimmed.strip_prefix("pub(crate) struct "))
        .or_else(|| trimmed.strip_prefix("pub enum "))
        .or_else(|| trimmed.strip_prefix("pub trait "))
        .or_else(|| trimmed.strip_prefix("pub type "))
        .or_else(|| trimmed.strip_prefix("struct "))
        .or_else(|| trimmed.strip_prefix("enum "))
        .or_else(|| trimmed.strip_prefix("trait "))
        .or_else(|| trimmed.strip_prefix("type "))
        .or_else(|| trimmed.strip_prefix("class "))
        .or_else(|| trimmed.strip_prefix("interface "))?;

    // The name ends at '<', whitespace, '{', or ':'
    let name_end = after_keyword
        .find(|c: char| c == '<' || c == ' ' || c == '{' || c == ':')
        .unwrap_or(after_keyword.len());
    let name = after_keyword[..name_end].trim().to_string();
    if name.is_empty() { None } else { Some(name) }
}

// ================================================================
// Commit Message Generation
// ================================================================

/// Generate a Conventional Commits message from the diff analysis.
fn generate_commit_message(analysis: &DiffAnalysis) -> String {
    let commit_type = detect_commit_type(analysis);
    let scope = detect_scope(analysis);
    let description = generate_description(analysis, commit_type);
    let breaking = analysis.has_breaking_changes;

    // Build the first line: type[(scope)][!]: description
    let mut first_line = String::from(commit_type.as_str());
    if let Some(ref s) = scope {
        first_line.push('(');
        first_line.push_str(s);
        first_line.push(')');
    }
    if breaking {
        first_line.push('!');
    }
    first_line.push_str(": ");
    first_line.push_str(&description);

    // Build the body with details
    let body = generate_body(analysis);

    if body.is_empty() {
        first_line
    } else {
        format!("{}\n\n{}", first_line, body)
    }
}

/// Detect the Conventional Commit type based on the diff analysis.
fn detect_commit_type(analysis: &DiffAnalysis) -> CommitType {
    let mut has_new_features = false;
    let mut has_tests = false;
    let mut has_docs = false;

    for file in &analysis.files {
        // New functions or structs = feature
        if !file.functions_added.is_empty() || !file.structs_added.is_empty() {
            has_new_features = true;
        }

        // Test files
        if file.path.contains("test")
            || file.path.ends_with("_test.rs")
            || file.path.ends_with(".spec.ts")
            || file.path.ends_with(".test.ts")
            || file.path.ends_with("_test.py")
            || file.path.ends_with("_test.go")
        {
            has_tests = true;
        }
        if !file.tests_added.is_empty() {
            has_tests = true;
        }

        // Documentation files
        if file.path.ends_with(".md")
            || file.path.starts_with("docs/")
            || file.path.contains("README")
            || file.path == "CHANGELOG"
            || file.path == "CONTRIBUTING"
        {
            has_docs = true;
        }
        if file.doc_comments_added > 3 {
            has_docs = true;
        }
    }

    // Priority-based detection
    if has_new_features {
        // If only test files changed AND we have new features, still feat
        return CommitType::Feat;
    }

    if has_tests {
        return CommitType::Test;
    }

    if has_docs {
        return CommitType::Docs;
    }

    // Check for fix keywords in removed function names
    for file in &analysis.files {
        for fn_removed in &file.functions_removed {
            let lower = fn_removed.to_lowercase();
            if lower.contains("fix") || lower.contains("bug") || lower.contains("error") || lower.contains("issue") {
                return CommitType::Fix;
            }
        }
    }

    // Config / build file changes
    for file in &analysis.files {
        if file.path == "Cargo.toml"
            || file.path == "Cargo.lock"
            || file.path == "package.json"
            || file.path == "package-lock.json"
            || file.path == "Makefile"
            || file.path == "Dockerfile"
            || file.path.starts_with(".github/")
            || file.path == "build.rs"
            || file.path == "CMakeLists.txt"
            || file.path == "go.mod"
            || file.path == "go.sum"
        {
            return CommitType::Chore;
        }
        // Dependency changes
        if file.imports_added.iter().any(|i| i.contains("dep-") || i.contains("version") || i.contains("dependency")) {
            return CommitType::Chore;
        }
    }

    // Size-based heuristics
    let total_change: usize = analysis.files.iter().map(|f| f.additions + f.deletions).sum();

    // Very small changes are likely fix or chore
    if total_change <= 10 {
        let just_imports = analysis.files.iter().all(|f| {
            f.additions == f.imports_added.len()
                && f.functions_added.is_empty()
                && f.structs_added.is_empty()
                && f.functions_removed.is_empty()
                && f.structs_removed.is_empty()
        });
        if just_imports {
            return CommitType::Chore;
        }
        return CommitType::Fix;
    }

    // Everything else is refactor
    CommitType::Refactor
}

/// Detect the scope (module / component) from the changed files.
fn detect_scope(analysis: &DiffAnalysis) -> Option<String> {
    let paths: Vec<&str> = analysis.files.iter().map(|f| f.path.as_str()).collect();

    if paths.is_empty() {
        return None;
    }

    // Single file: use its logical scope
    if paths.len() == 1 {
        return extract_scope_from_path(paths[0]);
    }

    // Multiple files: try to find a common directory
    let dirs: Vec<&str> = paths
        .iter()
        .map(|p| {
            if let Some(idx) = p.rfind('/') {
                &p[..idx]
            } else {
                "." // root directory
            }
        })
        .collect();

    if dirs.is_empty() {
        return None;
    }

    // All files in the same directory: use that directory's last component
    let first_dir = dirs[0];
    if dirs.iter().all(|d| *d == first_dir) && !first_dir.is_empty() && first_dir != "." {
        if let Some(idx) = first_dir.rfind('/') {
            return Some(first_dir[idx + 1..].to_string());
        }
        return Some(first_dir.to_string());
    }

    // All files share the same top-level directory (e.g. all under "src/")
    let top_components: Vec<&str> = paths
        .iter()
        .filter_map(|p| p.split('/').next())
        .collect();
    if !top_components.is_empty() {
        let first = top_components[0];
        if top_components.iter().all(|c| *c == first) {
            return Some(first.to_string());
        }
    }

    // If one of the changed files is a core entry point, use "core"
    if paths.contains(&"src/main.rs")
        || paths.contains(&"main.rs")
        || paths.contains(&"src/lib.rs")
        || paths.contains(&"lib.rs")
    {
        return Some("core".to_string());
    }

    // Fallback: use the scope of the file with the largest change set
    let largest_file = analysis
        .files
        .iter()
        .max_by_key(|f| f.additions + f.deletions)
        .map(|f| f.path.as_str());
    if let Some(largest) = largest_file {
        return extract_scope_from_path(largest);
    }

    None
}

/// Extract a scope name from a single file path.
fn extract_scope_from_path(path: &str) -> Option<String> {
    // Well-known special paths
    match path {
        p if p == "Cargo.toml" || p == "Cargo.lock" => return Some("deps".to_string()),
        p if p == "package.json" || p == "package-lock.json" => return Some("deps".to_string()),
        p if p == "go.mod" || p == "go.sum" => return Some("deps".to_string()),
        p if p == "build.rs" => return Some("build".to_string()),
        p if p == "Makefile" || p == "CMakeLists.txt" => return Some("build".to_string()),
        _ => {}
    }

    // CI / GitHub workflows
    if path.starts_with(".github/") {
        return Some("ci".to_string());
    }

    // Documentation
    if path.starts_with("docs/") {
        let rest = path.strip_prefix("docs/").unwrap_or("");
        if let Some(idx) = rest.find('/') {
            return Some(rest[..idx].to_string());
        }
        return Some("docs".to_string());
    }

    // Tests
    if path.starts_with("tests/") || path.ends_with("_test.rs") || path.ends_with(".spec.ts") || path.ends_with("_test.py") {
        return Some("tests".to_string());
    }

    // Strip the "src/" prefix
    let trimmed = if path.starts_with("src/") {
        &path[4..]
    } else {
        path
    };

    // Extract the file name (without extension)
    let name = if let Some(idx) = trimmed.rfind('/') {
        &trimmed[idx + 1..]
    } else {
        trimmed
    };
    let name = name.rsplit_once('.').map(|(n, _)| n).unwrap_or(name);

    // If the name is "mod" or "lib", use the parent directory instead
    if name == "mod" || name == "lib" {
        if let Some(idx) = trimmed.rfind('/') {
            let parent = &trimmed[..idx];
            if let Some(slash) = parent.rfind('/') {
                return Some(parent[slash + 1..].to_string());
            }
            return Some(parent.to_string());
        }
        return None;
    }

    if name.is_empty() {
        return None;
    }

    Some(name.to_string())
}

/// Generate a short, descriptive first line for the commit message.
fn generate_description(analysis: &DiffAnalysis, commit_type: CommitType) -> String {
    let file_count = analysis.files.len();

    match commit_type {
        CommitType::Feat => {
            // Describe what was added
            let mut descriptions: Vec<String> = Vec::new();

            for file in &analysis.files {
                for fn_name in &file.functions_added {
                    descriptions.push(format!("add `{}`", fn_name));
                }
                for struct_name in &file.structs_added {
                    descriptions.push(format!("add `{}`", struct_name));
                }
            }

            if !descriptions.is_empty() {
                descriptions.truncate(3);
                if descriptions.len() <= 2 {
                    return descriptions.join(", ");
                }
                return format!("{}, and {} more", descriptions[0], descriptions.len() - 1);
            }

            format!("add new features across {} file(s)", file_count)
        }
        CommitType::Fix => {
            // Describe what was removed/fixed
            let mut descriptions: Vec<String> = Vec::new();

            for file in &analysis.files {
                for fn_name in &file.functions_removed {
                    descriptions.push(format!("remove `{}`", fn_name));
                }
            }

            if !descriptions.is_empty() {
                descriptions.truncate(2);
                return descriptions.join(", ");
            }

            format!("fix issues in {} file(s)", file_count)
        }
        CommitType::Refactor => {
            for file in &analysis.files {
                let fn_count = file.functions_removed.len().max(file.functions_added.len());
                if fn_count > 0 {
                    return format!("refactor {} function(s) in {}", fn_count, file.path);
                }
            }
            format!(
                "refactor {} file(s) (+{} -{})",
                file_count, analysis.total_additions, analysis.total_deletions
            )
        }
        CommitType::Docs => {
            let doc_files: Vec<&str> = analysis
                .files
                .iter()
                .filter(|f| f.path.ends_with(".md") || f.path.starts_with("docs/"))
                .map(|f| f.path.as_str())
                .collect();
            if !doc_files.is_empty() {
                format!("update documentation ({} file(s))", doc_files.len())
            } else {
                format!("update doc comments in {} file(s)", file_count)
            }
        }
        CommitType::Test => {
            let test_count: usize = analysis.files.iter().map(|f| f.tests_added.len()).sum();
            if test_count > 0 {
                format!("add {} test(s) across {} file(s)", test_count, file_count)
            } else {
                format!("update test files ({} file(s))", file_count)
            }
        }
        CommitType::Style => {
            format!("format {} file(s)", file_count)
        }
        CommitType::Perf => {
            format!("improve performance in {} file(s)", file_count)
        }
        CommitType::Revert => {
            format!("revert changes in {} file(s)", file_count)
        }
        CommitType::Chore => {
            // Check for specific chores
            for file in &analysis.files {
                if file.path == "Cargo.toml" || file.path == "Cargo.lock" {
                    if !file.imports_added.is_empty() {
                        return "update dependencies".to_string();
                    }
                    return format!("update {}", file.path);
                }
                if file.path == "package.json" {
                    return "update npm dependencies".to_string();
                }
                if file.path.starts_with(".github/") {
                    return "update CI workflow".to_string();
                }
                if file.path == "go.mod" || file.path == "go.sum" {
                    return "update Go dependencies".to_string();
                }
            }
            format!(
                "update {} file(s) (+{} -{})",
                file_count, analysis.total_additions, analysis.total_deletions
            )
        }
    }
}

/// Generate the detailed body of the commit message.
fn generate_body(analysis: &DiffAnalysis) -> String {
    let mut body = String::new();

    for file in &analysis.files {
        let mut file_items: Vec<String> = Vec::new();

        for fn_name in &file.functions_added {
            file_items.push(format!("add `{}`", fn_name));
        }
        for fn_name in &file.functions_removed {
            file_items.push(format!("remove `{}`", fn_name));
        }
        for struct_name in &file.structs_added {
            file_items.push(format!("add `{}`", struct_name));
        }
        for struct_name in &file.structs_removed {
            file_items.push(format!("remove `{}`", struct_name));
        }
        for test_name in &file.tests_added {
            file_items.push(format!("add test `{}`", test_name));
        }
        if file.additions > 0 || file.deletions > 0 {
            file_items.push(format!("(+{} -{})", file.additions, file.deletions));
        }

        if !file_items.is_empty() {
            body.push_str(&format!("  - {}: ", file.path));
            body.push_str(&file_items.join(", "));
            body.push('\n');
        }
    }

    // Summary line for multi-file changes
    if analysis.files.len() > 1 {
        body.push_str(&format!(
            "\n  {} file(s) changed, {} insertions(+), {} deletions(-)",
            analysis.files.len(),
            analysis.total_additions,
            analysis.total_deletions
        ));
    }

    // Breaking change warning
    if analysis.has_breaking_changes {
        body.push_str(
            "\n\n  BREAKING CHANGE: public API items have been removed or modified.",
        );
    }

    body.trim().to_string()
}

// ================================================================
// Merge Handler
// ================================================================

/// Handle the `merge` subcommand.
async fn handle_merge(branch: &str, auto_resolve: bool, strategy: &str) -> anyhow::Result<()> {
    println!("[ai-git] Merging branch: {} (strategy: {})", branch, strategy);
    let strat = merge::MergeStrategy::from_str(strategy);

    if auto_resolve {
        // First try a plain `git merge`
        let merge_output = Command::new("git")
            .args(["merge", branch])
            .output()?;

        if merge_output.status.success() {
            println!("[ai-git] Merge completed successfully");
            let stdout = String::from_utf8_lossy(&merge_output.stdout);
            if !stdout.trim().is_empty() {
                println!("{}", stdout.trim());
            }
            return Ok(());
        }

        // Merge conflict detected -- attempt AI resolution
        println!(
            "[ai-git] Conflict detected, attempting AI resolution (strategy: {})...",
            strategy
        );

        let conflicts = get_conflict_files()?;
        if conflicts.is_empty() {
            let stderr = String::from_utf8_lossy(&merge_output.stderr);
            anyhow::bail!(
                "Merge failed with no conflict files found.\nstdout: {}\nstderr: {}",
                String::from_utf8_lossy(&merge_output.stdout).trim(),
                stderr.trim(),
            );
        }

        for file in &conflicts {
            println!("[ai-git] Resolving conflict in: {}", file);
            resolve_conflict_file(file, strat)?;
        }

        // Stage all resolved files
        let add_output = Command::new("git").args(["add", "-A"]).output()?;
        if !add_output.status.success() {
            anyhow::bail!(
                "Failed to stage resolved files: {}",
                String::from_utf8_lossy(&add_output.stderr)
            );
        }

        // Commit the merge result
        let msg = format!("Merge branch '{}' (AI resolved)", branch);
        let commit_output = Command::new("git")
            .args(["commit", "-m", &msg, "--no-edit"])
            .output()?;

        if commit_output.status.success() {
            println!("[ai-git] Merge conflicts resolved by AI");
        } else {
            let stderr = String::from_utf8_lossy(&commit_output.stderr);
            if stderr.contains("nothing to commit") {
                println!("[ai-git] Merge conflicts resolved (all changes already staged)");
            } else {
                anyhow::bail!("Merge commit failed: {}", stderr.trim());
            }
        }
    } else {
        // Non-auto-resolve: run plain `git merge`
        let merge_output = Command::new("git").args(["merge", branch]).output()?;

        if merge_output.status.success() {
            println!("[ai-git] Merge completed successfully");
            let stdout = String::from_utf8_lossy(&merge_output.stdout);
            if !stdout.trim().is_empty() {
                println!("{}", stdout.trim());
            }
        } else {
            let stderr = String::from_utf8_lossy(&merge_output.stderr);
            println!("[ai-git] Merge conflicts detected. Use --auto-resolve for AI resolution.");
            if !stderr.trim().is_empty() {
                println!("{}", stderr.trim());
            }
        }
    }

    Ok(())
}

/// Get the list of files with merge conflicts (unmerged paths).
fn get_conflict_files() -> anyhow::Result<Vec<String>> {
    let output = Command::new("git")
        .args(["diff", "--name-only", "--diff-filter=U"])
        .output()?;

    if !output.status.success() {
        anyhow::bail!(
            "Failed to get conflict files: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    let files: Vec<String> = String::from_utf8_lossy(&output.stdout)
        .lines()
        .map(|s| s.to_string())
        .filter(|s| !s.is_empty())
        .collect();

    Ok(files)
}

/// Resolve merge conflicts in a single file using the merge engine.
fn resolve_conflict_file(file: &str, strategy: merge::MergeStrategy) -> anyhow::Result<()> {
    let content = std::fs::read_to_string(file)
        .map_err(|e| anyhow::anyhow!("Failed to read '{}': {}", file, e))?;

    let result = merge::resolve_conflict_with_strategy(&content, Some(strategy), Some(file));

    let total = result.resolved + result.unresolved;
    println!(
        "[ai-git]   {} conflicts: {} resolved, {} unresolved",
        total, result.resolved, result.unresolved
    );

    for resolution in &result.resolutions {
        println!(
            "[ai-git]   Conflict #{}: {} ({})",
            resolution.id,
            if resolution.resolved { "resolved" } else { "unresolved" },
            resolution.reason
        );
    }

    std::fs::write(file, &result.content)
        .map_err(|e| anyhow::anyhow!("Failed to write '{}': {}", file, e))?;

    Ok(())
}

// ================================================================
// Diff Handler
// ================================================================

/// Handle the `diff` subcommand.
async fn handle_diff(range: Option<&str>, semantic: bool) -> anyhow::Result<()> {
    let mut args = vec!["diff"];
    if let Some(r) = range {
        args.push(r);
    }

    let output = Command::new("git").args(&args).output()?;

    if !output.status.success() {
        anyhow::bail!(
            "git diff failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

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

// ================================================================
// Log Handler
// ================================================================

/// Handle the `log` subcommand.
async fn handle_log(count: usize) -> anyhow::Result<()> {
    let output = Command::new("git")
        .args(["log", &format!("-{}", count), "--oneline", "--stat"])
        .output()?;

    if output.status.success() {
        let stdout = String::from_utf8_lossy(&output.stdout);
        if !stdout.trim().is_empty() {
            println!("{}", stdout.trim());
        }
        Ok(())
    } else {
        anyhow::bail!(
            "git log failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }
}

// ================================================================
// Analyze Handler
// ================================================================

/// Handle the `analyze` subcommand.
async fn handle_analyze(range: Option<&str>) -> anyhow::Result<()> {
    let mut args = vec!["diff"];
    if let Some(r) = range {
        args.push(r);
    }

    let output = Command::new("git").args(&args).output()?;

    if !output.status.success() {
        anyhow::bail!(
            "git diff failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    let diff_text = String::from_utf8_lossy(&output.stdout);

    // Use the enhanced semantic analysis
    let analysis = parse_diff(&diff_text);
    let commit_msg = generate_commit_message(&analysis);
    let commit_type = detect_commit_type(&analysis);
    let scope = detect_scope(&analysis);

    println!("[ai-git] Change Impact Analysis:");
    println!("  Files changed:  {}", analysis.files.len());
    println!("  Insertions:     {}", analysis.total_additions);
    println!("  Deletions:      {}", analysis.total_deletions);
    println!(
        "  Net change:     {:+}",
        analysis.total_additions as isize - analysis.total_deletions as isize
    );

    // Also show the existing semantic analysis from the diff module
    let semantic = diff::analyze_diff(&diff_text);
    print!("{}", semantic);

    // Show suggested commit metadata
    println!("  Suggested type:  {}", commit_type.as_str());
    if let Some(ref s) = scope {
        println!("  Suggested scope: {}", s);
    }
    if analysis.has_breaking_changes {
        println!("  WARNING: Breaking changes detected!");
    }

    // Show the first line of the suggested commit message
    let first_line = commit_msg.lines().next().unwrap_or("");
    if !first_line.is_empty() {
        println!("\n  Suggested commit message:");
        println!("  {}", first_line);
    }

    // Show per-file semantic details
    let has_details = analysis.files.iter().any(|f| {
        !f.functions_added.is_empty()
            || !f.functions_removed.is_empty()
            || !f.structs_added.is_empty()
            || !f.structs_removed.is_empty()
            || !f.tests_added.is_empty()
    });

    if has_details {
        println!("\n  Detailed changes:");
        for file in &analysis.files {
            let mut details = Vec::new();
            if !file.functions_added.is_empty() {
                details.push(format!("+fn:{}", file.functions_added.join(",")));
            }
            if !file.functions_removed.is_empty() {
                details.push(format!("-fn:{}", file.functions_removed.join(",")));
            }
            if !file.structs_added.is_empty() {
                details.push(format!("+struct:{}", file.structs_added.join(",")));
            }
            if !file.structs_removed.is_empty() {
                details.push(format!("-struct:{}", file.structs_removed.join(",")));
            }
            if !file.tests_added.is_empty() {
                details.push(format!("+test:{}", file.tests_added.join(",")));
            }
            if !details.is_empty() {
                println!("    {}: {}", file.path, details.join("; "));
            }
        }
    }

    Ok(())
}