"""Lambda function: OAuth token exchange - POST /api/auth/token-exchange"""
import base64
import json
import os
import urllib.parse
import urllib.request
import urllib.error

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

COGNITO_DOMAIN = os.environ.get("COGNITO_DOMAIN", "").rstrip("/")
COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "")
COGNITO_CLIENT_SECRET = os.environ.get("COGNITO_CLIENT_SECRET", "")


def get_cors_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body) if isinstance(body, dict) else body,
    }


def handle_options():
    return {
        "statusCode": 204,
        "headers": CORS_HEADERS,
        "body": "",
    }


def lambda_handler(event, context):
    try:
        method = (
            (event.get("requestContext") or {})
            .get("http", {})
            .get("method", "")
            .upper()
        )
        if method == "OPTIONS":
            return handle_options()
        if method != "POST":
            return get_cors_response(405, {"error": "Method not allowed"})

        if not COGNITO_DOMAIN or not COGNITO_CLIENT_ID or not COGNITO_CLIENT_SECRET:
            return get_cors_response(500, {"error": "Missing Cognito env vars"})

        body = {}
        if event.get("body"):
            body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]

        code = (body.get("code") or "").strip()
        redirect_uri = (body.get("redirectUri") or "").strip()
        code_verifier = (body.get("codeVerifier") or "").strip()

        if not code or not redirect_uri or not code_verifier:
            return get_cors_response(
                400,
                {"error": "Missing required fields: code, redirectUri, codeVerifier"},
            )

        token_url = f"{COGNITO_DOMAIN}/oauth2/token"
        form_payload = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "client_id": COGNITO_CLIENT_ID,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            }
        ).encode("utf-8")

        basic = base64.b64encode(
            f"{COGNITO_CLIENT_ID}:{COGNITO_CLIENT_SECRET}".encode("utf-8")
        ).decode("utf-8")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic}",
        }

        request = urllib.request.Request(token_url, data=form_payload, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8")
                token_data = json.loads(raw)
                return get_cors_response(200, token_data)
        except urllib.error.HTTPError as http_err:
            err_body = http_err.read().decode("utf-8") if http_err.fp else ""
            try:
                parsed = json.loads(err_body) if err_body else {}
            except Exception:
                parsed = {"raw": err_body}
            return get_cors_response(http_err.code or 500, parsed or {"error": "Token exchange failed"})

    except Exception as exc:
        print(f"Error in token exchange: {str(exc)}")
        return get_cors_response(500, {"error": f"Token exchange failed: {str(exc)}"})
