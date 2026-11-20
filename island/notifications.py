"""Mirror new Windows toast notifications as a pill (Nusa: UserNotificationListener, "notif_pill")."""
import asyncio
import sys

ALLOWED = 1  # UserNotificationListenerAccessStatus.ALLOWED


def default_listener():
    from winrt.windows.ui.notifications.management import UserNotificationListener
    return UserNotificationListener.current


def _texts(toast):
    from winrt.windows.ui.notifications import KnownNotificationBindings
    binding = toast.notification.visual.get_binding(KnownNotificationBindings.toast_generic)
    return [t.text for t in binding.get_text_elements()] if binding else []


class Listener:
    def __init__(self, listener=None):
        self.seen = None  # toast ids already in the action center; None until the first successful read
        try:
            self.listener = listener or default_listener()
            self.available = int(asyncio.run(self._access())) == ALLOWED
        except Exception as e:  # no package identity / API missing: the feature just stays off
            print("notifications unavailable:", type(e).__name__, file=sys.stderr)
            self.listener, self.available = None, False

    async def _access(self):  # asyncio.run needs a coroutine; WinRT operations are only awaitables
        return await self.listener.request_access_async()

    async def _read(self):
        from winrt.windows.ui.notifications import NotificationKinds
        return list(await self.listener.get_notifications_async(NotificationKinds.TOAST))

    def poll(self):
        """[(app, title, body)] for toasts that appeared since the last poll; the first poll only records."""
        if not self.available:
            return []
        try:
            toasts = asyncio.run(self._read())
            new = [] if self.seen is None else [t for t in toasts if t.id not in self.seen]
            out = []
            for t in new:
                texts = _texts(t) + ["", ""]
                app = t.app_info.display_info.display_name if t.app_info else ""
                out.append((app, texts[0], texts[1]))
        except Exception as e:  # keep the old baseline so a glitch doesn't replay every toast
            print("notifications read failed:", type(e).__name__, file=sys.stderr)
            return []
        self.seen = {t.id for t in toasts}
        return out
