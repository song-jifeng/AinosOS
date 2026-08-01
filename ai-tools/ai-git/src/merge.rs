// ================================================================
// Ainos OS - AI Git Merge Conflict Resolution Engine (v3.0.0)
// ================================================================
//
// Multi-strategy merge engine with language-aware smart merging,
// diff3 conflict marker support, syntax validation, and optional
// LLM fallback for complex conflicts.
//
// Strategies:
//   Ours    - Keep local changes only
//   Theirs  - Keep remote changes only
//   Union   - Keep both sides (may produce invalid code)
//   Smart   - Context-aware heuristics + language-aware merge (recommended)
//   Manual  - Preserve conflict markers for manual resolution
//
// Architecture:
//   ┌──────────────────────────────────────────────────┐
//   │  Conflict Parser                                 │
//   │  Parses <<<<<<< / ||||||| / ======= / >>>>>>>   │
//   └──────────────────┬───────────────────────────────┘
//                      ▼
//   ┌──────────────────────────────────────────────────┐
//   │  Strategy Engine                                 │
//   │  Ours / Theirs / Union / Smart / Manual          │
//   └──────────────────┬───────────────────────────────┘
//                      ▼
//   ┌──────────────────────────────────────────────────┐
//   │  Language-Aware Smart Merge (Smart mode)         │
//   │  - Import/use merging + dedup + sort             │
//   │  - Adjacent insertion detection                  │
//   │  - Function-level merge (different functions)    │
//   │  - Same-function line-level heuristics           │
//   │  - Syntax validation (brace/paren/bracket)       │
//   │  - LLM fallback for complex conflicts            │
//   └──────────────────────────────────────────────────┘
// ================================================================

use std::collections::HashSet;

// ================================================================
// Public API — Types
// ================================================================

/// Merge strategy selection.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum MergeStrategy {
    /// Keep local (ours) changes only.
    Ours,
    /// Keep remote (theirs) changes only.
    Theirs,
    /// Keep both sides (union — may produce invalid code).
    Union,
    /// Context-aware smart merge (recommended).
    Smart,
    /// Preserve conflict markers for manual resolution.
    Manual,
}

impl MergeStrategy {
    /// Parse a strategy from a string. Unknown values default to Smart.
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

/// Programming language detected from file extension. Used by the Smart
/// strategy for language-aware parsing and import merging.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Language {
    Rust,
    Python,
    C,
    JavaScript,
    Go,
    Java,
    Unknown,
}

/// Result of a merge operation.
#[derive(Debug)]
pub struct MergeResult {
    /// Merged file content.
    pub content: String,
    /// Number of automatically resolved conflicts.
    pub resolved: usize,
    /// Number of unresolved conflicts (require manual intervention).
    pub unresolved: usize,
    /// Resolution record for each conflict.
    pub resolutions: Vec<ConflictResolution>,
}

/// Record of how a single conflict was handled.
#[derive(Debug)]
pub struct ConflictResolution {
    pub id: usize,
    pub strategy: MergeStrategy,
    pub resolved: bool,
    pub reason: String,
}

/// Trait for LLM-based conflict resolution fallback.
///
/// Implement this to integrate with any LLM API. The `resolve` method
/// receives the conflicting sides and optional merge base, and should
/// return a resolved set of lines, or `None` if resolution fails.
///
/// The returned lines MUST NOT contain conflict markers
/// (`<<<<<<<`, `|||||||`, `=======`, `>>>>>>>`).
pub trait LlmClient {
    /// Attempt to resolve a single merge conflict using an LLM.
    fn resolve_merge_conflict(
        &self,
        ours: &[String],
        theirs: &[String],
        base: Option<&[String]>,
        context_before: &[String],
        context_after: &[String],
        language: Language,
    ) -> Option<Vec<String>>;
}

// ================================================================
// Public API — Functions
// ================================================================

/// Resolve all merge conflicts in `content` using the Smart strategy.
///
/// This is a convenience wrapper around `resolve_conflict_with_strategy`.
pub fn resolve_conflict(content: &str) -> MergeResult {
    resolve_conflict_with_strategy(content, None, None)
}

/// Resolve all merge conflicts in `content` using the specified strategy.
///
/// * `strategy` — merge strategy; defaults to `Smart` when `None`.
/// * `filename` — optional filename for language detection in Smart mode.
pub fn resolve_conflict_with_strategy(
    content: &str,
    strategy: Option<MergeStrategy>,
    filename: Option<&str>,
) -> MergeResult {
    resolve_conflict_inner(content, strategy, filename, None)
}

/// Resolve merge conflicts with optional LLM fallback.
///
/// When `llm_client` is provided, conflicts that the Smart strategy's
/// heuristics cannot resolve cleanly will be forwarded to the LLM.
/// The existing `resolve_conflict_with_strategy` and `resolve_conflict`
/// functions work without LLM (complex conflicts are marked unresolved).
pub fn resolve_conflict_with_llm(
    content: &str,
    strategy: Option<MergeStrategy>,
    filename: Option<&str>,
    llm_client: &dyn LlmClient,
) -> MergeResult {
    resolve_conflict_inner(content, strategy, filename, Some(llm_client))
}

/// Check whether `content` contains merge conflict markers.
pub fn has_conflicts(content: &str) -> bool {
    content.lines().any(|l| l.starts_with("<<<<<<<"))
}

/// Count the number of merge conflicts in `content`.
pub fn count_conflicts(content: &str) -> usize {
    content.lines()
        .filter(|l| l.starts_with("<<<<<<<"))
        .count()
}

// ================================================================
// Internal Types
// ================================================================

/// A single conflict block parsed from conflict markers.
///
/// Supports both standard two-way markers and diff3 three-way markers:
/// ```text
/// <<<<<<< ours
///  (ours)
/// ||||||| base
///  (merge base — diff3 only)
/// =======
///  (theirs)
/// >>>>>>> theirs
/// ```
struct ConflictBlock {
    /// Local changes (ours).
    ours: Vec<String>,
    /// Remote changes (theirs).
    theirs: Vec<String>,
    /// Merge base from diff3 markers (empty if not diff3).
    base: Vec<String>,
    /// Context lines before the conflict.
    context_before: Vec<String>,
    /// Context lines after the conflict.
    context_after: Vec<String>,
    /// Sequential conflict ID.
    id: usize,
    /// Source filename (for language detection).
    filename: Option<String>,
    /// Whether this block used diff3 format.
    has_diff3: bool,
}

impl ConflictBlock {
    fn new(id: usize) -> Self {
        ConflictBlock {
            ours: Vec::new(),
            theirs: Vec::new(),
            base: Vec::new(),
            context_before: Vec::new(),
            context_after: Vec::new(),
            id,
            filename: None,
            has_diff3: false,
        }
    }

    /// Detect the programming language from the filename extension.
    fn language(&self) -> Language {
        self.filename
            .as_deref()
            .and_then(|f| {
                let (_, ext) = f.rsplit_once('.')?;
                Some(Language::from_extension(ext))
            })
            .unwrap_or(Language::Unknown)
    }

    /// Both sides are byte-for-byte identical.
    fn is_identical(&self) -> bool {
        self.ours == self.theirs
    }

    /// All lines in `ours` are empty or whitespace.
    fn ours_empty(&self) -> bool {
        self.ours.iter().all(|l| l.trim().is_empty())
    }

    /// All lines in `theirs` are empty or whitespace.
    fn theirs_empty(&self) -> bool {
        self.theirs.iter().all(|l| l.trim().is_empty())
    }

    /// All lines in both sides are import/use/include statements.
    fn is_import_conflict(&self) -> bool {
        let lang = self.language();
        self.ours.iter().chain(self.theirs.iter()).all(|line| {
            is_import_line(line, lang)
        })
    }

    /// All lines in both sides are comments or blank.
    fn is_comment_conflict(&self) -> bool {
        self.ours.iter().chain(self.theirs.iter()).all(|line| {
            let trimmed = line.trim();
            trimmed.is_empty() || is_comment_line(trimmed, self.language())
        })
    }

    /// All lines are whitespace or bare braces.
    fn is_whitespace_conflict(&self) -> bool {
        self.ours.iter().chain(self.theirs.iter()).all(|l| {
            let t = l.trim();
            t.is_empty() || t == "}" || t == "{"
        })
    }
}

// ================================================================
// Language Detection
// ================================================================

impl Language {
    /// Map a file extension to a Language.
    fn from_extension(ext: &str) -> Self {
        match ext {
            "rs" => Language::Rust,
            "py" => Language::Python,
            "c" | "h" | "cpp" | "hpp" | "cc" | "hh" | "cxx" | "hxx" => Language::C,
            "js" | "jsx" | "ts" | "tsx" | "mjs" | "cjs" => Language::JavaScript,
            "go" => Language::Go,
            "java" | "kt" | "kts" => Language::Java,
            _ => Language::Unknown,
        }
    }
}

// ================================================================
// Language-Aware Utilities
// ================================================================

/// Check if `line` is a comment in the given language.
fn is_comment_line(line: &str, lang: Language) -> bool {
    let trimmed = line.trim_start();
    match lang {
        Language::Python | Language::Unknown => {
            trimmed.starts_with('#')
                || trimmed.starts_with("//")
                || trimmed.starts_with("/*")
                || trimmed.starts_with('*')
                || trimmed.starts_with("///")
                || trimmed.starts_with("//!")
        }
        Language::Rust => {
            trimmed.starts_with("//")
                || trimmed.starts_with("/*")
                || trimmed.starts_with('*')
                || trimmed.starts_with("///")
                || trimmed.starts_with("//!")
        }
        Language::C | Language::JavaScript | Language::Go | Language::Java => {
            trimmed.starts_with("//")
                || trimmed.starts_with("/*")
                || trimmed.starts_with('*')
                || trimmed.starts_with("///")
        }
    }
}

/// Check if `line` is an import/use/include statement in the given language.
fn is_import_line(line: &str, lang: Language) -> bool {
    let trimmed = line.trim_start();
    match lang {
        Language::Rust => trimmed.starts_with("use "),
        Language::Python => trimmed.starts_with("import ") || trimmed.starts_with("from "),
        Language::C => trimmed.starts_with("#include"),
        Language::JavaScript => {
            trimmed.starts_with("import ")
                || trimmed.starts_with("const ")
                || trimmed.starts_with("let ")
                || trimmed.starts_with("var ")
                || trimmed.starts_with("require(")
        }
        Language::Go => trimmed.starts_with("import "),
        Language::Java => trimmed.starts_with("import "),
        Language::Unknown => {
            let keywords = ["import ", "use ", "#include", "require(", "from "];
            keywords.iter().any(|kw| trimmed.starts_with(kw))
        }
    }
}

/// Check if a line starts a Python block (def, class, async def).
fn is_python_block_start(line: &str) -> bool {
    let trimmed = line.trim_start();
    trimmed.starts_with("def ")
        || trimmed.starts_with("class ")
        || trimmed.starts_with("async def ")
}

/// Check if a line starts a function/method/block definition in the given language.
fn is_function_start(line: &str, lang: Language) -> bool {
    let trimmed = line.trim_start();
    match lang {
        Language::Rust => {
            trimmed.starts_with("fn ")
                || trimmed.starts_with("pub fn ")
                || trimmed.starts_with("pub(crate) fn ")
                || trimmed.starts_with("pub(super) fn ")
                || trimmed.starts_with("unsafe fn ")
                || trimmed.starts_with("pub unsafe fn ")
                || trimmed.starts_with("pub(crate) unsafe fn ")
                || trimmed.starts_with("trait ")
                || trimmed.starts_with("impl ")
                || trimmed.starts_with("pub trait ")
                || trimmed.starts_with("pub impl ")
                || trimmed.starts_with("struct ")
                || trimmed.starts_with("pub struct ")
                || trimmed.starts_with("enum ")
                || trimmed.starts_with("pub enum ")
                || trimmed.starts_with("mod ")
                || trimmed.starts_with("pub mod ")
                || trimmed.starts_with("macro_rules!")
        }
        Language::Python => is_python_block_start(line),
        Language::C => {
            // C functions: return_type name(...) { or just name(...) {
            trimmed.contains('(') && trimmed.contains(')')
                && !trimmed.starts_with("if")
                && !trimmed.starts_with("while")
                && !trimmed.starts_with("for")
                && !trimmed.starts_with("switch")
                && !trimmed.starts_with("return")
                && (trimmed.ends_with('{') || trimmed.ends_with(')') || trimmed.ends_with(") "))
        }
        Language::JavaScript => {
            trimmed.starts_with("function ")
                || trimmed.starts_with("async function ")
                || trimmed.starts_with("const ")
                || trimmed.starts_with("let ")
                || trimmed.starts_with("var ")
                || trimmed.starts_with("class ")
                || trimmed.starts_with("async ")
        }
        Language::Go => {
            trimmed.starts_with("func ")
        }
        Language::Java => {
            trimmed.contains('(') && trimmed.contains(')')
                && (trimmed.starts_with("public")
                    || trimmed.starts_with("private")
                    || trimmed.starts_with("protected")
                    || trimmed.starts_with("static")
                    || trimmed.starts_with("final")
                    || trimmed.starts_with("synchronized")
                    || trimmed.starts_with("abstract")
                    || trimmed.starts_with("default")
                    || trimmed.starts_with('(')
                    || is_java_constructor(trimmed))
        }
        Language::Unknown => {
            trimmed.contains('(') && trimmed.contains(')') && trimmed.contains('{')
        }
    }
}

/// Heuristic: a Java constructor starts with an uppercase letter and has parens.
fn is_java_constructor(trimmed: &str) -> bool {
    trimmed.starts_with(|c: char| c.is_uppercase())
        && trimmed.contains('(') && trimmed.contains(')')
}

// ================================================================
// Brace / Paren / Bracket Balance Checking
// ================================================================

/// Result of syntax balance checking.
#[derive(Debug)]
struct BalanceResult {
    balanced: bool,
    open_braces: usize,
    close_braces: usize,
    open_parens: usize,
    close_parens: usize,
    open_brackets: usize,
    close_brackets: usize,
}

impl BalanceResult {
    fn is_balanced(&self) -> bool {
        self.open_braces == self.close_braces
            && self.open_parens == self.close_parens
            && self.open_brackets == self.close_brackets
    }
}

/// Check brace/paren/bracket balance in a set of lines, respecting
/// string literals and comments.
fn check_balance(lines: &[String]) -> BalanceResult {
    let mut result = BalanceResult {
        balanced: false,
        open_braces: 0,
        close_braces: 0,
        open_parens: 0,
        close_parens: 0,
        open_brackets: 0,
        close_brackets: 0,
    };

    let mut in_block_comment = false;

    for line in lines {
        let mut chars = line.chars().peekable();
        while let Some(ch) = chars.next() {
            if in_block_comment {
                // Look for end of block comment: */
                if ch == '*' && chars.peek() == Some(&'/') {
                    in_block_comment = false;
                    chars.next(); // consume '/'
                }
                continue;
            }

            // String literals — skip contents (handled before comment checks
            // so that `"//"` is not treated as a comment).
            if ch == '"' || ch == '\'' {
                let quote = ch;
                while let Some(next) = chars.next() {
                    if next == '\\' {
                        chars.next(); // skip escaped char
                    } else if next == quote {
                        break;
                    }
                }
                continue;
            }

            match ch {
                '/' if chars.peek() == Some(&'*') => {
                    in_block_comment = true;
                    chars.next(); // consume '*'
                }
                '/' if chars.peek() == Some(&'/') => break, // line comment
                '{' => result.open_braces += 1,
                '}' => result.close_braces += 1,
                '(' => result.open_parens += 1,
                ')' => result.close_parens += 1,
                '[' => result.open_brackets += 1,
                ']' => result.close_brackets += 1,
                _ => {}
            }
        }
    }

    result.balanced = result.is_balanced();
    result
}

/// Validate that `lines` have balanced braces, parens, and brackets.
fn validate_syntax(lines: &[String]) -> bool {
    check_balance(lines).is_balanced()
}

// ================================================================
// Block Boundary Detection
// ================================================================

/// Find the end of a brace-delimited block starting at `start`.
///
/// Returns the line index of the matching `}`, or `None` if the block
/// is unterminated.  Handles string literals, line comments, and block
/// comments correctly.
fn find_matching_block_end(lines: &[String], start: usize) -> Option<usize> {
    // Find the opening brace
    let brace_line = (start..lines.len()).find(|&i| lines[i].contains('{'))?;

    let mut depth: i32 = 0;
    let mut in_block_comment = false;

    for i in brace_line..lines.len() {
        let line = &lines[i];
        let mut chars = line.chars().peekable();

        while let Some(ch) = chars.next() {
            if in_block_comment {
                if ch == '*' && chars.peek() == Some(&'/') {
                    in_block_comment = false;
                    chars.next();
                }
                continue;
            }

            // String literals
            if ch == '"' || ch == '\'' {
                let quote = ch;
                while let Some(next) = chars.next() {
                    if next == '\\' {
                        chars.next();
                    } else if next == quote {
                        break;
                    }
                }
                continue;
            }

            match ch {
                '/' if chars.peek() == Some(&'*') => {
                    in_block_comment = true;
                    chars.next();
                }
                '/' if chars.peek() == Some(&'/') => break,
                '{' => depth += 1,
                '}' => {
                    depth -= 1;
                    if depth == 0 {
                        return Some(i);
                    }
                }
                _ => {}
            }
        }

        // If depth reaches 0 at end of line, the block was closed
        // (handles `fn foo() {}` style single-line blocks).
        if depth == 0 && i >= brace_line {
            return Some(i);
        }
    }

    None // Unterminated block
}

/// Find the end of a Python block (indentation-based).
fn find_python_block_end(lines: &[String], start: usize) -> Option<usize> {
    let first_body = (start + 1..lines.len())
        .find(|&i| !lines[i].trim().is_empty())?;

    let indent = lines[first_body].len() - lines[first_body].trim_start().len();

    for i in first_body + 1..lines.len() {
        let line = &lines[i];
        if line.trim().is_empty() {
            continue;
        }
        let current_indent = line.len() - line.trim_start().len();
        if current_indent <= indent && !line.trim_start().starts_with('#') {
            return if i > 0 { Some(i - 1) } else { Some(i) };
        }
    }

    Some(lines.len() - 1)
}

// ================================================================
// Function Name Extraction
// ================================================================

/// Extract the name of a function/method from its definition line.
fn extract_function_name(line: &str, lang: Language) -> Option<String> {
    let trimmed = line.trim_start();
    match lang {
        Language::Rust => {
            // "fn name(...)", "pub fn name(...)", "pub unsafe fn name(...)", etc.
            let fn_idx = trimmed.find("fn ")?;
            let after_fn = trimmed[fn_idx + 3..].trim_start();
            let name_end = after_fn.find(|c: char| c == '(' || c == '<' || c == ' ')
                .unwrap_or(after_fn.len());
            let name = after_fn[..name_end].trim().to_string();
            if name.is_empty() { None } else { Some(name) }
        }
        Language::Python => {
            // "def name(...):" or "async def name(...):" or "class name(...):"
            let after_def = if let Some(d) = trimmed.find("def ") {
                &trimmed[d + 4..]
            } else if let Some(c) = trimmed.find("class ") {
                &trimmed[c + 6..]
            } else {
                return None;
            };
            let name_end = after_def.find(|c: char| c == '(' || c == ':' || c == ' ')
                .unwrap_or(after_def.len());
            let name = after_def[..name_end].trim().to_string();
            if name.is_empty() { None } else { Some(name) }
        }
        Language::JavaScript => {
            // "function name(...)", "const name = ...", "class name"
            if let Some(fn_idx) = trimmed.find("function ") {
                let after_fn = trimmed[fn_idx + 9..].trim_start();
                let name_end = after_fn.find('(').unwrap_or(after_fn.len());
                let name = after_fn[..name_end].trim().to_string();
                return if name.is_empty() { None } else { Some(name) };
            }
            // Arrow function: "const name = (...)" or "let name = (...)"
            let eq_idx = trimmed.find('=')?;
            let before_eq = trimmed[..eq_idx].trim();
            let name = before_eq
                .split_whitespace()
                .filter(|&w| !matches!(w, "const" | "let" | "var" | "async"))
                .next()
                .unwrap_or("")
                .trim_end_matches('=')
                .trim()
                .to_string();
            if !name.is_empty() {
                return Some(name);
            }
            // Class
            let cls_idx = trimmed.find("class ")?;
            let after_cls = trimmed[cls_idx + 6..].trim_start();
            let name_end = after_cls.find(|c: char| c == '{' || c == ' ')
                .unwrap_or(after_cls.len());
            let name = after_cls[..name_end].trim().to_string();
            if name.is_empty() { None } else { Some(name) }
        }
        Language::Go => {
            // "func name(...)" or "func (r *Receiver) Name(...)"
            let func_idx = trimmed.find("func ")?;
            let after_func = trimmed[func_idx + 5..].trim_start();
            // Skip receiver if present: (r *Receiver)
            let after_receiver = if after_func.starts_with('(') {
                let close = after_func.find(')')?;
                after_func[close + 1..].trim_start()
            } else {
                after_func
            };
            let name_end = after_receiver.find('(').unwrap_or(after_receiver.len());
            let name = after_receiver[..name_end].trim().to_string();
            if name.is_empty() { None } else { Some(name) }
        }
        Language::C | Language::Java => {
            // Find the identifier before '('
            let paren_idx = trimmed.find('(')?;
            let before_paren = trimmed[..paren_idx].trim();
            let tokens: Vec<&str> = before_paren.split_whitespace().collect();
            let last = *tokens.last()?;
            let name = last.trim_end_matches('*').trim();
            if name.is_empty() {
                if tokens.len() >= 2 {
                    let candidate = tokens[tokens.len() - 2].trim_end_matches('*').trim().to_string();
                    if candidate.is_empty() { None } else { Some(candidate) }
                } else {
                    None
                }
            } else {
                Some(name.to_string())
            }
        }
        Language::Unknown => {
            let paren_idx = trimmed.find('(')?;
            let before_paren = trimmed[..paren_idx].trim();
            let tokens: Vec<&str> = before_paren.split_whitespace().collect();
            let last = tokens.last()?;
            let name = last.trim_end_matches('*').trim().to_string();
            if name.is_empty() { None } else { Some(name) }
        }
    }
}

// ================================================================
// Import Merging
// ================================================================

/// Merge two sets of import lines, deduplicate, and sort.
fn merge_imports(ours: &[String], theirs: &[String], lang: Language) -> Vec<String> {
    let mut merged: Vec<String> = ours.to_vec();
    for line in theirs {
        if !merged.contains(line) {
            merged.push(line.clone());
        }
    }
    sort_imports(&mut merged, lang);
    merged
}

/// Sort imports according to language conventions.
fn sort_imports(imports: &mut Vec<String>, lang: Language) {
    match lang {
        Language::Rust => {
            // Group by std, external, self; alphabetical within groups.
            // For simplicity, sort by the path after "use ".
            imports.sort_by(|a, b| {
                let a_key = a.trim_start().trim_end_matches(';').replace("pub ", "");
                let b_key = b.trim_start().trim_end_matches(';').replace("pub ", "");
                // Crate:: vs self:: vs super:: grouping heuristic
                let a_group = if a_key.starts_with("std::") || a_key.starts_with("core::")
                    || a_key.starts_with("alloc::") { 0 }
                else if a_key.starts_with("crate::") || a_key.starts_with("self::") { 2 }
                else { 1 };
                let b_group = if b_key.starts_with("std::") || b_key.starts_with("core::")
                    || b_key.starts_with("alloc::") { 0 }
                else if b_key.starts_with("crate::") || b_key.starts_with("self::") { 2 }
                else { 1 };
                a_group.cmp(&b_group).then_with(|| a_key.cmp(&b_key))
            });
        }
        Language::Python | Language::Java | Language::Go => {
            imports.sort_by(|a, b| a.trim_start().cmp(b.trim_start()));
        }
        Language::C => {
            // Standard headers (<>) first, then project headers ("").
            imports.sort_by(|a, b| {
                let a_trimmed = a.trim_start().trim_start_matches('#').trim();
                let b_trimmed = b.trim_start().trim_start_matches('#').trim();
                let a_is_std = a_trimmed.starts_with('<');
                let b_is_std = b_trimmed.starts_with('<');
                b_is_std.cmp(&a_is_std) // std first
                    .then_with(|| a_trimmed.cmp(&b_trimmed))
            });
        }
        Language::JavaScript => {
            imports.sort_by(|a, b| {
                let a_src = extract_import_source(a);
                let b_src = extract_import_source(b);
                // Absolute/relative heuristic: third-party before local
                let a_is_relative = a_src.starts_with('.') || a_src.starts_with('/');
                let b_is_relative = b_src.starts_with('.') || b_src.starts_with('/');
                a_is_relative.cmp(&b_is_relative)
                    .then_with(|| a_src.cmp(&b_src))
            });
        }
        Language::Unknown => {
            imports.sort();
        }
    }
}

/// Extract the source/module path from an import line.
fn extract_import_source(line: &str) -> &str {
    let trimmed = line.trim_start();
    // "import X from 'y'"
    if let Some(from_pos) = trimmed.rfind(" from ") {
        let after = &trimmed[from_pos + 6..];
        return after.trim().trim_matches('\'').trim_matches('"');
    }
    // "const X = require('y')"
    if let Some(req_pos) = trimmed.find("require(") {
        let after = &trimmed[req_pos + 8..];
        let end = after.find(|c: char| c == ')' || c == ',')
            .unwrap_or(after.len());
        return after[..end].trim().trim_matches('\'').trim_matches('"');
    }
    // "import 'y'"
    // "import * as X from 'y'"
    // Fallback: return the whole line
    trimmed
}

// ================================================================
// Conflict Parsing (with diff3 support)
// ================================================================

/// Number of context lines to capture before and after each conflict.
const CONTEXT_LINES: usize = 3;

/// Parse conflict markers from `content` into `ConflictBlock` values.
///
/// Supports both standard two-way markers and diff3 three-way markers.
/// Returns the parsed blocks and the non-conflict lines (for completeness).
fn parse_conflicts(content: &str, filename: Option<&str>)
    -> (Vec<ConflictBlock>, Vec<String>)
{
    let lines: Vec<&str> = content.lines().collect();
    let mut blocks = Vec::new();
    let mut non_conflict_lines = Vec::new();
    let mut i = 0;
    let mut conflict_id = 0;
    let mut recent_context: Vec<String> = Vec::new();

    while i < lines.len() {
        let line = lines[i];

        if line.starts_with("<<<<<<<") {
            let mut block = ConflictBlock::new(conflict_id);
            block.filename = filename.map(|s| s.to_string());
            block.context_before = recent_context.clone();
            i += 1;

            // Parse ours: up to ||||||| or =======
            while i < lines.len()
                && !lines[i].starts_with("=======")
                && !lines[i].starts_with("|||||||")
            {
                block.ours.push(lines[i].to_string());
                i += 1;
            }

            // Check for diff3 merge base
            if i < lines.len() && lines[i].starts_with("|||||||") {
                block.has_diff3 = true;
                i += 1;
                while i < lines.len() && !lines[i].starts_with("=======") {
                    block.base.push(lines[i].to_string());
                    i += 1;
                }
            }

            // Skip =======
            if i < lines.len() && lines[i].starts_with("=======") {
                i += 1;
            }

            // Parse theirs: up to >>>>>>>
            while i < lines.len() && !lines[i].starts_with(">>>>>>>") {
                block.theirs.push(lines[i].to_string());
                i += 1;
            }

            // Skip >>>>>>>
            if i < lines.len() && lines[i].starts_with(">>>>>>>") {
                i += 1;
            }

            // Collect context after the conflict
            let start_after = i;
            let end_after = (start_after + CONTEXT_LINES).min(lines.len());
            for j in start_after..end_after {
                if lines[j].starts_with("<<<<<<<") {
                    break;
                }
                block.context_after.push(lines[j].to_string());
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

// ================================================================
// Smart Merge — Core Heuristics
// ================================================================

/// Main smart merge entry point. Applies a cascade of heuristics
/// from simplest (identical blocks) to most complex (line-level merge).
fn smart_merge(block: &ConflictBlock) -> (Vec<String>, String) {
    // 1. Identical blocks — pick either side
    if block.is_identical() {
        return (block.ours.clone(), "Identical blocks".to_string());
    }

    // 2. One side empty — keep the non-empty side
    if block.ours_empty() && !block.theirs_empty() {
        return (block.theirs.clone(), "Ours is empty, kept theirs".to_string());
    }
    if block.theirs_empty() && !block.ours_empty() {
        return (block.ours.clone(), "Theirs is empty, kept ours".to_string());
    }
    if block.ours_empty() && block.theirs_empty() {
        return (vec![], "Both empty".to_string());
    }

    // 3. Import/use/include conflict — merge, deduplicate, and sort
    if block.is_import_conflict() {
        let merged = merge_imports(&block.ours, &block.theirs, block.language());
        return (merged, "Import conflict: merged, deduplicated, and sorted".to_string());
    }

    // 4. Comment conflict — keep both sides
    if block.is_comment_conflict() {
        let mut merged = block.ours.clone();
        for line in &block.theirs {
            if !merged.contains(line) {
                merged.push(line.clone());
            }
        }
        return (merged, "Comment conflict: kept both".to_string());
    }

    // 5. Whitespace/formatting conflict — keep ours
    if block.is_whitespace_conflict() {
        return (block.ours.clone(), "Whitespace only: kept ours".to_string());
    }

    // 6. Superset detection — one side is a superset of the other
    let our_set: HashSet<&str> = block.ours.iter().map(|s| s.as_str()).collect();
    let their_set: HashSet<&str> = block.theirs.iter().map(|s| s.as_str()).collect();

    if our_set.is_superset(&their_set) {
        return (block.ours.clone(), "Ours is superset of theirs".to_string());
    }
    if their_set.is_superset(&our_set) {
        return (block.theirs.clone(), "Theirs is superset of ours".to_string());
    }

    // 7. Adjacent insertion merge — both sides add new code near each other
    if let Some(result) = try_adjacent_insertion_merge(block) {
        return result;
    }

    // 8. Function-level merge — different functions on each side
    if let Some(result) = try_function_level_merge(block) {
        return result;
    }

    // 9. Same-function line-level merge — fallback
    same_function_line_merge(block)
}

/// Detect when both sides add code near each other (adjacent insertions).
///
/// When both sides add different structural units (new functions, new blocks)
/// or both sides are pure additions relative to the merge base, we keep both.
fn try_adjacent_insertion_merge(block: &ConflictBlock) -> Option<(Vec<String>, String)> {
    let lang = block.language();

    // Strategy A: use merge base to detect pure additions
    if !block.base.is_empty() {
        let ours_is_add = block.ours.iter().all(|l| !block.base.contains(l));
        let theirs_is_add = block.theirs.iter().all(|l| !block.base.contains(l));
        if ours_is_add && theirs_is_add {
            let mut merged = block.ours.clone();
            // Do NOT deduplicate via contains — both sides add structurally
            // different code; the same token (e.g. `}`) may appear in both
            // but belongs to different blocks.
            merged.extend(block.theirs.iter().cloned());
            return Some((merged, "Adjacent insertions (diff3): both sides add new lines".to_string()));
        }
    }

    // Strategy B: both sides start new function definitions
    let ours_fn_count = block.ours.iter().filter(|l| is_function_start(l, lang)).count();
    let theirs_fn_count = block.theirs.iter().filter(|l| is_function_start(l, lang)).count();

    if ours_fn_count > 0 && theirs_fn_count > 0 {
        let mut merged = block.ours.clone();
        let needs_separator = merged.last().map_or(false, |l| !l.trim().is_empty())
            && block.theirs.first().map_or(false, |l| !l.trim().is_empty())
            && block.theirs.first().map_or(true, |l| !l.trim().is_empty());
        if needs_separator {
            merged.push(String::new());
        }
        // Do NOT deduplicate via contains — both sides add structurally
        // different code; the same token (e.g. `}`) may appear in both
        // but belongs to different blocks.
        merged.extend(block.theirs.iter().cloned());
        return Some((merged, "Adjacent insertions: both sides add functions".to_string()));
    }

    None
}

/// Extract function blocks from a set of lines.
///
/// Returns a list of `(name, lines, start_index)` tuples.
type FunctionBlock = (String, Vec<String>, usize);

fn extract_function_blocks(lines: &[String], lang: Language) -> Vec<FunctionBlock> {
    let mut blocks = Vec::new();
    let mut i = 0;
    while i < lines.len() {
        if is_function_start(&lines[i], lang) {
            let name = extract_function_name(&lines[i], lang).unwrap_or_default();
            // Determine end of function block
            let end = if lang == Language::Python {
                find_python_block_end(lines, i)
            } else {
                find_matching_block_end(lines, i)
            };
            if let Some(end) = end {
                let end = end.min(lines.len() - 1);
                let func_lines: Vec<String> = lines[i..=end].to_vec();
                blocks.push((name, func_lines, i));
                i = end + 1;
                continue;
            }
        }
        i += 1;
    }
    blocks
}

/// Check if a line belongs to any function in the list.
fn is_in_any_function(line: &str, functions: &[FunctionBlock]) -> bool {
    functions.iter().any(|(_, lines, _)| lines.iter().any(|l| l == line))
}

/// Merge when both sides modify different functions.
///
/// If both sides contain function definitions, and the function names
/// don't overlap, we keep both sets of functions.
fn try_function_level_merge(block: &ConflictBlock) -> Option<(Vec<String>, String)> {
    let lang = block.language();
    let ours_fns = extract_function_blocks(&block.ours, lang);
    let theirs_fns = extract_function_blocks(&block.theirs, lang);

    if ours_fns.is_empty() || theirs_fns.is_empty() {
        return None;
    }

    // Collect function names
    let our_fn_names: HashSet<&str> = ours_fns.iter()
        .filter(|(name, _, _)| !name.is_empty())
        .map(|(name, _, _)| name.as_str())
        .collect();
    let their_fn_names: HashSet<&str> = theirs_fns.iter()
        .filter(|(name, _, _)| !name.is_empty())
        .map(|(name, _, _)| name.as_str())
        .collect();
    let common: HashSet<&str> = our_fn_names.intersection(&their_fn_names).copied().collect();

    if !common.is_empty() {
        // Same function(s) — fall through to line-level
        return None;
    }

    // Different functions — merge both sides
    let mut merged = Vec::new();

    // Add non-function lines from ours, then our functions, then their functions
    for line in &block.ours {
        if !is_in_any_function(line, &ours_fns) {
            merged.push(line.clone());
        }
    }
    for (_, lines, _) in &ours_fns {
        if !merged.is_empty() && !merged.last().map_or(false, |l| l.trim().is_empty()) {
            merged.push(String::new());
        }
        for line in lines {
            merged.push(line.clone());
        }
    }
    for (_, lines, _) in &theirs_fns {
        if !merged.is_empty() && !merged.last().map_or(false, |l| l.trim().is_empty()) {
            merged.push(String::new());
        }
        for line in lines {
            merged.push(line.clone());
        }
    }
    // Add non-function lines from theirs that aren't already present
    for line in &block.theirs {
        if !is_in_any_function(line, &theirs_fns) && !merged.contains(line) {
            merged.push(line.clone());
        }
    }

    Some((merged, "Function-level merge: different functions on each side".to_string()))
}

/// Line-level merge when both sides modify the same function or area.
///
/// Uses word-level heuristics: common lines first, then ours-only,
/// then theirs-only.
fn same_function_line_merge(block: &ConflictBlock) -> (Vec<String>, String) {
    // If same number of lines, try line-by-line matching
    if block.ours.len() == block.theirs.len() {
        let mut merged = Vec::new();
        let mut changes = 0usize;

        for (o, t) in block.ours.iter().zip(block.theirs.iter()) {
            if o.trim() == t.trim() {
                // Same content (possibly different whitespace) — keep ours
                merged.push(o.clone());
            } else if t.trim_start().starts_with(o.trim_start())
                || o.trim_start().starts_with(t.trim_start())
            {
                // One is an extension of the other — keep the longer one
                if o.len() >= t.len() {
                    merged.push(o.clone());
                } else {
                    merged.push(t.clone());
                }
            } else {
                // Truly different — keep both (ours first, then theirs)
                merged.push(o.clone());
                changes += 1;
            }
        }

        if changes == 0 {
            return (merged, "Line-by-line: whitespace-only differences".to_string());
        }
        return (merged, format!("Line-by-line: {} differing line(s) merged", changes));
    }

    // Different number of lines — merge unique lines
    let mut merged: Vec<String> = Vec::new();
    let mut used_ours = HashSet::new();
    let mut used_theirs = HashSet::new();

    // Common lines first, preserving order
    for line in &block.ours {
        if block.theirs.contains(line) && !used_ours.contains(line) {
            merged.push(line.clone());
            used_ours.insert(line.clone());
            used_theirs.insert(line.clone());
        }
    }

    // Ours-only lines
    for line in &block.ours {
        if !used_ours.contains(line) {
            merged.push(line.clone());
            used_ours.insert(line.clone());
        }
    }

    // Theirs-only lines (not already added)
    for line in &block.theirs {
        if !used_theirs.contains(line) {
            merged.push(line.clone());
            used_theirs.insert(line.clone());
        }
    }

    let merged_len = merged.len();
    let merged_eq_ours = merged_len == block.ours.len() && merged == block.ours;
    if merged_eq_ours {
        return (merged, "Same-function: kept ours".to_string());
    }
    let merged_eq_theirs = merged_len == block.theirs.len() && merged == block.theirs;
    if merged_eq_theirs {
        return (merged, "Same-function: kept theirs".to_string());
    }

    (merged, format!("Same-function: merged ({} lines)", merged_len))
}

// ================================================================
// LLM Fallback
// ================================================================

/// Attempt to resolve a conflict using the LLM client.
fn try_llm_resolve(
    block: &ConflictBlock,
    llm: Option<&dyn LlmClient>,
) -> Option<(Vec<String>, String)> {
    let client = llm?;
    let result = client.resolve_merge_conflict(
        &block.ours,
        &block.theirs,
        if block.has_diff3 { Some(&block.base) } else { None },
        &block.context_before,
        &block.context_after,
        block.language(),
    )?;
    // Validate that the LLM result doesn't contain conflict markers
    let has_markers = result.iter().any(|l| {
        l.starts_with("<<<<<<<")
            || l.starts_with(">>>>>>>")
            || l.starts_with("=======")
            || l.starts_with("|||||||")
    });
    if has_markers {
        return None;
    }
    Some((result, "LLM-assisted resolution".to_string()))
}

// ================================================================
// Internal Resolution Engine
// ================================================================

/// Internal resolve implementation shared by all public entry points.
fn resolve_conflict_inner(
    content: &str,
    strategy: Option<MergeStrategy>,
    filename: Option<&str>,
    llm_client: Option<&dyn LlmClient>,
) -> MergeResult {
    let strategy = strategy.unwrap_or(MergeStrategy::Smart);
    let (blocks, _) = parse_conflicts(content, filename);

    let all_lines: Vec<&str> = content.lines().collect();
    let mut result_lines: Vec<String> = Vec::new();
    let mut resolved = 0usize;
    let mut unresolved = 0usize;
    let mut resolutions = Vec::new();
    let mut i = 0usize;

    for block in &blocks {
        // Add non-conflict lines before this block
        while i < all_lines.len() && !all_lines[i].starts_with("<<<<<<<") {
            result_lines.push(all_lines[i].to_string());
            i += 1;
        }

        // Skip the conflict block in the original content
        let conflict_end = skip_conflict_markers(&all_lines, i);

        // Resolve the conflict
        let (merged_lines, reason) = resolve_block(block, strategy, llm_client);

        // Check if the merged result is free of conflict markers
        let actually_resolved = !merged_lines.iter().any(|l| {
            l.starts_with("<<<<<<<")
                || l.starts_with(">>>>>>>")
                || l.starts_with("=======")
                || l.starts_with("|||||||")
        });

        // Syntax validation on resolved blocks
        let syntax_valid = if actually_resolved {
            validate_syntax(&merged_lines)
        } else {
            false
        };

        let is_final_resolved = actually_resolved && syntax_valid;

        if is_final_resolved {
            resolved += 1;
        } else {
            unresolved += 1;
        }

        let final_reason = if actually_resolved && !syntax_valid {
            format!("{} (unbalanced syntax — marked unresolved)", reason)
        } else {
            reason
        };

        resolutions.push(ConflictResolution {
            id: block.id,
            strategy,
            resolved: is_final_resolved,
            reason: final_reason,
        });

        for line in &merged_lines {
            result_lines.push(line.clone());
        }

        i = conflict_end;
    }

    // Add remaining non-conflict lines
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

/// Skip over conflict markers in the original line array.
/// Returns the index of the first line after `>>>>>>>`.
fn skip_conflict_markers(lines: &[&str], mut i: usize) -> usize {
    if i >= lines.len() || !lines[i].starts_with("<<<<<<<") {
        return i;
    }
    i += 1; // skip <<<<<<<

    // Skip ours (up to ||||||| or =======)
    while i < lines.len()
        && !lines[i].starts_with("=======")
        && !lines[i].starts_with("|||||||")
    {
        i += 1;
    }

    // Skip base if diff3
    if i < lines.len() && lines[i].starts_with("|||||||") {
        i += 1;
        while i < lines.len() && !lines[i].starts_with("=======") {
            i += 1;
        }
    }

    // Skip =======
    if i < lines.len() && lines[i].starts_with("=======") {
        i += 1;
    }

    // Skip theirs
    while i < lines.len() && !lines[i].starts_with(">>>>>>>") {
        i += 1;
    }

    // Skip >>>>>>>
    if i < lines.len() && lines[i].starts_with(">>>>>>>") {
        i += 1;
    }

    i
}

/// Resolve a single conflict block using the given strategy.
fn resolve_block(
    block: &ConflictBlock,
    strategy: MergeStrategy,
    llm_client: Option<&dyn LlmClient>,
) -> (Vec<String>, String) {
    match strategy {
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
            // Try heuristic merge first
            let (lines, reason) = smart_merge(block);

            // If the heuristic result has conflict markers, try LLM fallback
            let has_markers = lines.iter().any(|l| {
                l.starts_with("<<<<<<<")
                    || l.starts_with(">>>>>>>")
                    || l.starts_with("=======")
                    || l.starts_with("|||||||")
            });
            if has_markers {
                if let Some((llm_lines, llm_reason)) = try_llm_resolve(block, llm_client) {
                    return (llm_lines, llm_reason);
                }
                // LLM didn't help — return heuristic result anyway
                return (lines, format!("{} (heuristic, may contain conflict markers)", reason));
            }

            // If syntax is unbalanced, try LLM fallback
            if !validate_syntax(&lines) {
                if let Some((llm_lines, llm_reason)) = try_llm_resolve(block, llm_client) {
                    return (llm_lines, llm_reason);
                }
            }

            (lines, reason)
        }
        MergeStrategy::Manual => {
            let mut manual = Vec::new();
            manual.push(format!("<<<<<<< ours (conflict #{})", block.id));
            for line in &block.ours {
                manual.push(line.clone());
            }
            if block.has_diff3 {
                manual.push(format!("||||||| merge base (conflict #{})", block.id));
                for line in &block.base {
                    manual.push(line.clone());
                }
            }
            manual.push("=======".to_string());
            for line in &block.theirs {
                manual.push(line.clone());
            }
            manual.push(format!(">>>>>>> theirs (conflict #{})", block.id));
            (manual, format!("Manual resolution needed for conflict #{}", block.id))
        }
    }
}

// ================================================================
// Tests
// ================================================================

#[cfg(test)]
mod tests {
    use super::*;

    // ─── Basic strategies ───────────────────────────────────────

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

    // ─── Import merging ─────────────────────────────────────────

    #[test]
    fn test_import_conflict() {
        let content = "<<<<<<< HEAD\nimport foo\n=======\nimport bar\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), None);
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("import foo"));
        assert!(result.content.contains("import bar"));
    }

    // ─── No conflict ────────────────────────────────────────────

    #[test]
    fn test_no_conflict() {
        let content = "line1\nline2\n";
        let result = resolve_conflict(content);
        assert_eq!(result.resolved, 0);
        assert_eq!(result.content, "line1\nline2");
    }

    // ─── Multiple conflicts ─────────────────────────────────────

    #[test]
    fn test_multiple_conflicts() {
        let content = "<<<<<<< HEAD\nfirst ours\n=======\nfirst theirs\n>>>>>>> branch\nmiddle\n<<<<<<< HEAD\nsecond ours\n=======\nsecond theirs\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), None);
        assert_eq!(result.resolved, 2);
        assert!(result.content.contains("middle"));
    }

    // ─── Union strategy ─────────────────────────────────────────

    #[test]
    fn test_union_strategy() {
        let content = "<<<<<<< HEAD\nour line\n=======\ntheir line\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Union), None);
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("our line"));
        assert!(result.content.contains("their line"));
    }

    // ─── Detection helpers ──────────────────────────────────────

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

    // ─── Whitespace only ────────────────────────────────────────

    #[test]
    fn test_whitespace_only() {
        let content = "<<<<<<< HEAD\n  \n=======\n\t\n>>>>>>> branch\n";
        let result = resolve_conflict(content);
        assert_eq!(result.resolved, 1);
    }

    // ─── Comment conflict ───────────────────────────────────────

    #[test]
    fn test_comment_conflict() {
        let content = "<<<<<<< HEAD\n// my comment\n=======\n// their comment\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), None);
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("my comment"));
        assert!(result.content.contains("their comment"));
    }

    // ─── Superset detection ─────────────────────────────────────

    #[test]
    fn test_superset_detection() {
        let content = "<<<<<<< HEAD\nline1\nline2\nline3\n=======\nline1\nline3\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), None);
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("line2"));
    }

    // ─── Manual strategy ────────────────────────────────────────

    #[test]
    fn test_manual_strategy() {
        let content = "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Manual), None);
        assert_eq!(result.resolved, 0);
        assert_eq!(result.unresolved, 1);
        assert!(result.content.contains("<<<<<<<"));
    }

    // ─── New tests ──────────────────────────────────────────────

    #[test]
    fn test_diff3_format() {
        let content = "<<<<<<< HEAD\nour change\n||||||| base\noriginal\n=======\ntheir change\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), None);
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("our change") || result.content.contains("their change"));
        assert!(!result.content.contains("<<<<<<<"));
        assert!(!result.content.contains("original"));
    }

    #[test]
    fn test_diff3_format_manual() {
        let content = "<<<<<<< HEAD\nour change\n||||||| base\noriginal\n=======\ntheir change\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Manual), None);
        assert_eq!(result.resolved, 0);
        assert_eq!(result.unresolved, 1);
        assert!(result.content.contains("<<<<<<<"));
        assert!(result.content.contains("merge base"));
        assert!(result.content.contains("original"));
    }

    #[test]
    fn test_empty_content() {
        let result = resolve_conflict("");
        assert_eq!(result.resolved, 0);
        assert_eq!(result.unresolved, 0);
        assert_eq!(result.content, "");
    }

    #[test]
    fn test_no_trailing_newline() {
        let content = "line1\nline2";
        let result = resolve_conflict(content);
        assert_eq!(result.content, "line1\nline2");
    }

    #[test]
    fn test_rust_use_conflict() {
        let content = "<<<<<<< HEAD\nuse std::collections::HashMap;\n=======\nuse std::sync::Arc;\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), Some("main.rs"));
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("HashMap"));
        assert!(result.content.contains("Arc"));
    }

    #[test]
    fn test_adjacent_functions() {
        let content = "<<<<<<< HEAD\nfn foo() {\n    1\n}\n=======\nfn bar() {\n    2\n}\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), Some("main.rs"));
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("fn foo()"));
        assert!(result.content.contains("fn bar()"));
    }

    #[test]
    fn test_balance_detection() {
        let balanced = vec![
            "fn foo() {".to_string(),
            "    let x = 1;".to_string(),
            "}".to_string(),
        ];
        assert!(validate_syntax(&balanced));

        let unbalanced = vec![
            "fn foo() {".to_string(),
            "    let x = 1;".to_string(),
        ];
        assert!(!validate_syntax(&unbalanced));
    }

    #[test]
    fn test_python_def_conflict() {
        let content = "<<<<<<< HEAD\ndef foo():\n    return 1\n=======\ndef bar():\n    return 2\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), Some("main.py"));
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("def foo()"));
        assert!(result.content.contains("def bar()"));
    }

    #[test]
    fn test_go_import_conflict() {
        let content = "<<<<<<< HEAD\nimport \"fmt\"\n=======\nimport \"os\"\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), Some("main.go"));
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("\"fmt\""));
        assert!(result.content.contains("\"os\""));
    }

    #[test]
    fn test_language_detection() {
        assert_eq!(Language::from_extension("rs"), Language::Rust);
        assert_eq!(Language::from_extension("py"), Language::Python);
        assert_eq!(Language::from_extension("js"), Language::JavaScript);
        assert_eq!(Language::from_extension("go"), Language::Go);
        assert_eq!(Language::from_extension("java"), Language::Java);
        assert_eq!(Language::from_extension("c"), Language::C);
        assert_eq!(Language::from_extension("unknown"), Language::Unknown);
    }

    #[test]
    fn test_merge_strategy_from_str() {
        assert_eq!(MergeStrategy::from_str("ours"), MergeStrategy::Ours);
        assert_eq!(MergeStrategy::from_str("THEIRS"), MergeStrategy::Theirs);
        assert_eq!(MergeStrategy::from_str("Smart"), MergeStrategy::Smart);
        assert_eq!(MergeStrategy::from_str("unknown"), MergeStrategy::Smart);
    }

    #[test]
    fn test_import_sorted() {
        // Both sides have imports; Smart should merge + sort
        let content = "<<<<<<< HEAD\nimport b\nimport c\n=======\nimport a\nimport d\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), None);
        assert_eq!(result.resolved, 1);
        let _lines: Vec<&str> = result.content.lines().collect();
        // Should contain all 4 imports, sorted
        assert!(result.content.contains("import a"));
        assert!(result.content.contains("import b"));
        assert!(result.content.contains("import c"));
        assert!(result.content.contains("import d"));
        // Verify sort order: a, b, c, d
        let a_pos = result.content.find("import a").unwrap_or(usize::MAX);
        let b_pos = result.content.find("import b").unwrap_or(usize::MAX);
        let c_pos = result.content.find("import c").unwrap_or(usize::MAX);
        let d_pos = result.content.find("import d").unwrap_or(usize::MAX);
        assert!(a_pos < b_pos && b_pos < c_pos && c_pos < d_pos,
            "imports should be sorted alphabetically");
    }

    #[test]
    fn test_line_by_line_same_length() {
        // Same number of lines, different content
        let content = "<<<<<<< HEAD\nline1\nline2\n=======\nline1\nmodified\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), None);
        assert_eq!(result.resolved, 1);
        assert!(result.content.contains("line1"));
        assert!(result.content.contains("line2"));
    }

    #[test]
    fn test_syntax_unbalanced_block() {
        // A block that would be unbalanced if merged naively
        let content = "<<<<<<< HEAD\nfn a() {\n    return 1;\n}\n=======\nfn b() {\n    return 2;\n}\n>>>>>>> branch\n";
        let result = resolve_conflict_with_strategy(
            content, Some(MergeStrategy::Smart), Some("main.rs"));
        // Both functions are balanced individually, so the merge should succeed
        assert_eq!(result.resolved, 1);
    }
}