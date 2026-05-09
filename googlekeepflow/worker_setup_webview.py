#!/usr/bin/env python
import json
import logging
import os
import sys
import threading
import time
import shutil
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

package_dir = Path(__file__).parent.resolve()
plugindir = package_dir.parent
if str(plugindir) not in sys.path:
    sys.path.insert(0, str(plugindir))
lib_path = plugindir / "lib"
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

from googlekeepflow.keep_auth_store import save_auth
from googlekeepflow.keep_setup_google import (
    EMBEDDED_SETUP_URL,
    describe_cookie,
    exchange_token,
    extract_email_from_page,
    find_cookie_in_document_cookie,
    find_oauth_token,
    mask_email,
)
from googlekeepflow.keep_setup_notifications import (
    is_webview2_runtime_error,
    show_message,
    show_notification,
    show_webview2_missing_notice,
)

RESULT_FILE = plugindir / "token_setup_result.json"
LOG_FILE = plugindir / "log_setup.log"
WEBVIEW_USER_DATA = plugindir / ".webview2-setup-profile"
SETUP_ICON_FILE = plugindir / "icons" / "ico" / "setup.ico"
PYTHONNET_RUNTIME_CONFIG_FILE = plugindir / "pythonnet_webview.runtimeconfig.json"
DEBUG_WEBVIEW = False

logger = logging.getLogger("token_setup_webview")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = RotatingFileHandler(LOG_FILE, maxBytes=512 * 1024, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)


def parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def cleanup_path(path):
    try:
        if Path(path).exists():
            shutil.rmtree(path, ignore_errors=True)
    except OSError as exc:
        logger.debug("Failed to remove path %s: %s: %s", path, type(exc).__name__, exc)


def save_result(payload):
    payload = {
        **payload,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    RESULT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved result: success=%s error=%s", payload.get("success"), payload.get("error"))


def create_setup_window(webview):
    return webview.create_window(
        "GoogleKeepFlow Setup",
        EMBEDDED_SETUP_URL,
        width=520,
        height=760,
        text_select=True,
    )


def configure_pythonnet_runtime():
    runtime_config = {
        "runtimeOptions": {
            "tfm": "net6.0",
            "framework": {
                "name": "Microsoft.WindowsDesktop.App",
                "version": "6.0.0",
            },
            "rollForward": "LatestMajor",
        }
    }
    PYTHONNET_RUNTIME_CONFIG_FILE.write_text(
        json.dumps(runtime_config, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    os.environ.setdefault("PYTHONNET_RUNTIME", "coreclr")
    os.environ.setdefault("PYTHONNET_CORECLR_RUNTIME_CONFIG", str(PYTHONNET_RUNTIME_CONFIG_FILE))
    logger.info("Using pythonnet runtime: %s", os.environ.get("PYTHONNET_RUNTIME"))
    logger.info("Using pythonnet runtime config: %s", os.environ.get("PYTHONNET_CORECLR_RUNTIME_CONFIG"))


def cleanup_webview_profile(window):
    try:
        window.clear_cookies()
        logger.info("Cleared setup WebView cookies")
    except Exception as exc:
        logger.debug("Failed to clear WebView cookies: %s: %s", type(exc).__name__, exc)

    try:
        cleanup_path(WEBVIEW_USER_DATA)
        logger.info("Removed setup WebView profile")
    except Exception as exc:
        logger.debug("Failed to remove WebView profile: %s: %s", type(exc).__name__, exc)


def poll_for_cookie(window, email_getter, settings_dir):
    logger.info("Started cookie polling")
    seen_token = None
    last_cookie_report = 0

    while True:
        time.sleep(2)
        email = email_getter()
        try:
            if not email:
                inferred_email = extract_email_from_page(window)
                if inferred_email:
                    email_getter(inferred_email)
                    email = inferred_email
                    logger.info("Captured email from Google sign-in page: %s", mask_email(email))

            cookies = window.get_cookies()
            oauth_token = find_oauth_token(cookies)
            current_url = window.get_current_url()
            if not oauth_token:
                try:
                    document_cookie = window.evaluate_js("document.cookie")
                    oauth_token = find_cookie_in_document_cookie(document_cookie, "oauth_token")
                except Exception as exc:
                    logger.debug("document.cookie read failed: %s: %s", type(exc).__name__, exc)
        except Exception as exc:
            logger.debug("Cookie polling error: %s: %s", type(exc).__name__, exc)
            continue

        now = time.time()
        if DEBUG_WEBVIEW and now - last_cookie_report > 10:
            last_cookie_report = now
            cookie_names = sorted({describe_cookie(cookie) for cookie in (cookies or [])})
            logger.info(
                "Polling url=%s cookies=%s cookie_names=%s",
                current_url,
                len(cookies or []),
                ", ".join(cookie_names[:50]) if cookie_names else "-",
            )

        if current_url and "disallowed_useragent" in current_url:
            save_result({
                "success": False,
                "email": email,
                "error": "Google blocked the embedded browser user agent.",
                "url": current_url,
            })
            show_message(
                "GoogleKeepFlow Setup",
                "Google blocked this embedded browser. See token_setup_result.json.",
                is_error=True,
            )
            window.destroy()
            return

        if not oauth_token or oauth_token == seen_token:
            continue

        seen_token = oauth_token
        logger.info("Found oauth_token cookie")
        if not email:
            save_result({
                "success": False,
                "email": "",
                "error": "Email is required before exchanging oauth_token.",
            })
            show_message(
                "GoogleKeepFlow Setup",
                "Google sign-in worked, but Gmail address is missing.\n\n"
                "Run setup with your Gmail address:\n"
                "keep setup your@gmail.com",
                is_error=True,
            )
            window.destroy()
            return

        try:
            result = exchange_token(email, oauth_token)
            if result.get("success"):
                metadata = save_auth(
                    settings_dir,
                    result["email"],
                    result["master_token"],
                    android_id=result.get("android_id"),
                )
                save_result({
                    "success": True,
                    "email": metadata.get("email"),
                    "android_id": metadata.get("android_id"),
                    "token_last4": metadata.get("token_last4"),
                })
                show_notification("GoogleKeepFlow is ready", "You can use the plugin now.", plugindir, logger)
                cleanup_webview_profile(window)
                window.destroy()
                return

            save_result(result)
            show_message(
                "GoogleKeepFlow Setup",
                f"oauth_token was found, but exchange failed: {result.get('error')}\n\n"
                f"Details saved to:\n{RESULT_FILE}",
                is_error=True,
            )
        except Exception as exc:
            save_result({
                "success": False,
                "email": email,
                "error": f"{type(exc).__name__}: {exc}",
            })
            show_message(
                "GoogleKeepFlow Setup",
                f"oauth_token was found, but setup failed: {exc}\n\n"
                f"Details saved to:\n{RESULT_FILE}",
                is_error=True,
            )


def main():
    global DEBUG_WEBVIEW

    logger.info("Setup helper started with executable: %s", sys.executable)
    default_email = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    settings_dir = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].strip() else plugindir
    DEBUG_WEBVIEW = parse_bool(sys.argv[3]) if len(sys.argv) > 3 else False
    logger.info("Setup WebView debug/devtools enabled: %s", DEBUG_WEBVIEW)
    email_holder = {"email": default_email.lower()}
    if email_holder["email"]:
        logger.info("Using email from command argument: %s", mask_email(email_holder["email"]))
    else:
        logger.info("No email provided; will infer it from Google sign-in page")

    try:
        configure_pythonnet_runtime()
        import webview
        logger.info("Imported pywebview from: %s", getattr(webview, "__file__", "?"))
    except ImportError as exc:
        logger.exception("Failed to import dependencies")
        save_result({
            "success": False,
            "email": email_holder.get("email", ""),
            "error": f"Missing plugin dependency: {type(exc).__name__}: {exc}",
        })
        if not show_notification(
            "GoogleKeepFlow setup failed",
            "Plugin dependencies are missing. Try reinstalling the plugin.",
            plugindir,
            logger,
        ):
            show_message(
                "GoogleKeepFlow Setup",
                "Plugin dependencies are missing.\n\n"
                "Try reinstalling the plugin.",
                is_error=True,
            )
        return 1

    window = create_setup_window(webview)

    def start_polling():
        def email_accessor(value=None):
            if value:
                email_holder["email"] = value
            return email_holder.get("email", "")

        threading.Thread(
            target=poll_for_cookie,
            args=(window, email_accessor, settings_dir),
            daemon=True,
        ).start()

    try:
        logger.info("Starting webview with storage path: %s", WEBVIEW_USER_DATA)
        start_args = {
            "private_mode": False,
            "storage_path": str(WEBVIEW_USER_DATA),
            "debug": DEBUG_WEBVIEW,
        }
        if SETUP_ICON_FILE.exists():
            start_args["icon"] = str(SETUP_ICON_FILE)
        webview.start(start_polling, **start_args)
    except Exception as exc:
        logger.exception("webview.start failed")
        if is_webview2_runtime_error(exc):
            save_result({
                "success": False,
                "email": email_holder.get("email", ""),
                "error": "Microsoft Edge WebView2 Runtime is not installed.",
            })
            show_webview2_missing_notice(plugindir, logger)
            return 1

        save_result({
            "success": False,
            "email": email_holder.get("email", ""),
            "error": f"{type(exc).__name__}: {exc}",
        })
        show_message(
            "GoogleKeepFlow Setup",
            f"Failed to start WebView2/browser window: {exc}\n\n"
            f"Details saved to:\n{LOG_FILE}",
            is_error=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



