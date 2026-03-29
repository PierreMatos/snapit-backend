"""Lambda function: Create (invite) user - POST /api/admin/users"""
import json
import os
import boto3
from botocore.exceptions import ClientError

cognito = boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "eu-central-1"))

COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
DEFAULT_GROUP = os.environ.get("DEFAULT_GROUP", "staff")

ALLOWED_GROUPS = {"admins", "staff", "capture"}

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
}


def get_cors_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body) if isinstance(body, dict) else body,
    }


def handle_options():
    return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}


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
        if not COGNITO_USER_POOL_ID:
            return get_cors_response(500, {"error": "Missing COGNITO_USER_POOL_ID env var"})

        body = {}
        if event.get("body"):
            body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]

        email = (body.get("email") or "").strip().lower()
        group = (body.get("group") or DEFAULT_GROUP).strip().lower()
        given_name = (body.get("givenName") or "").strip()
        family_name = (body.get("familyName") or "").strip()

        if not email:
            return get_cors_response(400, {"error": "Missing email"})
        if group not in ALLOWED_GROUPS:
            return get_cors_response(400, {"error": f"Invalid group. Allowed: {sorted(ALLOWED_GROUPS)}"})

        user_attributes = [
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
        ]
        if given_name:
            user_attributes.append({"Name": "given_name", "Value": given_name})
        if family_name:
            user_attributes.append({"Name": "family_name", "Value": family_name})

        cognito.admin_create_user(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=email,
            UserAttributes=user_attributes,
            DesiredDeliveryMediums=["EMAIL"],
        )

        cognito.admin_add_user_to_group(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=email,
            GroupName=group,
        )

        return get_cors_response(
            200,
            {
                "success": True,
                "message": "User invited successfully",
                "user": {"email": email, "group": group},
            },
        )
    except ClientError as exc:
        message = exc.response.get("Error", {}).get("Message", str(exc))
        code = exc.response.get("Error", {}).get("Code", "")
        status = 409 if code == "UsernameExistsException" else 500
        return get_cors_response(status, {"error": message, "code": code})
    except Exception as exc:
        print(f"Error creating user: {str(exc)}")
        return get_cors_response(500, {"error": f"Failed to create user: {str(exc)}"})
