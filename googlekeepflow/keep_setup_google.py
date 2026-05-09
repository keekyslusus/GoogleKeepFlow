import logging
import secrets
from http.cookies import SimpleCookie


EMBEDDED_SETUP_URL = "https://accounts.google.com/EmbeddedSetup"
log = logging.getLogger("token_setup_webview")


def normalize_email(value):
    value = (value or "").strip().lower()
    if "@" not in value or " " in value:
        return ""
    local, _, domain = value.partition("@")
    if not local or "." not in domain:
        return ""
    return value


def mask_email(email):
    email = normalize_email(email)
    if not email:
        return ""
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        masked_local = local[:1] + "*"
    else:
        masked_local = local[:2] + "***" + local[-1:]
    return f"{masked_local}@{domain}"


def cookie_name(cookie):
    if isinstance(cookie, SimpleCookie):
        return next(iter(cookie.keys()), None)
    if isinstance(cookie, dict):
        return cookie.get("name") or cookie.get("Name")
    return getattr(cookie, "name", None) or getattr(cookie, "Name", None)


def cookie_value(cookie):
    if isinstance(cookie, SimpleCookie):
        name = cookie_name(cookie)
        return cookie[name].value if name else None
    if isinstance(cookie, dict):
        return cookie.get("value") or cookie.get("Value")
    value = getattr(cookie, "value", None) or getattr(cookie, "Value", None)
    if value:
        return value

    output = getattr(cookie, "output", None)
    if callable(output):
        text = output()
        marker = "oauth_token="
        if marker in text:
            return text.split(marker, 1)[1].split(";", 1)[0].strip()
    return None


def find_oauth_token(cookies):
    for cookie in cookies or []:
        if cookie_name(cookie) == "oauth_token":
            return cookie_value(cookie)
    return None


def describe_cookie(cookie):
    if isinstance(cookie, SimpleCookie):
        name = cookie_name(cookie) or ""
        morsel = cookie[name] if name else None
        domain = morsel["domain"] if morsel else ""
        return f"{domain}:{name}"

    if isinstance(cookie, dict):
        domain = cookie.get("domain") or cookie.get("Domain") or ""
        name = cookie.get("name") or cookie.get("Name") or ""
        return f"{domain}:{name}"

    domain = getattr(cookie, "domain", None) or getattr(cookie, "Domain", None) or ""
    name = cookie_name(cookie) or ""
    return f"{domain}:{name}"


def find_cookie_in_document_cookie(document_cookie, name):
    marker = f"{name}="
    for part in (document_cookie or "").split(";"):
        item = part.strip()
        if item.startswith(marker):
            return item[len(marker):]
    return None


def extract_email_from_page(window):
    script = r"""
(() => {
  const candidates = [];
  const push = (value) => {
    if (value && typeof value === 'string') candidates.push(value.trim().toLowerCase());
  };

  for (const input of document.querySelectorAll('input')) {
    push(input.value);
    push(input.getAttribute('value'));
    push(input.getAttribute('data-initial-value'));
    push(input.getAttribute('aria-label'));
  }

  for (const node of document.querySelectorAll('[data-email], [data-identifier], [email]')) {
    push(node.getAttribute('data-email'));
    push(node.getAttribute('data-identifier'));
    push(node.getAttribute('email'));
    push(node.textContent);
  }

  push(document.body ? document.body.innerText : '');
  const joined = candidates.join('\n');
  const matches = joined.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/ig) || [];
  return matches.length ? matches[0].toLowerCase() : '';
})()
"""
    try:
        return normalize_email(window.evaluate_js(script))
    except Exception as exc:
        log.debug("Email sniff failed: %s: %s", type(exc).__name__, exc)
        return ""


def exchange_token(email, oauth_token):
    log.info("Exchanging oauth_token for %s", mask_email(email))
    import gpsoauth

    if not hasattr(gpsoauth, "exchange_token"):
        raise RuntimeError("Installed gpsoauth does not support exchange_token")

    android_id = secrets.token_hex(8)
    result = gpsoauth.exchange_token(email, oauth_token, android_id)
    if "Token" in result:
        return {
            "success": True,
            "email": email,
            "android_id": android_id,
            "master_token": result["Token"],
        }

    return {
        "success": False,
        "email": email,
        "android_id": android_id,
        "error": result.get("Error", "Unknown error"),
        "raw": result,
    }

