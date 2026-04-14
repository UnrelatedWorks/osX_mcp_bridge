# macOS Bridge MCP — Mail.app & Reminders.app

A local MCP server that connects Claude to your native macOS **Mail.app** and **Reminders.app** via JavaScript for Automation (JXA).

## Requirements

- macOS 12+ (Monterey or later)
- Python 3.10+
- `pip install "mcp[cli]"`

## Quick Setup

### 1. Install dependency

```bash
pip install "mcp[cli]"
```

### 2. Test it works

```bash
cd /path/to/macos_bridge_mcp
python server.py
```

If it starts without errors, press `Ctrl+C` to stop.

### 3. Add to Claude Code / Claude Desktop

**Option A — Claude Code (terminal):**

```bash
claude mcp add macos_bridge -- python /full/path/to/macos_bridge_mcp/server.py
```

**Option B — Claude Desktop (`claude_desktop_config.json`):**

Add this to your config file (usually at `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "macos_bridge": {
      "command": "python",
      "args": ["/full/path/to/macos_bridge_mcp/server.py"]
    }
  }
}
```

### 4. Grant permissions

The first time a tool runs, macOS will ask you to grant Automation access. Go to:

**System Settings → Privacy & Security → Automation**

Allow your terminal (or Claude Desktop) to control **Mail** and **Reminders**.

## Available Tools

### Reminders.app

| Tool | Description |
|------|-------------|
| `reminders_get_lists` | List all reminder lists with counts |
| `reminders_list` | Fetch reminders (filter by list, completed status) |
| `reminders_create` | Create a new reminder (with due date, priority, notes) |
| `reminders_complete` | Mark a reminder as done |

### Mail.app

| Tool | Description |
|------|-------------|
| `mail_list_accounts` | List all mail accounts |
| `mail_list_mailboxes` | List all mailboxes/folders with unread counts |
| `mail_fetch_messages` | Fetch recent messages (newest first) |
| `mail_read_message` | Read the full content of a specific email |
| `mail_search` | Search emails by subject or sender |

## Notes

- This server uses **stdio** transport (local only, no network exposure)
- All Mail.app tools are **read-only** — no sending or deleting
- Reminders tools can read, create, and complete reminders
- JXA runs via `osascript`, which is built into macOS
