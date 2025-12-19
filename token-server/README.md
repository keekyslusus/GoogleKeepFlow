## GoogleKeepFlow master token generator
for sissy bakas who prefer to run it on their own machine instead of using [gkeeptokengenerator.duckdns.org](https://gkeeptokengenerator.duckdns.org/)


## Prerequisites:

- [Docker](https://www.docker.com/get-started)
- Gmail account with [2FA enabled](https://myaccount.google.com/signinoptions/twosv)
- Gmail [App Password](https://myaccount.google.com/apppasswords)

**Note**: You MUST have [2FA](https://myaccount.google.com/signinoptions/twosv) enabled to create app passwords!


## Quick Start Guide:

### 1. Download Files

Download this folder to your computer.

### 2. Start Server

Open **Terminal** in this folder and enter the command:

```bash
docker-compose up -d
```

### 3. Open in Browser

Open your browser and go to:

```
http://localhost:8080
```

### 4. Generate Master Token

1. Enter your Gmail address
2. Enter your [**App Password**](https://myaccount.google.com/apppasswords)
3. Get token
4. Paste your master token & Enter your Gmail in plugin settings


## Stop Server:

When finished generating tokens, stop the server:

```bash
docker-compose down
```

## Delete server:
```bash
docker-compose down -v
docker rmi gkeep-token-server-local
```

## Troubleshooting:

### ❌ Port 8080 already in use:

Another app is using port 8080. Change the port:

1. Open `docker-compose.yml`
2. Change line:
   ```yaml
   - "127.0.0.1:8080:8080"
   ```
   to:
   ```yaml
   - "127.0.0.1:9090:8080"  # or any free port
   ```
3. Access at `http://localhost:9090` instead

### ❌ BadAuthentication:

**Possible causes:**
- Wrong email/password
- App password not created ([need 2FA](https://myaccount.google.com/signinoptions/twosv) first!)
- Using regular Gmail password instead of app password

## How It Works:

1. You enter Gmail + App Password in browser
2. Server calls [**gpsoauth API**](https://github.com/simon-weber/gpsoauth)
3. Google returns master token