import ctypes


WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"


def show_message(title, message, is_error=False):
    flags = 0x10 if is_error else 0x40
    ctypes.windll.user32.MessageBoxW(None, str(message), str(title), flags)


def show_notification(title, message, plugin_dir, logger=None):
    try:
        from winotify import Notification

        icon_path = plugin_dir / "keep.png"
        toast = Notification(
            app_id="GoogleKeepFlow",
            title=title,
            msg=message,
            icon=str(icon_path) if icon_path.exists() else None,
        )
        toast.show()
        if logger:
            logger.info("Notification shown: %s", title)
        return True
    except Exception as exc:
        if logger:
            logger.warning("Failed to show notification: %s: %s", type(exc).__name__, exc)
        return False


def show_link_notification(title, message, url, plugin_dir, action_label="Open", logger=None):
    try:
        from winotify import Notification

        icon_path = plugin_dir / "keep.png"
        toast = Notification(
            app_id="GoogleKeepFlow",
            title=title,
            msg=message,
            icon=str(icon_path) if icon_path.exists() else None,
            duration="long",
            launch=url,
        )
        toast.add_actions(action_label, url)
        toast.show()
        if logger:
            logger.info("Link notification shown: %s", title)
        return True
    except Exception as exc:
        if logger:
            logger.warning("Failed to show link notification: %s: %s", type(exc).__name__, exc)
        return False


def is_webview2_runtime_error(error):
    text = f"{type(error).__name__}: {error}".lower()
    markers = (
        "webview2",
        "edgechromium",
        "edge webview",
        "could not load runtime",
        "runtime is not installed",
        "webviewruntime",
    )
    return any(marker in text for marker in markers)


def is_pythonnet_runtime_error(error):
    text = f"{type(error).__name__}: {error}".lower()
    markers = (
        "python.runtime.dll",
        "python.runtime.loader.initialize",
        "failed to resolve python.runtime",
        "pythonnet",
    )
    return any(marker in text for marker in markers)


def show_webview2_missing_notice(plugin_dir, logger=None):
    message = (
        "Edge WebView2 Runtime is not installed.\n\n"
        "Install Evergreen Standalone:\n"
        "developer.microsoft.com/microsoft-edge/webview2"
    )
    if not show_link_notification(
        "GoogleKeepFlow setup needs WebView2",
        "Install Evergreen Standalone Installer, then run keep setup again.",
        WEBVIEW2_DOWNLOAD_URL,
        plugin_dir,
        action_label="Download WebView2",
        logger=logger,
    ):
        show_message("GoogleKeepFlow Setup", message, is_error=True)


def show_manual_install_notice(log_file):
    show_message(
        "GoogleKeepFlow Setup",
        "Failed to start the setup window.\n\n"
        "This may happen if the plugin folder was copied into Flow Launcher plugins manually.\n"
        "Install GoogleKeepFlow through Flow Launcher Plugin Store or Install from local path, then run keep setup again.\n\n"
        f"Details saved to:\n{log_file}",
        is_error=True,
    )

