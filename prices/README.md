# Prices Microservices

This directory contains Lambda functions for managing per-city package prices.

## Endpoints

- `GET /api/prices/{cityId}` -> `get-prices`
- `PUT /api/prices/{cityId}` -> `upsert-prices`

## DynamoDB table

- Table name: `Prices` (or your `PRICES_TABLE_NAME` env var)
- Partition key: `id` (String)
- Example item:

```json
{
  "id": "1",
  "cityId": "1",
  "price1": 10,
  "price2": 20,
  "price3": 25,
  "price4": 30,
  "currency": "EUR",
  "updatedAt": "2026-03-23T12:00:00+00:00"
}
```

## Environment variables

Set these on both Lambda functions:

- `PRICES_TABLE_NAME` (default `Prices`)
- `AWS_REGION` (default `eu-central-1`)

## API Gateway routes

Configure HTTP API routes:

- `GET /api/prices/{cityId}` -> Lambda `get-prices`
- `PUT /api/prices/{cityId}` -> Lambda `upsert-prices`

Enable Lambda proxy integration.
