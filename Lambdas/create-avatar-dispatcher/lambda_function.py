import boto3
import http.client
import json
from urllib.parse import urlparse, urlencode
from boto3.dynamodb.conditions import Attr
from concurrent.futures import ThreadPoolExecutor

dynamodb = boto3.resource('dynamodb', region_name='eu-central-1')
filter_table = dynamodb.Table('Filters')

def lambda_handler(event, context):
    results = []

    # Parse JSON body from POST
    body = json.loads(event.get("body", "{}"))
    image_url = body.get("imageUrl")
    gender = body.get("gender")
    city_id = body.get("city_id")
    #return json.dumps({"imageUrl": image_url, "gender": gender, "city_id": city_id})
    #image_url = "https://snapit2025.s3.us-east-1.amazonaws.com/user-uploads/17423971108665155319681902336942.jpg"
    #gender = "male"
    #city_id = "1"

   # Fetch filters from DB
    response = filter_table.scan(
        FilterExpression=Attr('city_id').eq(city_id)
    )
    filters = response.get("Items", [])

    def call_tool_url(filter_item):
        try:
            tool_url = filter_item["tool_url"]
            parsed = urlparse(tool_url)

            # Build GET query string
            params =  json.dumps({
                "imageUrl": image_url,
                "gender": gender,
                "city_id": city_id,
                "filterId": filter_item["id"]
            })
            
            #query = urlencode(params)
            #full_path = f"{parsed.path}?{query}"

            conn = http.client.HTTPSConnection(parsed.hostname)
            conn.request("POST", parsed.path, body=params, headers={"Content-Type": "application/json"})

            res = conn.getresponse()
            raw_body = res.read().decode()

            # ✅ Parse the inner "body" string from the tool_url Lambda
            outer_response = json.loads(raw_body)
            if "body" in outer_response:
                parsed_body = json.loads(outer_response["body"])  # this is the actual response from create-single-avatar
            else:
                parsed_body = outer_response

            return {
                "filterId": filter_item["id"],
                "output": parsed_body  # contains "orderId" and "output"
            }

        except Exception as e:
            return {
                "filterId": filter_item["id"],
                "output": None,
                "error": str(e)
            }

    # Process all filters in parallel
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(call_tool_url, f) for f in filters]
        for future in futures:
            result = future.result()
            results.append(result)

    # ✅ Final response must json.dumps the body
    return {
        "statusCode": 200,
        "body": json.dumps({
            "outputs": results,
            "filters": [f["id"] for f in filters]
        })
    }