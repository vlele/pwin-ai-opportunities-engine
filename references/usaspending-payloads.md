# USAspending Payloads

## Recipient autocomplete

Endpoint:

`POST https://api.usaspending.gov/api/v2/autocomplete/recipient/`

Example body:

```json
{
  "search_text": "Oak Ridge Center for Risk Analysis",
  "limit": 10
}
```

## Spending by award

Endpoint:

`POST https://api.usaspending.gov/api/v2/search/spending_by_award/`

Example contract-award body:

```json
{
  "subawards": false,
  "limit": 25,
  "page": 1,
  "sort": "Award Amount",
  "order": "desc",
  "filters": {
    "recipient_search_text": ["Oak Ridge Center for Risk Analysis"],
    "award_type_codes": ["A", "B", "C", "D"]
  },
  "fields": [
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Start Date",
    "End Date",
    "Award Type",
    "Contract Award Type",
    "Awarding Agency",
    "Awarding Sub Agency"
  ]
}
```

## Rules

- use `POST`, not `GET`
- send JSON
- inspect error bodies
- retry once with a corrected body before reporting failure
