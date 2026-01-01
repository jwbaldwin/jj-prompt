//! jj-prompt - Fast JJ prompt for starship
//!
//! Output format: ` {change_id} {bookmarks} {status} {~file_count} {description}`
//! Matches jj's native coloring exactly.

use clap::{Parser, Subcommand};
use jj_lib::config::{ConfigLayer, ConfigSource, StackedConfig};
use jj_lib::hex_util::encode_reverse_hex;
use jj_lib::object_id::ObjectId;
use jj_lib::repo::{Repo, StoreFactories};
use jj_lib::settings::UserSettings;
use jj_lib::workspace::{default_working_copy_factories, Workspace};
use std::env;
use std::path::{Path, PathBuf};
use std::process::{Command as ProcessCommand, ExitCode, Stdio};

#[derive(Parser)]
#[command(name = "jj-prompt")]
#[command(version)]
struct Cli {
    #[command(subcommand)]
    command: Option<Command>,

    /// Override working directory
    #[arg(long)]
    cwd: Option<PathBuf>,

    /// Length of change_id to display (default: 4)
    #[arg(long, default_value = "4")]
    id_length: usize,

    /// Symbol prefix (default: "  ")
    #[arg(long, default_value = "  ")]
    symbol: String,

    /// Disable colors
    #[arg(long)]
    no_color: bool,

    /// Skip file count (faster)
    #[arg(long)]
    no_file_count: bool,
}

#[derive(Subcommand)]
enum Command {
    /// Output prompt string (default)
    Prompt,
    /// Exit 0 if in jj repo, 1 otherwise
    Detect,
}

/// ANSI color codes matching jj's native output
mod color {
    pub const RESET: &str = "\x1b[0m";
    pub const RESET_COLOR: &str = "\x1b[39m";
    // Symbol: green
    pub const SYMBOL: &str = "\x1b[32m";
    // Change ID: bold + 256-color magenta (5) for prefix, 256-color gray (8) for rest
    pub const CHANGE_ID_PREFIX: &str = "\x1b[1m\x1b[38;5;5m";
    pub const CHANGE_ID_REST: &str = "\x1b[0m\x1b[38;5;8m";
    // Bookmarks: 256-color magenta (5), no bold
    pub const BOOKMARK: &str = "\x1b[38;5;5m";
    // Dim for description and file count
    pub const DIM: &str = "\x1b[2m";
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let cwd = cli
        .cwd
        .clone()
        .or_else(|| env::current_dir().ok())
        .unwrap_or_default();

    match cli.command {
        Some(Command::Detect) => {
            if find_jj_root(&cwd).is_some() {
                ExitCode::SUCCESS
            } else {
                ExitCode::FAILURE
            }
        }
        Some(Command::Prompt) | None => {
            if let Some(output) = run_prompt(&cwd, &cli) {
                print!("{output}");
                ExitCode::SUCCESS
            } else {
                ExitCode::FAILURE
            }
        }
    }
}

/// Walk up directory tree to find .jj
fn find_jj_root(start: &Path) -> Option<PathBuf> {
    let mut current = start.to_path_buf();
    loop {
        if current.join(".jj").is_dir() {
            return Some(current);
        }
        if !current.pop() {
            return None;
        }
    }
}

/// Create minimal UserSettings for read-only operations
fn create_user_settings() -> Option<UserSettings> {
    let mut config = StackedConfig::with_defaults();
    let mut user_layer = ConfigLayer::empty(ConfigSource::User);
    user_layer.set_value("user.name", "jj-prompt").ok()?;
    user_layer
        .set_value("user.email", "jj-prompt@localhost")
        .ok()?;
    config.add_layer(user_layer);
    UserSettings::from_config(config).ok()
}

/// Get file count by shelling out to jj (the tree diff API is complex)
fn get_file_count(repo_root: &Path) -> Option<usize> {
    let output = ProcessCommand::new("jj")
        .args(["diff", "--stat", "--ignore-working-copy"])
        .current_dir(repo_root)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .ok()?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    // Last line looks like: "9 files changed, 449 insertions(+), 187 deletions(-)"
    // Or just a single file: "1 file changed, 10 insertions(+)"
    let last_line = stdout.lines().last()?;

    // Extract the first number (file count)
    last_line
        .split_whitespace()
        .next()
        .and_then(|s| s.parse::<usize>().ok())
        .filter(|&n| n > 0)
}

fn run_prompt(cwd: &Path, cli: &Cli) -> Option<String> {
    let repo_root = find_jj_root(cwd)?;
    let settings = create_user_settings()?;

    let workspace = Workspace::load(
        &settings,
        &repo_root,
        &StoreFactories::default(),
        &default_working_copy_factories(),
    )
    .ok()?;

    let repo = workspace.repo_loader().load_at_head().ok()?;
    let view = repo.view();

    // Get working copy commit
    let wc_id = view.wc_commit_ids().get(workspace.workspace_name())?;
    let commit = repo.store().get_commit(wc_id).ok()?;

    // Change ID (reverse hex format like jj uses)
    let change_id_full = encode_reverse_hex(commit.change_id().as_bytes());
    let change_id = &change_id_full[..cli.id_length.min(change_id_full.len())];

    // Get unique prefix length for coloring
    let prefix_len = repo
        .shortest_unique_change_id_prefix_len(commit.change_id())
        .unwrap_or(cli.id_length)
        .min(change_id.len());

    // Bookmarks on this commit
    let bookmarks: Vec<String> = view
        .local_bookmarks_for_commit(wc_id)
        .map(|(name, _)| name.as_str().to_string())
        .collect();

    // Description (first line)
    let description = commit.description().lines().next().unwrap_or("").trim();

    // Status indicators
    let has_conflict = commit.has_conflict();
    let is_divergent = repo
        .resolve_change_id(commit.change_id())
        .ok()
        .flatten()
        .is_some_and(|commits| commits.len() > 1);

    // File count (optional, shells out to jj)
    let file_count = if cli.no_file_count {
        None
    } else {
        get_file_count(&repo_root)
    };

    // Build output
    let mut output = String::new();

    // Symbol (green)
    if cli.no_color {
        output.push_str(&cli.symbol);
    } else {
        output.push_str(color::SYMBOL);
        output.push_str(&cli.symbol);
        output.push_str(color::RESET);
    }

    // Change ID with jj's native coloring
    if cli.no_color {
        output.push_str(change_id);
    } else {
        let (prefix, suffix) = change_id.split_at(prefix_len);
        output.push_str(color::CHANGE_ID_PREFIX);
        output.push_str(prefix);
        output.push_str(color::CHANGE_ID_REST);
        output.push_str(suffix);
        output.push_str(color::RESET_COLOR);
    }

    // Bookmarks (with jj's native coloring)
    if !bookmarks.is_empty() {
        output.push(' ');
        if cli.no_color {
            output.push_str(&bookmarks.join(" "));
        } else {
            output.push_str(color::BOOKMARK);
            output.push_str(&bookmarks.join(" "));
            output.push_str(color::RESET);
        }
    }

    // Status indicators (conflict and divergent)
    let mut status = String::new();
    if has_conflict {
        status.push('>');
    }
    if is_divergent {
        status.push('\\');
    }
    if !status.is_empty() {
        output.push(' ');
        output.push_str(&status);
    }

    // File count (dimmed)
    if let Some(count) = file_count {
        output.push(' ');
        if cli.no_color {
            output.push_str(&format!("~{}", count));
        } else {
            output.push_str(color::DIM);
            output.push_str(&format!("~{}", count));
            output.push_str(color::RESET);
        }
    }

    // Description (dimmed, skip if empty or default)
    if !description.is_empty() && description != "(no description set)" {
        output.push(' ');
        if cli.no_color {
            output.push_str(description);
        } else {
            output.push_str(color::DIM);
            output.push_str(description);
            output.push_str(color::RESET);
        }
    }

    Some(output)
}
