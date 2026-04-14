# Filters CRUD Lambda

Standalone Lambda for filter management (city_0 workflow), created without changing existing code.

## Handler

- `lambda_function.lambda_handler`

## Expected API routes

- `GET /api/filters?city_id=0` -> list filters (filtered when `city_id` is provided)
- `POST /api/filters` -> create filter
- `GET /api/filters/{id}` -> get single filter
- `PUT /api/filters/{id}` -> update filter fields
- `PUT /api/filters/{id}/cover-image` -> update `cover_image`

## Environment variables

- `AWS_REGION` (default `eu-central-1`)
- `FILTERS_TABLE_NAME` (default `Filters`)

## Field defaults enforced on create/update

- `city_id = 0`
- `tool = "single-avatar-generation"`
- `tool_url = "https://fz7v4pd43xjhvwe3xfvqpbk3le0ozggd.lambda-url.eu-central-1.on.aws/"`
- `id` generated from title on create (slug format)

## Notes

- This Lambda returns CORS headers for browser calls.
- `cover_image` updates also mirror into `imageUrl` for compatibility with existing UI patterns.
