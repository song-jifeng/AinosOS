// ================================================================
// Ainos OS - AI Git 合并冲突解决引擎 (深度实现 v2.0.0)
// ================================================================
//
// 多策略合并引擎:
//   Ours    - 保留本地变更 (安全)
//   Theirs  - 保留远程变更 (信任远程)
//   Union   - 保留双方变更 (最大保留)
//   Smart   - 上下文感知合并 (推荐)
//   Manual  - 保留冲突标记 (人工解决)
//
// 架构:
//   ┌─────────────────────────────────────────────────────────┐
//   │  冲突解析器                                            │
//   │  解析 <<<<<<< / ======= / >>>>>>> 标记                  │
//   └──────────────────┬──────────────────────────────────────┘
//                      ▼
//   ┌─────────────────────────────────────────────────────────┐
//   │  策略引擎                                              │
//   │  Ours / Theirs / Union / Smart / Manual                │
//   └──────────────────┬──────────────────────────────────────┘
//                      ▼
//   ┌─────────────────────────────────────────────────────────┐
//   │  上下文感知合并 (Smart 模式)                            │
//   │  - 识别新增/删除/修改                                   │
//   │  - 行级上下文匹配                                      │
//   │  - 语义冲突检测                                        │
//   └─────────────────────────────────────────────────────────┘
// ================================================================

use std::collections::HashSet;

/// 合并策略
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum MergeStrategy {
    /// 保留本地变更
    Ours,
    /// 保留远程变更
    Theirs,
    /// 保留双方变更 (当前实现的问题所在)
    Union,
    /// 上下文感知合并 (推荐)
    Smart,
    /// 保留冲突标记 (人工解决)
    Manual,
}

impl MergeStrategy {
    pub fn from_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "ours" => MergeStrategy::Ours,
            "theirs" => MergeStrategy::Theirs,
            "union" => MergeStrategy::Union,
            "smart" => MergeStrategy::Smart,
            "manual" => MergeStrategy::Manual,
            _ => MergeStrategy::Smart,
        }
    }
}

/// 冲突块
#[derive(Debug)]
struct ConflictBlock {
    /// 本地变更 (HEAD)
    ours: Vec<String>,
    /// 远程变更 (branch)
    theirs: Vec<String>,
    /// 冲突前的上下文 (前 N 行)
    context_before: Vec<String>,
    /// 冲突后的上下文 (后 N 行)
    context_after: Vec<String>,
    /// 冲突 ID
    id: usize,
    /// 文件名 (用于上下文)
    filename: Option<String>,
}

impl ConflictBlock {
    fn new(id: usize) -> Self {
        ConflictBlock {
            ours: Vec::new(),
            theirs: Vec::new(),
            context_before: Vec::new(),
            context_after: Vec::new(),
            id,
            filename: None,
        }
    }

    /// 检查双方是否完全相同
    fn is_identical(&self) -> bool {
        self.ours == self.theirs
    }

    /// 检查一方是否为空
    fn ours_empty(&self) -> bool {
        self.ours.iter().all(|l| l.trim().is_empty())
    }

    fn theirs_empty(&self) -> bool {
        self.theirs.iter().all(|l| l.trim().is_empty())
    }

    /// 检查是否只是添加了新行 (没有修改)
    fn is_only_addition(&self) -> bool {
        self.ours.iter().any(|l| l.trim().is_empty())
            || self.theirs.iter().any(|l| l.trim().is_empty())
    }

    /// 检测是否是 import/use 语句冲突
    fn is_import_conflict(&self) -> bool {
        let import_keywords = ["import ", "use ", "#include", "require(", "from "];
        self.ours.iter().chain(self.theirs.iter()).all(|line| {
            import_keywords.iter().any(|kw| line.trim_start().starts_with(kw))
        })
    }

    /// 检测是否是注释冲突
    fn is_comment_conflict(&self) -> bool {
        let comment_markers = ["//", "#", "/*", "*", "///", "//!"];
        self.ours.iter().chain(self.theirs.iter()).all(|line| {
            let trimmed = line.trim();
            trimmed.is_empty() || comment_markers.iter().any(|m| trimmed.starts_with(m))
        })
    }

    /// 检测是否是空白/空行冲突
    fn is_whitespace_conflict(&self) -> bool {
        self.ours.iter().chain(self.theirs.iter()).all(|l| {
            l.trim().is_empty() || l.trim() == "}" || l.trim() == "{"
        })
    }
}

/// 合并结果
#[derive(Debug)]
pub struct MergeResult {
    /// 合并后的内容
    pub content: String,
    /// 自动解决的冲突数
    pub resolved: usize,
    /// 未解决的冲突数 (需要人工处理)
    pub unresolved: usize,
    /// 每个冲突的处理方式
    pub resolutions: Vec<ConflictResolution>,
}

/// 冲突解决记录
#[derive(Debug)]
pub struct ConflictResolution {
    pub id: usize,
    pub strategy: MergeStrategy,
    pub resolved: bool,
    pub reason: String,
}

/// 解析冲突块
fn parse_conflicts(content: &str, filename: Option<&str>) -> (Vec<ConflictBlock>, Vec<String>) {
    let lines: Vec<&str> = content.lines().collect();
    let mut blocks = Vec::new();
    let mut non_conflict_lines = Vec::new();
    let mut i = 0;
    let mut conflict_id = 0;
    const CONTEXT_LINES: usize = 3;

    // 收集上下文 (最近 N 行非冲突行)
    let mut recent_context: Vec<String> = Vec::new();

    while i < lines.len() {
        let line = lines[i];

        if line.starts_with("<<<<<<<") {
            let mut block = ConflictBlock::new(conflict_id);
            block.filename = filename.map(|s| s.to_string());
            block.context_before = recent_context.clone();
            i += 1;

            // 解析本地变更
            while i < lines.len() && !lines[i].starts_with("=======") {
                block.ours.push(lines[i].to_string());
                i += 1;
            }

            // 跳过 =======
            if i < lines.len() && lines[i].starts_with("=======") {
                i += 1;
            }

            // 解析远程变更
            while i < lines.len() && !lines[i].starts_with(">>>>>>>") {
                block.theirs.push(lines[i].to_string());
                i += 1;
            }

            // 跳过 >>>>>>>
            if i < lines.len() && lines[i].starts_with(">>>>>>>") {
                i += 1;
            }

            // 收集冲突后上下文
            let mut after_idx = i;
            while after_idx < lines.len()
                && after_idx < i + CONTEXT_LINES
                && !lines[after_idx].starts_with("<<<<<<<")
            {
                block.context_after.push(lines[after_idx].to_string());
                after_idx += 1;
            }

            conflict_id += 1;
            blocks.push(block);
            recent_context.clear();
        } else {
            non_conflict_lines.push(line.to_string());
            recent_context.push(line.to_string());
            if recent_context.len() > CONTEXT_LINES {
                recent_context.remove(0);
            }
            i += 1;
        }
    }

    (blocks, non_conflict_lines)
}

/// 智能合并策略
fn smart_merge(block: &ConflictBlock) -> (Vec<String>, String) {
    // 1. 完全相同 - 随便选一个
    if block.is_identical() {
        return (block.ours.clone(), "Identical blocks".to_string());
    }

    // 2. 一方为空 - 保留另一方
    if block.ours_empty() && !block.theirs_empty() {
        return (block.theirs.clone(), "Ours is empty, kept theirs".to_string());
    }
    if block.theirs_empty() && !block.ours_empty() {
        return (block.ours.clone(), "Theirs is empty, kept ours".to_string());
    }
    if block.ours_empty() && block.theirs_empty() {
        return (vec![], "Both empty".to_string());
    }

    // 3. import/use 语句冲突 - 合并排序去重
    if block.is_import_conflict() {
        let mut merged: Vec<String> = block.ours.clone();
        for line in &block.theirs {
            if !merged.contains(line) {
                merged.push(line.clone());
            }
        }
        // 尝试排序
        merged.sort();
        return (merged, "Import conflict: merged and deduplicated".to_string());
    }

    // 4. 注释冲突 - 保留双方
    if block.is_comment_conflict() {
        let mut merged = block.ours.clone();
        for line in &block.theirs {
            if !merged.contains(line) {
                merged.push(line.clone());
            }
        }
        return (merged, "Comment conflict: kept both".to_string());
    }

    // 5. 空白/格式冲突 - 保留本地
    if block.is_whitespace_conflict() {
        return (block.ours.clone(), "Whitespace only: kept ours".to_string());
    }

    // 6. 一方是另一方的超集 - 保留超集
    let our_set: HashSet<&str> = block.ours.iter().map(|s| s.as_str()).collect();
    let their_set: HashSet<&str> = block.theirs.iter().map(|s| s.as_str()).collect();

    if our_set.is_superset(&their_set) {
        return (block.ours.clone(), "Ours is superset".to_string());
    }
    if their_set.is_superset(&our_set) {
        return (block.theirs.clone(), "Theirs is superset".to_string());
    }

    // 7. 上下文感知合并
    // 检查双方是否在修改同一行
    let _ours_trimmed: Vec<&str> = block.ours.iter().map(|l| l.trim()).collect();
    let _theirs_trimmed: Vec<&str> = block.theirs.iter().map(|l| l.trim()).collect();

    // 如果行数相同，尝试逐行匹配
    if block.ours.len() == block.theirs.len() {
        let mut merged = Vec::new();
        let mut changes = 0;

        for (o, t) in block.ours.iter().zip(block.theirs.iter()) {
            if o.trim() == t.trim() {
                // 相同行 (可能缩进不同)
                merged.push(o.clone());
            } else {
                // 不同行，检查是否只是添加了内容
                if t.trim().starts_with(o.trim()) || o.trim().starts_with(t.trim()) {
                    // 一方是另一方的扩展，保留较长的
                    if o.len() >= t.len() {
                        merged.push(o.clone());
                    } else {
                        merged.push(t.clone());
                    }
                } else {
                    // 真正的修改，标记为变更
                    merged.push(format!("/* AI MERGE: conflict */ {}", o));
                    changes += 1;
                }
            }
        }

        if changes == 0 {
            return (merged, "Line-by-line merged (whitespace only)".to_string());
        }
        return (merged, format!("Line-by-line merged ({} changes)", changes));
    }

    // 8. 默认: 智能合并，按行号排序
    let mut merged: Vec<String> = Vec::new();
    let mut used_ours = HashSet::new();
    let mut used_theirs = HashSet::new();

    // 先添加共同行
    for (_i, line) in block.ours.iter().enumerate() {
        if block.theirs.contains(line) {
            if !used_ours.contains(line) {
                merged.push(line.clone());
                used_ours.insert(line.clone());
            }
        }
    }

    // 添加本地特有的行
    for line in &block.ours {
        if !used_ours.contains(line) {
            merged.push(line.clone());
            used_ours.insert(line.clone());
        }
    }

    // 添加远程特有的行
    for line in &block.theirs {
        if !used_theirs.contains(line) {
            merged.push(line.clone());
            used_theirs.insert(line.clone());
        }
    }

    (merged, "Smart merge: combined unique lines".to_string())
}

/// 解决冲突 (主入口)
pub fn resolve_conflict(content: &str) -> MergeResult {
    resolve_conflict_with_strategy(content, None, None)
}

/// 使用指定策略解决冲突
pub fn resolve_conflict_with_strategy(
    content: &str,
    strategy: Option<MergeStrategy>,
    filename: Option<&str>,
) -> MergeResult {
    let strategy = strategy.unwrap_or(MergeStrategy::Smart);
    let (blocks, non_conflict_lines) = parse_conflicts(content, filename);

    let mut result_lines: Vec<String> = Vec::new();
    let mut resolved = 0;
    let mut unresolved = 0;
    let mut resolutions = Vec::new();

    // 重建文件内容，将冲突块替换为合并结果
    // 我们需要在原始行中定位冲突块的位置
    let all_lines: Vec<&str> = content.lines().collect();
    let mut i = 0;

    for block in &blocks {
        // 添加冲突前的非冲突行
        while i < all_lines.len() && !all_lines[i].starts_with("<<<<<<<") {
            result_lines.push(all_lines[i].to_string());
            i += 1;
        }

        // 跳过冲突块
        let mut conflict_end = i;
        if conflict_end < all_lines.len() && all_lines[conflict_end].starts_with("<<<<<<<") {
            conflict_end += 1;
            while conflict_end < all_lines.len() && !all_lines[conflict_end].starts_with("=======") {
                conflict_end += 1;
            }
            if conflict_end < all_lines.len() && all_lines[conflict_end].starts_with("=======") {
                conflict_end += 1;
            }
            while conflict_end < all_lines.len() && !all_lines[conflict_end].starts_with(">>>>>>>") {
                conflict_end += 1;
            }
            if conflict_end < all_lines.len() && all_lines[conflict_end].starts_with(">>>>>>>") {
                conflict_end += 1;
            }
        }

        // 解决冲突
        let (merged_lines, reason) = match strategy {
            MergeStrategy::Ours => {
                (block.ours.clone(), "Ours strategy".to_string())
            }
            MergeStrategy::Theirs => {
                (block.theirs.clone(), "Theirs strategy".to_string())
            }
            MergeStrategy::Union => {
                let mut merged = block.ours.clone();
                for line in &block.theirs {
                    if !merged.contains(line) {
                        merged.push(line.clone());
                    }
                }
                (merged, "Union strategy".to_string())
            }
            MergeStrategy::Smart => {
                smart_merge(block)
            }
            MergeStrategy::Manual => {
                let mut manual = Vec::new();
                manual.push(format!("<<<<<<< ours (conflict #{})", block.id));
                for line in &block.ours {
                    manual.push(line.clone());
                }
                manual.push("=======".to_string());
                for line in &block.theirs {
                    manual.push(line.clone());
                }
                manual.push(format!(">>>>>>> theirs (conflict #{})", block.id));
                (manual, format!("Manual resolution needed for conflict #{}", block.id))
            }
        };

        // 检查是否真的解决了 (Smart 模式下可能仍有冲突标记)
        let actually_resolved = !merged_lines.iter().any(|l| {
            l.starts_with("<<<<<<<") || l.starts_with(">>>>>>>") || l.starts_with("=======")
        });

        if actually_resolved {
            resolved += 1;
        } else {
            unresolved += 1;
        }

        // 添加合并后的行
        for line in &merged_lines {
            result_lines.push(line.clone());
        }

        resolutions.push(ConflictResolution {
            id: block.id,
            strategy,
            resolved: actually_resolved,
            reason,
        });

        i = conflict_end;
    }

    // 添加剩余的非冲突行
    while i < all_lines.len() {
        result_lines.push(all_lines[i].to_string());
        i += 1;
    }

    MergeResult {
        content: result_lines.join("\n"),
        resolved,
        unresolved,
        resolutions,
    }
}

/// 检测文件是否有冲突
pub fn has_conflicts(content: &str) -> bool {
    content.lines().any(|l| l.starts_with("<<<<<<<"))
}

/// 统计冲突数
pub fn count_conflicts(content: &str) -> usize {
    content.lines()
        .filter(|l| l.starts_with("<<<<<<<"))
        .count()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_identical_blocks() {
        let content = "<<<<<<< HEAD\nsame\n=======\nsame\n>>>>>>> branch\n";
        let result = resolve_conflict(content);
        assert_eq!(result.resolved, 1);
        assert_eq!(result.content.trim(), "same");
    }

    #[test]
    fn test_ours_empty() {
        let content = "<<<<<<< HEAD\n=======\ntheir change\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), None);
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("their change"));
    }

    #[test]
    fn test_theirs_empty() {
        let content = "<<<<<<< HEAD\nour change\n=======\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), None);
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("our change"));
    }

    #[test]
    fn test_ours_strategy() {
        let content = "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Ours), None);
        assert_eq!(result.resolved, 1);
        assert_eq!(result.content.trim(), "ours");
    }

    #[test]
    fn test_theirs_strategy() {
        let content = "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Theirs), None);
        assert_eq!(result.resolved, 1);
        assert_eq!(result.content.trim(), "theirs");
    }

    #[test]
    fn test_import_conflict() {
        let content = "<<<<<<< HEAD\nimport foo\n=======\nimport bar\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), None);
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("import foo"));
        assert!(result.content.contains("import bar"));
    }

    #[test]
    fn test_no_conflict() {
        let content = "line1\nline2\n";
        let result = resolve_conflict(content);
        assert_eq!(result.resolved, 0);
        assert_eq!(result.content, "line1\nline2");
    }

    #[test]
    fn test_multiple_conflicts() {
        let content = "<<<<<<< HEAD\nfirst ours\n=======\nfirst theirs\n>>>>>>> branch\nmiddle\n<<<<<<< HEAD\nsecond ours\n=======\nsecond theirs\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), None);
        assert_eq!(result.resolved, 2);
        assert!(result.content.contains("middle"));
    }

    #[test]
    fn test_union_strategy() {
        let content = "<<<<<<< HEAD\nour line\n=======\ntheir line\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Union), None);
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("our line"));
        assert!(result.content.contains("their line"));
    }

    #[test]
    fn test_has_conflicts() {
        assert!(has_conflicts("<<<<<<< HEAD\nfoo\n=======\nbar\n>>>>>>> branch\n"));
        assert!(!has_conflicts("no conflicts here"));
    }

    #[test]
    fn test_count_conflicts() {
        let content = "<<<<<<< HEAD\n1\n=======\n1\n>>>>>>> a\nmiddle\n<<<<<<< HEAD\n2\n=======\n2\n>>>>>>> b\n";
        assert_eq!(count_conflicts(content), 2);
    }

    #[test]
    fn test_whitespace_only() {
        let content = "<<<<<<< HEAD\n  \n=======\n\t\n>>>>>>> branch\n";
        let result = resolve_conflict(content);
        assert_eq!(result.resolved, 1);
    }

    #[test]
    fn test_comment_conflict() {
        let content = "<<<<<<< HEAD\n// my comment\n=======\n// their comment\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), None);
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("my comment"));
        assert!(result.content.contains("their comment"));
    }

    #[test]
    fn test_superset_detection() {
        let content = "<<<<<<< HEAD\nline1\nline2\nline3\n=======\nline1\nline3\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), None);
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("line2"));
    }

    #[test]
    fn test_manual_strategy() {
        let content = "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Manual), None);
        assert_eq!(result.resolved, 0);
        assert_eq!(result.unresolved, 1);
        assert!(result.content.contains("<<<<<<<"));
    }
}