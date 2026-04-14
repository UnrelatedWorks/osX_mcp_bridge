#!/usr/bin/env python3
"""
MCP Server for macOS Mail.app and Reminders.app.

Bridges Claude to native macOS apps via AppleScript (osascript).
Designed to run locally on macOS via stdio transport.

Requirements:
    pip install "mcp[cli]"

Usage:
    python server.py
"""

import json
import subprocess
from typing import Optional, List
from datetime import datetime, date
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

# ─── Server ───────────────────────────────────────────────────────────

mcp = FastMCP("macos_bridge_mcp")

# ─── Helpers ──────────────────────────────────────────────────────────

def _run_applescript(script: str, timeout: int = 30) -> str:
    """Execute an AppleScript via osascript and return stdout."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            # Common macOS permission errors
            if "not allowed" in err.lower() or "access" in err.lower():
                return (
                    f"Error: macOS denied access. Open System Settings → "
                    f"Privacy & Security → Automation and grant this terminal "
                    f"access to Mail / Reminders.\n\nFull error: {err}"
                )
            return f"Error: AppleScript failed — {err}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: AppleScript timed out. The app may be unresponsive."
    except FileNotFoundError:
        return "Error: osascript not found. This server must run on macOS."
    except Exception as e:
        return f"Error: {type(e).__name__} — {e}"


def _run_jxa(script: str, timeout: int = 30) -> str:
    """Execute a JXA (JavaScript for Automation) script via osascript."""
    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            if "not allowed" in err.lower() or "access" in err.lower():
                return (
                    f"Error: macOS denied access. Open System Settings → "
                    f"Privacy & Security → Automation and grant this terminal "
                    f"access to Mail / Reminders.\n\nFull error: {err}"
                )
            return f"Error: JXA failed — {err}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Script timed out."
    except FileNotFoundError:
        return "Error: osascript not found. This server must run on macOS."
    except Exception as e:
        return f"Error: {type(e).__name__} — {e}"


# ═══════════════════════════════════════════════════════════════════════
#  REMINDERS.APP TOOLS
# ═══════════════════════════════════════════════════════════════════════

class ListRemindersInput(BaseModel):
    """Input for listing reminders."""
    model_config = ConfigDict(str_strip_whitespace=True)

    list_name: Optional[str] = Field(
        default=None,
        description="Name of the Reminders list to fetch (e.g., 'Work', 'Personal'). "
                    "Omit to fetch reminders from ALL lists.",
    )
    include_completed: bool = Field(
        default=False,
        description="Include already-completed reminders.",
    )
    limit: int = Field(
        default=50,
        description="Maximum number of reminders to return.",
        ge=1,
        le=200,
    )


@mcp.tool(
    name="reminders_list",
    annotations={
        "title": "List Reminders",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def reminders_list(params: ListRemindersInput) -> str:
    """List reminders from macOS Reminders.app.

    Returns reminders with their name, due date, priority, notes,
    completion status, and which list they belong to.

    Args:
        params: Filter by list name, completion status, and limit.

    Returns:
        JSON array of reminder objects.
    """
    if params.list_name:
        list_filter = f'whose name is "{params.list_name}"'
    else:
        list_filter = ""

    completed_filter = "" if params.include_completed else "whose completed is false"
    limit = params.limit

    jxa = f"""
    (() => {{
        const app = Application("Reminders");
        app.includeStandardAdditions = true;
        const results = [];
        let lists;
        {"" if not params.list_name else ""}
        try {{
            lists = {"app.lists.whose({name: '" + params.list_name + "'})()" if params.list_name else "app.lists()"};
        }} catch(e) {{
            return JSON.stringify({{error: "Could not access Reminders: " + e.message}});
        }}
        for (const lst of lists) {{
            const listName = lst.name();
            let rems;
            try {{
                rems = {"lst.reminders.whose({completed: false})()" if not params.include_completed else "lst.reminders()"};
            }} catch(e) {{
                continue;
            }}
            for (const r of rems) {{
                if (results.length >= {limit}) break;
                let dueDate = null;
                try {{ dueDate = r.dueDate() ? r.dueDate().toISOString() : null; }} catch(e) {{}}
                let body = null;
                try {{ body = r.body(); }} catch(e) {{}}
                let priority = 0;
                try {{ priority = r.priority(); }} catch(e) {{}}
                let completed = false;
                try {{ completed = r.completed(); }} catch(e) {{}}
                let completionDate = null;
                try {{ completionDate = r.completionDate() ? r.completionDate().toISOString() : null; }} catch(e) {{}}
                results.push({{
                    name: r.name(),
                    list: listName,
                    dueDate: dueDate,
                    priority: priority,
                    notes: body,
                    completed: completed,
                    completionDate: completionDate
                }});
            }}
            if (results.length >= {limit}) break;
        }}
        return JSON.stringify(results, null, 2);
    }})()
    """
    return _run_jxa(jxa, timeout=45)


class GetReminderListsInput(BaseModel):
    """Input for getting available reminder lists."""
    model_config = ConfigDict(str_strip_whitespace=True)


@mcp.tool(
    name="reminders_get_lists",
    annotations={
        "title": "Get Reminder Lists",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def reminders_get_lists(params: GetReminderListsInput) -> str:
    """Get all available Reminders lists (e.g., 'Work', 'Personal', 'Groceries').

    Returns:
        JSON array of list names with reminder counts.
    """
    jxa = """
    (() => {
        const app = Application("Reminders");
        const results = [];
        for (const lst of app.lists()) {
            let total = 0;
            let incomplete = 0;
            try {
                total = lst.reminders().length;
                incomplete = lst.reminders.whose({completed: false})().length;
            } catch(e) {}
            results.push({
                name: lst.name(),
                totalReminders: total,
                incompleteReminders: incomplete
            });
        }
        return JSON.stringify(results, null, 2);
    })()
    """
    return _run_jxa(jxa)


class CreateReminderInput(BaseModel):
    """Input for creating a new reminder."""
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(
        ..., description="The reminder title.", min_length=1, max_length=500
    )
    list_name: Optional[str] = Field(
        default=None,
        description="Which Reminders list to add it to (defaults to the default list).",
    )
    due_date: Optional[str] = Field(
        default=None,
        description="Due date in ISO 8601 format, e.g. '2026-04-15' or '2026-04-15T14:00:00'.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Additional notes for the reminder.",
    )
    priority: Optional[int] = Field(
        default=None,
        description="Priority: 0 = none, 1 = high, 5 = medium, 9 = low.",
        ge=0,
        le=9,
    )


@mcp.tool(
    name="reminders_create",
    annotations={
        "title": "Create Reminder",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def reminders_create(params: CreateReminderInput) -> str:
    """Create a new reminder in macOS Reminders.app.

    Args:
        params: Reminder details (name, list, due date, notes, priority).

    Returns:
        Confirmation message with the created reminder details.
    """
    props = [f'name: "{_escape_js(params.name)}"']
    if params.notes:
        props.append(f'body: "{_escape_js(params.notes)}"')
    if params.priority is not None:
        props.append(f"priority: {params.priority}")

    due_date_line = ""
    if params.due_date:
        due_date_line = f'r.dueDate = new Date("{params.due_date}");'

    list_target = (
        f'app.lists.whose({{name: "{_escape_js(params.list_name)}"}})[0]'
        if params.list_name
        else "app.defaultList()"
    )

    jxa = f"""
    (() => {{
        const app = Application("Reminders");
        const targetList = {list_target};
        const r = app.Reminder({{{", ".join(props)}}});
        targetList.reminders.push(r);
        {due_date_line}
        return JSON.stringify({{
            success: true,
            name: r.name(),
            list: targetList.name(),
            dueDate: r.dueDate() ? r.dueDate().toISOString() : null
        }}, null, 2);
    }})()
    """
    return _run_jxa(jxa)


class CompleteReminderInput(BaseModel):
    """Input for completing a reminder."""
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(
        ..., description="The exact name of the reminder to mark as completed."
    )
    list_name: Optional[str] = Field(
        default=None,
        description="The list to search in. Omit to search all lists.",
    )


@mcp.tool(
    name="reminders_complete",
    annotations={
        "title": "Complete Reminder",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def reminders_complete(params: CompleteReminderInput) -> str:
    """Mark a reminder as completed in Reminders.app.

    Args:
        params: The reminder name (and optionally which list).

    Returns:
        Confirmation or error message.
    """
    list_part = (
        f'app.lists.whose({{name: "{_escape_js(params.list_name)}"}})'
        if params.list_name
        else "app.lists()"
    )

    jxa = f"""
    (() => {{
        const app = Application("Reminders");
        const lists = {list_part};
        const target = "{_escape_js(params.name)}";
        for (const lst of {"lists" if not params.list_name else "[lists[0]]"}) {{
            const matches = lst.reminders.whose({{name: target, completed: false}})();
            if (matches.length > 0) {{
                matches[0].completed = true;
                return JSON.stringify({{
                    success: true,
                    name: target,
                    list: lst.name(),
                    completedAt: new Date().toISOString()
                }});
            }}
        }}
        return JSON.stringify({{success: false, error: "Reminder not found: " + target}});
    }})()
    """
    return _run_jxa(jxa)


# ═══════════════════════════════════════════════════════════════════════
#  MAIL.APP TOOLS
# ═══════════════════════════════════════════════════════════════════════

class ListMailAccountsInput(BaseModel):
    """Input for listing mail accounts."""
    model_config = ConfigDict(str_strip_whitespace=True)


@mcp.tool(
    name="mail_list_accounts",
    annotations={
        "title": "List Mail Accounts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mail_list_accounts(params: ListMailAccountsInput) -> str:
    """List all configured mail accounts in Mail.app.

    Returns:
        JSON array of account names and email addresses.
    """
    jxa = """
    (() => {
        const mail = Application("Mail");
        const results = [];
        for (const acct of mail.accounts()) {
            let emails = [];
            try { emails = acct.emailAddresses(); } catch(e) {}
            results.push({
                name: acct.name(),
                emails: emails,
                enabled: acct.enabled()
            });
        }
        return JSON.stringify(results, null, 2);
    })()
    """
    return _run_jxa(jxa)


class ListMailboxesInput(BaseModel):
    """Input for listing mailboxes."""
    model_config = ConfigDict(str_strip_whitespace=True)

    account_name: Optional[str] = Field(
        default=None,
        description="Filter to a specific account. Omit for all accounts.",
    )


@mcp.tool(
    name="mail_list_mailboxes",
    annotations={
        "title": "List Mailboxes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mail_list_mailboxes(params: ListMailboxesInput) -> str:
    """List all mailboxes (folders) in Mail.app.

    Returns:
        JSON array of mailbox names with unread counts.
    """
    if params.account_name:
        jxa = f"""
        (() => {{
            const mail = Application("Mail");
            const acct = mail.accounts.whose({{name: "{_escape_js(params.account_name)}"}})[0];
            const results = [];
            for (const mb of acct.mailboxes()) {{
                results.push({{
                    name: mb.name(),
                    unreadCount: mb.unreadCount(),
                    messageCount: mb.messages().length,
                    account: "{_escape_js(params.account_name)}"
                }});
            }}
            return JSON.stringify(results, null, 2);
        }})()
        """
    else:
        jxa = """
        (() => {
            const mail = Application("Mail");
            const results = [];
            for (const acct of mail.accounts()) {
                for (const mb of acct.mailboxes()) {
                    results.push({
                        name: mb.name(),
                        unreadCount: mb.unreadCount(),
                        account: acct.name()
                    });
                }
            }
            return JSON.stringify(results, null, 2);
        })()
        """
    return _run_jxa(jxa)


class FetchMailInput(BaseModel):
    """Input for fetching recent mail messages."""
    model_config = ConfigDict(str_strip_whitespace=True)

    mailbox: str = Field(
        default="INBOX",
        description="Mailbox name to fetch from (e.g., 'INBOX', 'Sent', 'Drafts').",
    )
    account_name: Optional[str] = Field(
        default=None,
        description="Account name. Omit to search across all accounts.",
    )
    limit: int = Field(
        default=20,
        description="Maximum number of messages to return.",
        ge=1,
        le=100,
    )
    unread_only: bool = Field(
        default=False,
        description="Only return unread messages.",
    )


@mcp.tool(
    name="mail_fetch_messages",
    annotations={
        "title": "Fetch Mail Messages",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mail_fetch_messages(params: FetchMailInput) -> str:
    """Fetch recent email messages from Mail.app.

    Returns message subject, sender, date, read status, and a preview
    of the body text. Messages are sorted newest-first.

    Args:
        params: Mailbox, account, limit, and unread filter.

    Returns:
        JSON array of message objects.
    """
    account_filter = (
        f'mail.accounts.whose({{name: "{_escape_js(params.account_name)}"}})[0]'
        if params.account_name
        else None
    )

    # Build the JXA script
    jxa = f"""
    (() => {{
        const mail = Application("Mail");
        const results = [];
        const limit = {params.limit};
        const unreadOnly = {"true" if params.unread_only else "false"};
        const targetMailbox = "{_escape_js(params.mailbox)}";

        function processMailbox(mb, acctName) {{
            let msgs;
            try {{
                msgs = mb.messages();
            }} catch(e) {{ return; }}

            // Messages are usually newest-first already
            for (let i = 0; i < msgs.length && results.length < limit; i++) {{
                const m = msgs[i];
                try {{
                    const isRead = m.readStatus();
                    if (unreadOnly && isRead) continue;

                    let preview = "";
                    try {{
                        const content = m.content();
                        if (content) preview = content.substring(0, 300);
                    }} catch(e) {{}}

                    results.push({{
                        subject: m.subject(),
                        sender: m.sender(),
                        dateSent: m.dateSent() ? m.dateSent().toISOString() : null,
                        dateReceived: m.dateReceived() ? m.dateReceived().toISOString() : null,
                        isRead: isRead,
                        account: acctName,
                        preview: preview
                    }});
                }} catch(e) {{
                    // Skip problematic messages
                }}
            }}
        }}

        {"const acct = " + account_filter + ";" if account_filter else ""}
        {"" if account_filter else "for (const acct of mail.accounts()) {"}
            try {{
                const mb = acct.mailboxes.whose({{name: targetMailbox}})[0];
                processMailbox(mb, acct.name());
            }} catch(e) {{}}
        {"" if account_filter else "}"}

        return JSON.stringify(results, null, 2);
    }})()
    """
    return _run_jxa(jxa, timeout=60)


class ReadMailInput(BaseModel):
    """Input for reading a specific email's full body."""
    model_config = ConfigDict(str_strip_whitespace=True)

    subject: str = Field(
        ..., description="Subject line of the email to read (exact or partial match)."
    )
    sender: Optional[str] = Field(
        default=None,
        description="Sender email or name to narrow the search.",
    )
    mailbox: str = Field(
        default="INBOX",
        description="Mailbox to search in.",
    )
    account_name: Optional[str] = Field(
        default=None,
        description="Account name to search in.",
    )


@mcp.tool(
    name="mail_read_message",
    annotations={
        "title": "Read Mail Message",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mail_read_message(params: ReadMailInput) -> str:
    """Read the full content of a specific email in Mail.app.

    Searches for a message by subject (and optionally sender) and returns
    the full body text plus metadata.

    Args:
        params: Subject to search for, optional sender and mailbox filters.

    Returns:
        JSON object with full message content, or error if not found.
    """
    sender_check = ""
    if params.sender:
        sender_check = f"""
            const senderStr = m.sender().toLowerCase();
            if (!senderStr.includes("{_escape_js(params.sender.lower())}")) continue;
        """

    account_filter = (
        f'mail.accounts.whose({{name: "{_escape_js(params.account_name)}"}})[0]'
        if params.account_name
        else None
    )

    jxa = f"""
    (() => {{
        const mail = Application("Mail");
        const searchSubject = "{_escape_js(params.subject)}".toLowerCase();
        const targetMailbox = "{_escape_js(params.mailbox)}";

        {"const acct = " + account_filter + ";" if account_filter else ""}
        {"" if account_filter else "for (const acct of mail.accounts()) {"}
            try {{
                const mb = acct.mailboxes.whose({{name: targetMailbox}})[0];
                const msgs = mb.messages();
                for (let i = 0; i < msgs.length && i < 200; i++) {{
                    const m = msgs[i];
                    try {{
                        if (!m.subject().toLowerCase().includes(searchSubject)) continue;
                        {sender_check}
                        let content = "";
                        try {{ content = m.content(); }} catch(e) {{}}
                        let toRecipients = [];
                        try {{
                            toRecipients = m.toRecipients().map(r => ({{
                                name: r.name(),
                                address: r.address()
                            }}));
                        }} catch(e) {{}}
                        let ccRecipients = [];
                        try {{
                            ccRecipients = m.ccRecipients().map(r => ({{
                                name: r.name(),
                                address: r.address()
                            }}));
                        }} catch(e) {{}}
                        return JSON.stringify({{
                            subject: m.subject(),
                            sender: m.sender(),
                            dateSent: m.dateSent() ? m.dateSent().toISOString() : null,
                            to: toRecipients,
                            cc: ccRecipients,
                            isRead: m.readStatus(),
                            content: content
                        }}, null, 2);
                    }} catch(e) {{}}
                }}
            }} catch(e) {{}}
        {"" if account_filter else "}"}

        return JSON.stringify({{error: "Message not found matching subject: " + searchSubject}});
    }})()
    """
    return _run_jxa(jxa, timeout=60)


class SearchMailInput(BaseModel):
    """Input for searching mail."""
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(
        ..., description="Search term to match against subject lines and sender.", min_length=1
    )
    mailbox: str = Field(
        default="INBOX",
        description="Mailbox to search in.",
    )
    account_name: Optional[str] = Field(
        default=None,
        description="Account to search in. Omit for all accounts.",
    )
    limit: int = Field(
        default=15,
        description="Maximum results.",
        ge=1,
        le=50,
    )


@mcp.tool(
    name="mail_search",
    annotations={
        "title": "Search Mail",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mail_search(params: SearchMailInput) -> str:
    """Search emails in Mail.app by subject or sender.

    Args:
        params: Search query, mailbox, account, and result limit.

    Returns:
        JSON array of matching messages (subject, sender, date, preview).
    """
    account_filter = (
        f'mail.accounts.whose({{name: "{_escape_js(params.account_name)}"}})[0]'
        if params.account_name
        else None
    )

    jxa = f"""
    (() => {{
        const mail = Application("Mail");
        const q = "{_escape_js(params.query)}".toLowerCase();
        const limit = {params.limit};
        const targetMailbox = "{_escape_js(params.mailbox)}";
        const results = [];

        {"const acct = " + account_filter + ";" if account_filter else ""}
        {"" if account_filter else "for (const acct of mail.accounts()) {"}
            try {{
                const mb = acct.mailboxes.whose({{name: targetMailbox}})[0];
                const msgs = mb.messages();
                for (let i = 0; i < msgs.length && results.length < limit; i++) {{
                    const m = msgs[i];
                    try {{
                        const subj = m.subject() || "";
                        const sender = m.sender() || "";
                        if (subj.toLowerCase().includes(q) || sender.toLowerCase().includes(q)) {{
                            let preview = "";
                            try {{ preview = (m.content() || "").substring(0, 200); }} catch(e) {{}}
                            results.push({{
                                subject: subj,
                                sender: sender,
                                dateSent: m.dateSent() ? m.dateSent().toISOString() : null,
                                isRead: m.readStatus(),
                                account: acct.name(),
                                preview: preview
                            }});
                        }}
                    }} catch(e) {{}}
                }}
            }} catch(e) {{}}
        {"" if account_filter else "}"}

        return JSON.stringify(results, null, 2);
    }})()
    """
    return _run_jxa(jxa, timeout=60)


# ─── Shared Utilities ─────────────────────────────────────────────────

def _escape_js(s: str) -> str:
    """Escape a string for safe embedding in JavaScript/JXA."""
    if not s:
        return ""
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


# ─── Entrypoint ───────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
