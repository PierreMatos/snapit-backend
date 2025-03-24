import boto3
import http.client
import json
from urllib.parse import urlparse, urlencode
from boto3.dynamodb.conditions import Attr
from concurrent.futures import ThreadPoolExecutor

lambda_client = boto3.client("lambda")
dynamodb = boto3.resource('dynamodb', region_name='eu-central-1')
filter_table = dynamodb.Table('Filters')

def invoke_lambda(payload, function_name):
    return lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",  # ou 'Event' se não quiseres esperar
        Payload=json.dumps(payload)
    )

def lambda_handler(event, context):
    # Buscar filtros
    response = filter_table.scan(
        FilterExpression=Attr('gender').eq("male") & Attr('city_id').eq("1")
    )

    filters = response.get("Items", [])

    city_id = 1
    image_url = "https://snapit2025.s3.us-east-1.amazonaws.com/user-uploads/17423971108665155319681902336942.jpg"
    gender = "male"
    results = []

    # 🧠 Função auxiliar para chamada HTTP ao tool_url
    def call_tool_url(filter_item):
        try:
            tool_url = filter_item["tool_url"]
            parsed = urlparse(tool_url)

            params = {
                "imageUrl": image_url,
                "gender": gender,
                "city_id": city_id,
                "filterId": filter_item["id"]
            }
            query = urlencode(params)
            full_path = f"{parsed.path}?{query}"

            conn = http.client.HTTPSConnection(parsed.hostname)
            conn.request("GET", full_path, headers={"Content-Type": "application/json"})

            response = conn.getresponse()
            body = response.read().decode()
            res_json = json.loads(body)

            return res_json.get("orderIds", [res_json.get("orderId")])

        except Exception as e:
            print(f"[Erro] Filtro {filter_item['id']}: {str(e)}")
            return []

    # Chamada concorrente às tool_url
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(call_tool_url, f) for f in filters]
        for future in futures:
            result = future.result()
            if result:
                results.extend(result)

    return {
        "statusCode": 200,
        "body": json.dumps({
            "orderIds": results,
            "filters": [f["id"] for f in filters]
        })
    }
