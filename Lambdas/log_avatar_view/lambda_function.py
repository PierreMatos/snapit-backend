# Lambda: log_avatar_view.py
import json
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('AvatarViews')

def lambda_handler(event, context):
    try:
        body = event.get("body")
        if isinstance(body, str):
            body = json.loads(body)

        request_id = body.get("requestId")
        language = body.get("language")
        user_agent = body.get("userAgent")
        timezone = body.get("timezone")
        screen_size = body.get("screenSize")
        visit_time = body.get("visitTime")

        if not request_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing requestId"})
            }

        # Increment view count and store metadata
        table.update_item(
            Key={"id": request_id},
            UpdateExpression="""
                ADD #v :incr 
                SET #lang = :lang, 
                    #ua = :ua, 
                    #tz = :tz, 
                    #sc = :sc, 
                    #vt = :vt
            """,
            ExpressionAttributeNames={
                "#v": "views",
                "#lang": "language",
                "#ua": "userAgent",
                "#tz": "timezone",
                "#sc": "screenSize",
                "#vt": "visitTime"
            },
            ExpressionAttributeValues={
                ":incr": 1,
                ":lang": language or "unknown",
                ":ua": user_agent or "unknown",
                ":tz": timezone or "unknown",
                ":sc": screen_size or "unknown",
                ":vt": visit_time or "unknown"
            }
        )

        return {
            "statusCode": 200,
            "body": json.dumps({"message": "View logged."})
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
