# Validation Rules

## Digest validation

- digest file exists
- digest-entry map exists
- every stable entry ID in the digest has a mapping row

## Capture validation

- request log exists
- request-specific brief exists
- request-specific evidence exists
- brief contains all required headings
- brief does not contain `{{...}}`
- evidence status matches brief status
- no final answer is only a stub or only a menu
