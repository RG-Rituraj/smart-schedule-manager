from mcp.server.fastmcp import FastMCP

mcp = FastMCP("smart-schedule-server")

# Mock database
contacts_db = {
    "alice@example.com": {"name": "Alice Smith", "timezone": "America/Los_Angeles"},
    "bob@example.com": {"name": "Bob Jones", "timezone": "America/New_York"},
    "carol@example.com": {"name": "Carol Vance", "timezone": "Europe/London"},
}

calendar_db = [
    {"title": "Sync with Team", "start": "2026-07-02T10:00:00", "end": "2026-07-02T11:00:00", "timezone": "America/Los_Angeles"},
    {"title": "Dentist Appointment", "start": "2026-07-02T14:00:00", "end": "2026-07-02T15:00:00", "timezone": "America/Los_Angeles"},
]

@mcp.tool()
def get_contact_timezone(email: str) -> dict:
    """Retrieve timezone and name for a given contact email.

    Args:
        email: The email address of the contact.
    """
    email_clean = email.strip().lower()
    contact = contacts_db.get(email_clean)
    if contact:
        return {"status": "success", "contact": contact}
    # Return America/New_York as default if contact not found
    return {
        "status": "warning",
        "message": f"Contact '{email}' not found. Defaulting to America/New_York timezone.",
        "contact": {"name": email.split("@")[0].capitalize(), "timezone": "America/New_York"}
    }

@mcp.tool()
def get_calendar_events() -> dict:
    """List all scheduled events on the user's calendar to check for conflicts."""
    return {"status": "success", "events": calendar_db}

@mcp.tool()
def book_calendar_event(title: str, start_time: str, end_time: str, timezone: str) -> dict:
    """Book a new meeting on the calendar.

    Args:
        title: The meeting title.
        start_time: ISO-8601 start time string.
        end_time: ISO-8601 end time string.
        timezone: Timezone identifier (e.g. 'America/Los_Angeles').
    """
    new_event = {
        "title": title,
        "start": start_time,
        "end": end_time,
        "timezone": timezone
    }
    calendar_db.append(new_event)
    return {"status": "success", "message": f"Event '{title}' successfully booked.", "event": new_event}

@mcp.tool()
def send_email_draft(recipient_email: str, subject: str, body: str) -> dict:
    """Send a drafted email to the client.

    Args:
        recipient_email: Email address of the recipient.
        subject: Email subject.
        body: Email body content.
    """
    return {
        "status": "success",
        "message": f"Email successfully sent to {recipient_email}.",
        "details": {"recipient": recipient_email, "subject": subject}
    }

if __name__ == "__main__":
    mcp.run()
