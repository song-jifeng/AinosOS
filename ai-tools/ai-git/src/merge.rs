// 合并冲突解决模块

use std::collections::HashSet;

/// AI 合并冲突解决
pub fn resolve_conflict(content: &str) -> String {
    let mut result = String::new();
    let mut conflict_id = 0;

    // 按行解析冲突
    let lines: Vec<&str> = content.lines().collect();
    let mut i = 0;

    while i < lines.len() {
        let line = lines[i];

        if line.starts_with("<<<<<<<") {
            // 解析冲突块
            let mut ours: Vec<&str> = Vec::new();
            let mut theirs: Vec<&str> = Vec::new();
            let mut in_ours = true;
            i += 1;

            while i < lines.len() && !lines[i].starts_with(">>>>>>>") {
                if lines[i].starts_with("=======") {
                    in_ours = false;
                } else if in_ours {
                    ours.push(lines[i]);
                } else {
                    theirs.push(lines[i]);
                }
                i += 1;
            }

            // AI 合并策略
            let merged = ai_merge_blocks(&ours, &theirs, conflict_id);
            result.push_str(&merged);
            if !merged.ends_with('\n') {
                result.push('\n');
            }
            conflict_id += 1;
        } else {
            result.push_str(line);
            result.push('\n');
        }
        i += 1;
    }

    result
}

/// AI 合并两个冲突块
fn ai_merge_blocks(ours: &[&str], theirs: &[&str], _id: usize) -> String {
    let mut merged = String::new();

    // 如果有一方为空，保留另一方
    if ours.is_empty() {
        return theirs.join("\n");
    }
    if theirs.is_empty() {
        return ours.join("\n");
    }

    // 如果完全相同，直接返回
    if ours == theirs {
        return ours.join("\n");
    }

    // 收集唯一行和共同行
    let our_set: HashSet<&str> = ours.iter().cloned().collect();
    let their_set: HashSet<&str> = theirs.iter().cloned().collect();

    // 交集 - 共同行
    let common: Vec<&&str> = our_set.intersection(&their_set).collect();

    // 差集 - 唯一行
    let our_only: Vec<&&str> = our_set.difference(&their_set).collect();
    let their_only: Vec<&&str> = their_set.difference(&our_set).collect();

    // 共同行优先
    for line in &common {
        merged.push_str(line);
        merged.push('\n');
    }

    // 本地新增
    for line in &our_only {
        merged.push_str(line);
        merged.push('\n');
    }

    // 远程新增
    for line in &their_only {
        merged.push_str(line);
        merged.push('\n');
    }

    merged
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_simple_conflict() {
        let content = "line1\n<<<<<<< HEAD\nour change\n=======\ntheir change\n>>>>>>> branch\nline2\n";
        let result = resolve_conflict(content);
        // 应该包含两个变更
        assert!(result.contains("our change"));
        assert!(result.contains("their change"));
        assert!(result.contains("line1"));
        assert!(result.contains("line2"));
    }

    #[test]
    fn test_no_conflict() {
        let content = "line1\nline2\nline3\n";
        let result = resolve_conflict(content);
        assert_eq!(result, "line1\nline2\nline3\n");
    }

    #[test]
    fn test_identical_blocks() {
        let content = "<<<<<<< HEAD\nsame\n=======\nsame\n>>>>>>> branch\n";
        let result = resolve_conflict(content);
        assert_eq!(result, "same\n");
    }

    #[test]
    fn test_empty_ours() {
        let content = "<<<<<<< HEAD\n=======\ntheir\n>>>>>>> branch\n";
        let result = resolve_conflict(content);
        assert_eq!(result, "their\n");
    }
}