import os
import time
import hashlib
import secrets
import logging
import re
from datetime import datetime, timedelta
from functools import wraps
from collections import defaultdict

from flask import Flask, request, jsonify, render_template

import gpsoauth

# ANTI-SPAM
MAX_REQUESTS_PER_IP_PER_HOUR = 5
MAX_REQUESTS_PER_IP_PER_DAY = 10
MAX_GLOBAL_REQUESTS_PER_HOUR = 30
MAX_GLOBAL_REQUESTS_PER_DAY = 200
CHALLENGE_DIFFICULTY = 5
CHALLENGE_TTL = 300  # 5 mins
FAILED_ATTEMPTS_BLOCK_THRESHOLD = 10  # Block IP after N failed attempts
BLOCK_DURATION = 3600  # 60 mins

# WALLET AND BALLS PROTECTION
ABSOLUTE_DAILY_LIMIT = 500
ABSOLUTE_MONTHLY_LIMIT = 5000

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

# STATE
ip_requests = defaultdict(list)
ip_failed_attempts = defaultdict(int)  # track failed auth attempts
global_requests = []
monthly_requests = []
blocked_ips = {}  # IP -> unblock_timestamp
challenges = {}
used_challenges = set()

# VALIDATION
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
APP_PASSWORD_REGEX = re.compile(r'^[a-z]{16}$')  # Google app passwords are 16 lowercase letters


def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
        if re.match(r'^(\d{1,3}\.){3}\d{1,3}$', ip) or ':' in ip:
            return ip
    return request.remote_addr


def cleanup_old_requests():
    now = time.time()
    hour_ago = now - 3600
    day_ago = now - 86400
    month_ago = now - 86400 * 30

    for ip in list(ip_requests.keys()):
        ip_requests[ip] = [t for t in ip_requests[ip] if t > day_ago]
        if not ip_requests[ip]:
            del ip_requests[ip]

    for ip in list(ip_failed_attempts.keys()):
        if ip not in ip_requests or not ip_requests[ip]:
            del ip_failed_attempts[ip]

    for ip in list(blocked_ips.keys()):
        if blocked_ips[ip] < now:
            del blocked_ips[ip]
            log.info(f"Unblocked IP: {ip}")

    global global_requests, monthly_requests
    global_requests = [t for t in global_requests if t > day_ago]
    monthly_requests = [t for t in monthly_requests if t > month_ago]

    for token in list(challenges.keys()):
        if challenges[token][1] < now - CHALLENGE_TTL:
            del challenges[token]

    # TODO: redis with TTL?


def check_rate_limit(ip):
    cleanup_old_requests()

    if ip in blocked_ips:
        remaining = int(blocked_ips[ip] - time.time())
        return False, f"IP temporarily blocked. Try again in {remaining // 60} minutes"

    now = time.time()
    hour_ago = now - 3600
    day_ago = now - 86400

    # ABSOLUTE LIMITS
    if len(monthly_requests) >= ABSOLUTE_MONTHLY_LIMIT:
        log.critical("MONTHLY LIMIT REACHED - SERVICE SUSPENDED")
        return False, "Service temporarily unavailable (monthly limit)"

    if len(global_requests) >= ABSOLUTE_DAILY_LIMIT:
        log.critical("DAILY LIMIT REACHED - SERVICE SUSPENDED")
        return False, "Service temporarily unavailable (daily limit)"

    # per IP limits
    ip_times = ip_requests[ip]
    requests_last_hour = len([t for t in ip_times if t > hour_ago])
    requests_last_day = len([t for t in ip_times if t > day_ago])

    if requests_last_hour >= MAX_REQUESTS_PER_IP_PER_HOUR:
        return False, f"Rate limit: max {MAX_REQUESTS_PER_IP_PER_HOUR} requests/hour"

    if requests_last_day >= MAX_REQUESTS_PER_IP_PER_DAY:
        return False, f"Rate limit: max {MAX_REQUESTS_PER_IP_PER_DAY} requests/day"

    global_last_hour = len([t for t in global_requests if t > hour_ago])

    if global_last_hour >= MAX_GLOBAL_REQUESTS_PER_HOUR:
        return False, "Server busy, try again later"

    if len(global_requests) >= MAX_GLOBAL_REQUESTS_PER_DAY:
        return False, "Daily limit reached, try again tomorrow"

    return True, "OK"


def record_request(ip):
    now = time.time()
    ip_requests[ip].append(now)
    global_requests.append(now)
    monthly_requests.append(now)


def record_failed_attempt(ip):
    ip_failed_attempts[ip] += 1
    if ip_failed_attempts[ip] >= FAILED_ATTEMPTS_BLOCK_THRESHOLD:
        blocked_ips[ip] = time.time() + BLOCK_DURATION
        log.warning(f"Blocked IP {ip} for {BLOCK_DURATION}s due to {ip_failed_attempts[ip]} failed attempts")
        ip_failed_attempts[ip] = 0


def generate_challenge():
    token = secrets.token_hex(32)
    challenge = secrets.token_hex(32)
    challenges[token] = (challenge, time.time())
    return token, challenge


def verify_challenge(token, nonce):
    if token in used_challenges:
        return False, "Challenge already used"

    if token not in challenges:
        return False, "Invalid or expired challenge"

    challenge, timestamp = challenges[token]

    if time.time() - timestamp > CHALLENGE_TTL:
        del challenges[token]
        return False, "Challenge expired"

    # verify pow
    data = f"{challenge}{nonce}"
    hash_result = hashlib.sha256(data.encode()).hexdigest()

    if hash_result.startswith('0' * CHALLENGE_DIFFICULTY):
        del challenges[token]
        used_challenges.add(token)  # mark as used
        return True, "Valid"

    return False, "Invalid solution"


def validate_email(email):
    if not email or len(email) > 254:
        return False
    return EMAIL_REGEX.match(email) is not None


def validate_app_password(password):
    if not password:
        return False
    clean = password.replace(' ', '').lower()
    return len(clean) == 16 and clean.isalpha()

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'timestamp': int(time.time())})


@app.route('/api/challenge', methods=['GET'])
def get_challenge():
    ip = get_client_ip()

    allowed, message = check_rate_limit(ip)
    if not allowed:
        log.warning(f"Rate limit hit for {ip}: {message}")
        return jsonify({'success': False, 'error': message}), 429

    token, challenge = generate_challenge()
    log.info(f"Challenge issued to {ip}")

    return jsonify({
        'success': True,
        'token': token,
        'challenge': challenge,
        'difficulty': CHALLENGE_DIFFICULTY
    })


@app.route('/api/token', methods=['POST'])
def get_token():
    ip = get_client_ip()

    allowed, message = check_rate_limit(ip)
    if not allowed:
        log.warning(f"Rate limit hit for {ip}: {message}")
        return jsonify({'success': False, 'error': message}), 429

    if not request.is_json:
        return jsonify({'success': False, 'error': 'Invalid content type'}), 400

    data = request.json
    if not data:
        return jsonify({'success': False, 'error': 'Invalid request'}), 400

    email = str(data.get('email', '')).strip().lower()
    password = str(data.get('password', '')).replace(' ', '')
    challenge_token = str(data.get('challenge_token', ''))
    nonce = str(data.get('nonce', ''))

    if not validate_email(email):
        return jsonify({'success': False, 'error': 'Invalid email format'}), 400

    if not validate_app_password(password):
        return jsonify({'success': False, 'error': 'Invalid app password format. Should be 16 letters without spaces.'}), 400

    valid, msg = verify_challenge(challenge_token, nonce)
    if not valid:
        log.warning(f"Invalid challenge from {ip}: {msg}")
        return jsonify({'success': False, 'error': msg}), 400

    record_request(ip)

    try:
        log.info(f"Token request from {ip} for {email[:3]}***@{email.split('@')[1] if '@' in email else '?'}")

        res = gpsoauth.perform_master_login(email, password, "")

        if 'Token' in res:
            log.info(f"Token generated successfully for {ip}")
            # reset failed attempts on success
            ip_failed_attempts[ip] = 0
            return jsonify({
                'success': True,
                'master_token': res['Token']
            })
        elif res.get('Error') == 'NeedsBrowser':
            record_failed_attempt(ip)
            return jsonify({
                'success': False,
                'error': 'Google requires browser verification. Try creating a new App Password.'
            })
        elif res.get('Error') == 'BadAuthentication':
            record_failed_attempt(ip)
            return jsonify({
                'success': False,
                'error': 'Invalid credentials. Make sure 2FA is enabled and you\'re using a valid App Password.'
            })
        else:
            error = res.get('Error', 'Unknown error')
            record_failed_attempt(ip)
            log.warning(f"Token generation failed for {ip}: {error}")
            return jsonify({
                'success': False,
                'error': f"Authentication failed: {error}"
            })

    except Exception as e:
        log.error(f"Exception for {ip}: {type(e).__name__}: {e}")
        return jsonify({
            'success': False,
            'error': 'Server error. Please try again later.'
        }), 500


@app.route('/stats', methods=['GET'])
def stats():
    client_ip = get_client_ip()
    if client_ip not in ['127.0.0.1', 'localhost', '::1']:
        return jsonify({'error': 'Forbidden'}), 403

    cleanup_old_requests()
    now = time.time()
    hour_ago = now - 3600

    return jsonify({
        'requests_last_hour': len([t for t in global_requests if t > hour_ago]),
        'requests_last_day': len(global_requests),
        'requests_this_month': len(monthly_requests),
        'unique_ips_today': len(ip_requests),
        'blocked_ips': len(blocked_ips),
        'active_challenges': len(challenges),
        'limits': {
            'daily_remaining': ABSOLUTE_DAILY_LIMIT - len(global_requests),
            'monthly_remaining': ABSOLUTE_MONTHLY_LIMIT - len(monthly_requests)
        }
    })

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500


@app.errorhandler(429)
def rate_limited(e):
    return jsonify({'error': 'Too many requests'}), 429


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    log.info(f"Starting server on port {port}")
    log.info(f"Daily limit: {ABSOLUTE_DAILY_LIMIT}, Monthly limit: {ABSOLUTE_MONTHLY_LIMIT}")
    app.run(host='0.0.0.0', port=port, threaded=True)