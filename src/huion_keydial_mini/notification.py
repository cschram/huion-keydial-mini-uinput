"""Native OS notification wrapper for Linux using notify-send."""

import logging
import subprocess

logger = logging.getLogger(__name__)


def notify(title: str, message: str, icon: str = "dialog-information") -> bool:
    """Send a native OS notification via notify-send.

    Fire-and-forget: spawns notify-send without waiting for it to exit so this
    function is safe to call from an asyncio event loop.

    Args:
        title: Notification title
        message: Notification body text
        icon: Icon name (default: dialog-information)

    Returns:
        True if the process was spawned successfully, False otherwise
    """
    try:
        subprocess.Popen(
            ["notify-send", title, message, "-i", icon],
            close_fds=True,
        )
        return True
    except Exception as e:
        logger.warning(f"Failed to send notification: {e}")
        return False
