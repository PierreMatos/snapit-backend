# Dashboard Metrics Lambda

## Function

- Folder: `Lambdas/dashboard/get-metrics`
- Handler: `lambda_function.lambda_handler`
- Runtime: Python 3.14 (or compatible with `zoneinfo`)

## API Gateway route

- `GET /api/dashboard/metrics` -> `get-metrics` Lambda
- Enable Lambda proxy integration
- Add `OPTIONS` support for CORS preflight

## Environment variables

- `AWS_REGION` (default `eu-central-1`)
- `REQUESTS_TABLE_NAME` (default `Requests`)
- `ORDERS_TABLE_NAME` (default `Orders`)

## IAM permissions

Required DynamoDB actions:

- `dynamodb:Scan` on `Requests`
- `dynamodb:Scan` on `Orders`

## Notes

- Metrics are computed for range start `2026-03-30` to now.
- Day boundaries are calculated in `Europe/Lisbon`.
- Response is role-aware:
  - `admins`: full payload (overall + daily + perUser)
  - `staff/capture/promoter`: only current-user top-line metrics.
