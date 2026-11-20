"""Internet connectivity via WinRT NetworkInformation (Nusa: Windows.Networking.Connectivity, Wi-Fi popup)."""
from winrt.windows.networking.connectivity import NetworkConnectivityLevel, NetworkInformation


def network_state():
    """(has internet, profile name or None). Raises on WinRT errors: the caller keeps its old baseline."""
    profile = NetworkInformation.get_internet_connection_profile()
    if profile is None:
        return False, None
    online = profile.get_network_connectivity_level() == NetworkConnectivityLevel.INTERNET_ACCESS
    return online, profile.profile_name if online else None


def network_popup(prev, cur):
    """(title, subtitle) when the state changed after a known baseline, else None."""
    if prev is None or prev == cur:
        return None
    return ("Connected", cur[1] or "Internet") if cur[0] else ("Disconnected", "No internet")
