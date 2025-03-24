import json
import os
import http.client
import boto3
from boto3.dynamodb.conditions import Key
from urllib.parse import urlencode, urlparse
import time

# Constants
LIGHTX_AVATAR_URL = "/external/api/v1/avatar"
LIGHTX_API_KEY = "9243575a15d641da829c5acac13cf1a2_85db21be6e604aa19ed83b94e3ce3798_andoraitools"
LIGHTX_HOST = "api.lightxeditor.com"

# Initialize AWS clients
lambda_client = boto3.client("lambda")
dynamodb = boto3.resource('dynamodb', region_name='eu-central-1')
filter_table = dynamodb.Table('Filters')

def lambda_handler(event, context):
    try:
        # Step 1: Extract parameters from query string
        #query_params = event.get("queryStringParameters", {})
        #image_url = query_params.get("imageUrl")
        image_url = "https://snapit2025.s3.us-east-1.amazonaws.com/user-uploads/17423971108665155319681902336942.jpg"
        filter_id = "braga_male_medieval"



        # Step 2: Fetch filter data from DynamoDB.
        filter_response = filter_table.get_item(Key={"id": filter_id})
        filter_item = filter_response.get("Item")

        if not filter_item:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": f"Filter with ID '{filter_id}' not found."})
            }

        style_image_url = filter_item.get("image_style")
        text_prompt = filter_item.get("prompt")

        if not style_image_url or not text_prompt:
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "Filter data is incomplete."})
            }
            
        conn = http.client.HTTPSConnection("api.lightxeditor.com")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": LIGHTX_API_KEY
        }


        payload = json.dumps({
            "imageUrl": image_url,
            "styleImageUrl": style_image_url,
            "textPrompt": text_prompt
        })
        
        conn.request("POST", LIGHTX_AVATAR_URL, payload, headers)
        res = conn.getresponse()
        response_data = json.loads(res.read().decode("utf-8"))

        # Step 3: Return orderId (check_status will be called separately)
        # Step 3: Return orderId and fetch output
        if "body" in response_data and "orderId" in response_data["body"]:
            order_id = response_data["body"]["orderId"]

            #time.sleep(15)
            try:
                # Prepare Function URL and query params
                # Define o URL da função
                check_url = "https://jjqikmmu3soj2imtggib56d2ie0zfglz.lambda-url.eu-central-1.on.aws/"
                parsed = urlparse(check_url)

                # Prepara os dados da requisição POST
                payload = json.dumps({
                    "orderId": "b8c76281183c4b45988fe6210c353e54"
                })

                # Faz a chamada HTTP POST
                conn = http.client.HTTPSConnection(parsed.hostname)
                conn.request("POST", parsed.path, body=payload, headers={"Content-Type": "application/json"})

                # Lê a resposta
                res = conn.getresponse()
                body = res.read().decode()
                check_data = json.loads(body)

                # Return the final output image URL
                return {
                    "statusCode": 200,
                    "body": json.dumps({
                        "orderId": order_id,
                        "output": check_data.get("output")  # assumes check-order-status returns { "output": "..." }
                    })
                }

            except Exception as e:
                print(f"[CheckOrderStatus Error] {str(e)}")

                return {
                    "statusCode": 200,
                    "body": json.dumps({
                        "orderId": order_id,
                        "output": None,
                        "error": str(e)
                    })
                }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
