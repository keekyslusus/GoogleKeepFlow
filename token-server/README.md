## GoogleKeepFlow master token generator

Local token helper for the [GoogleKeepFlow](https://github.com/keekyslusus/GoogleKeepFlow) plugin.

## Prerequisites

- [Docker](https://www.docker.com/get-started)
- A Google account
- Browser access to [Google EmbeddedSetup](https://accounts.google.com/EmbeddedSetup)

## Quick Start Guide

### 1. Download Files

[Download](https://download-directory.github.io/?url=https://github.com/keekyslusus/GoogleKeepFlow/tree/main/token-server) this folder to your computer.

### 2. Start Server

Open **Terminal** in this folder and enter the command:

```bash
docker-compose up -d
```

### 3. Open in Browser

Open your browser and go to:

```text
http://localhost:8080
```

### 4. Generate Master Token

1. Open [Google EmbeddedSetup](https://accounts.google.com/EmbeddedSetup) and sign in.
2. Click **I agree** if prompted; an endless loading page is fine.
3. Copy the `oauth_token` cookie value from browser devtools.
4. Paste it into the token generator and click **Get Token**.
5. Paste the returned `aas_et/...` master token and your Gmail into plugin settings.

In Chrome or Edge, open DevTools, go to **Application** -> **Cookies** -> `https://accounts.google.com`, then copy the `oauth_token` value. In Firefox, use **Storage** -> **Cookies** -> `https://accounts.google.com`.

## Stop Server

When finished generating tokens, stop the server:

```bash
docker-compose down
```

## Delete Server

```bash
docker-compose down -v
docker rmi gkeep-token-server-local
```

## Troubleshooting

### Port 8080 already in use

Another app is using port 8080. Change the port:

1. Open `docker-compose.yml`.
2. Change this line:

```yaml
- "127.0.0.1:8080:8080"
```

to:

```yaml
- "127.0.0.1:9090:8080"
```

3. Access the server at `http://localhost:9090` instead.

### BadAuthentication / UNKNOWN_ERR

Google started rejecting the old App Password based `perform_master_login` flow for many accounts in early 2026. Use the EmbeddedSetup `oauth_token` cookie flow instead.

The value you paste into GoogleKeepFlow settings should be the generated master token and should start with `aas_et/`. Do not paste a token that starts with `g.` or `ya29.` into the plugin settings.

## How It Works

1. You sign in through Google's EmbeddedSetup page.
2. You paste the temporary `oauth_token` cookie into this local server.
3. Server calls `gpsoauth.exchange_token`.
4. Google returns a long-lived master token.
