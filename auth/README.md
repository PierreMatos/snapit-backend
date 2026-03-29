# Auth Microservices

## Endpoints

- `POST /api/auth/token-exchange` -> `token-exchange`

## Purpose

Supports OAuth authorization-code exchange for secret-enabled Cognito app clients.
Frontend sends `code`, `redirectUri`, and `codeVerifier` to this endpoint.
Lambda exchanges the code with Cognito `/oauth2/token` using client secret.

## Required environment variables

- `COGNITO_DOMAIN` (e.g. `https://eu-central-1xxxx.auth.eu-central-1.amazoncognito.com`)
- `COGNITO_CLIENT_ID`
- `COGNITO_CLIENT_SECRET`

## API request body

```json
{
  "code": "authorization-code",
  "redirectUri": "https://www.snapitrabbit.com/callback.html",
  "codeVerifier": "pkce-verifier"
}
```
