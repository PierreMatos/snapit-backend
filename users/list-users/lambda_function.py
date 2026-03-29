"""Lambda function: List users - GET /api/admin/users"""
import json
import os
import boto3
from botocore.exceptions import ClientError

cognito = boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "eu-central-1"))

COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")

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


def attr_value(user, key):
    attrs = user.get("Attributes", [])
    for attr in attrs:
        if attr.get("Name") == key:
            return attr.get("Value", "")
    return ""


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
        if method != "GET":
            return get_cors_response(405, {"error": "Method not allowed"})
        if not COGNITO_USER_POOL_ID:
            return get_cors_response(500, {"error": "Missing COGNITO_USER_POOL_ID env var"})

        list_response = cognito.list_users(UserPoolId=COGNITO_USER_POOL_ID, Limit=60)
        users = []
        for user in list_response.get("Users", []):
            username = user.get("Username", "")
            groups_response = cognito.admin_list_groups_for_user(
                UserPoolId=COGNITO_USER_POOL_ID,
                Username=username,
            )
            groups = [group.get("GroupName", "") for group in groups_response.get("Groups", [])]
            users.append(
                {
                    "username": username,
                    "email": attr_value(user, "email"),
                    "status": user.get("UserStatus", ""),
                    "enabled": bool(user.get("Enabled", False)),
                    "createdAt": str(user.get("UserCreateDate", "")),
                    "groups": groups,
                }
            )

        return get_cors_response(200, {"users": users})
    except ClientError as exc:
        message = exc.response.get("Error", {}).get("Message", str(exc))
        code = exc.response.get("Error", {}).get("Code", "")
        return get_cors_response(500, {"error": message, "code": code})
    except Exception as exc:
        print(f"Error listing users: {str(exc)}")
        return get_cors_response(500, {"error": f"Failed to list users: {str(exc)}"})
