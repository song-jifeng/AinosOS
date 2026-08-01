// 语义 diff 分析模块

pub fn analyze_diff(diff: &str) -> String {
    let mut analysis = String::new();
    let lines: Vec<&str> = diff.lines().collect();

    let mut files_changed = 0;
    let mut insertions = 0;
    let mut deletions = 0;
    let mut category_changes: Vec<String> = Vec::new();

    for line in &lines {
        if line.starts_with("+++ b/") || line.starts_with("--- a/") {
            files_changed += 1;
        } else if line.starts_with('+') && !line.starts_with("+++") {
            insertions += 1;
        } else if line.starts_with('-') && !line.starts_with("---") {
            deletions += 1;
        }

        // 检测变更类别
        if line.contains("fn ") || line.contains("pub fn ") {
            category_changes.push("function".to_string());
        } else if line.contains("struct ") || line.contains("pub struct ") {
            category_changes.push("struct".to_string());
        } else if line.contains("impl ") {
            category_changes.push("implementation".to_string());
        } else if line.contains("match ") {
            category_changes.push("match expression".to_string());
        } else if line.contains("unsafe ") {
            category_changes.push("unsafe code".to_string());
        } else if line.contains("TODO") || line.contains("FIXME") {
            category_changes.push("todo/fixme".to_string());
        }
    }

    category_changes.sort();
    category_changes.dedup();

    analysis.push_str(&format!("  Files changed:     {}\n", files_changed));
    analysis.push_str(&format!("  Insertions:        {}\n", insertions));
    analysis.push_str(&format!("  Deletions:         {}\n", deletions));
    analysis.push_str(&format!("  Net change:        {:+}\n", insertions as isize - deletions as isize));

    if !category_changes.is_empty() {
        analysis.push_str(&format!("  Categories:        {}\n", category_changes.join(", ")));
    }

    // 风险评估
    let risk = if deletions > 100 || insertions > 200 {
        "HIGH"
    } else if deletions > 50 || insertions > 100 {
        "MEDIUM"
    } else {
        "LOW"
    };
    analysis.push_str(&format!("  Risk level:        {}\n", risk));

    if category_changes.contains(&"unsafe code".to_string()) {
        analysis.push_str("  WARNING: Unsafe code changes detected - review carefully!\n");
    }

    analysis
}

pub fn resolve_conflict(content: &str) -> String {
    let mut resolved = String::new();
    let mut in_conflict = false;
    let mut local_lines: Vec<&str> = Vec::new();
    let mut remote_lines: Vec<&str> = Vec::new();

    // AI 冲突解决策略: 保留本地和远程的变更
    for line in content.lines() {
        if line.starts_with("<<<<<<<") {
            in_conflict = true;
            local_lines.clear();
            remote_lines.clear();
        } else if line.starts_with("=======") && in_conflict {
            // 切换收集端
            continue;
        } else if line.starts_with(">>>>>>>") && in_conflict {
            // 冲突结束，AI 合并
            in_conflict = false;

            // 简单策略: 同时保留本地和远程的变更
            for l in &local_lines {
                if !remote_lines.contains(l) {
                    resolved.push_str(l);
                    resolved.push('\n');
                }
            }
            for r in &remote_lines {
                if !local_lines.contains(r) {
                    resolved.push_str(r);
                    resolved.push('\n');
                }
            }
        } else if in_conflict {
            if local_lines.is_empty() || remote_lines.len() < local_lines.len() {
                local_lines.push(line);
            } else {
                remote_lines.push(line);
            }
        } else {
            resolved.push_str(line);
            resolved.push('\n');
        }
    }

    resolved
}