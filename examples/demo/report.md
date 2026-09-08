# Google Ads audit — customer 1234567890

Window: 2026-08-01 to 2026-08-28

## Summary

- **gads-conversions**: Synthetic demo: review duplicate purchase conversion actions.
- **gads-search**: Synthetic demo: 12 search terms selected for review.
- **gads-pacing**: Synthetic demo: projected spend is 108% of the monthly budget.
- **gads-placements**: Synthetic demo: 3 placements matched the configured review rules.

## Findings

### high

- [gads-conversions] Two purchase actions are primary. Verify whether the same order is counted twice before changing bidding goals.

### medium

- [gads-search] Review the 12 irrelevant search terms before applying campaign negatives.
- [gads-pacing] Check the remaining monthly budget before adjusting daily limits.

### low

- [gads-placements] Inspect the flagged placements and confirm exclusions individually.
