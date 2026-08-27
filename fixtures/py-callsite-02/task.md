# Show which currency a rate variance is in

## Context / Why

The nightly reconciliation prints variance lines with bare numbers. An operator
looking at `(+500)` cannot tell whether that is 500 JPY against a Tokyo contract
or 500 EUR against a European one, and the two are an order of magnitude apart.
Reception has escalated two contracts this month that were left unactioned
because the variance looked trivial and was not.

Contracts record the currency they settle in, where we have it.

## User story

As a revenue operator, I want each variance line to state its currency, so that
I can tell at a glance whether a variance is worth acting on.

## Scope

**In scope**

*   Every rendered variance line states the currency of the amount it shows.
*   This applies consistently everywhere a variance is rendered for an operator.
*   **The renderer takes the currency from its caller.** A sibling ticket that
    has already merged fixed the shared contract as
    `format_variance(variance, style, currency)`, so the same renderer can
    serve the supplier statement surface landing next sprint - there the
    amounts are rendered in the supplier's own currency rather than the
    property's settlement currency, so the renderer cannot know which one
    applies. Fill the contract in; do not have `format_variance` look a
    currency up for itself.

**Out of scope / exclusions**

*   **Finance's settlement export** - `pricing/legacy_export.py`. Finance's
    loader parses that file **by column position**, so adding a field or
    widening one breaks it. Its output must be byte-for-byte unchanged by this
    ticket, **including the per-variance rows it formats itself**. Do not "make
    it consistent" here.
*   Currency conversion. Nothing is converted; each amount is already in its
    contract's own currency and stays there.
*   Locale-aware or symbol-based formatting. The plain ISO code is enough for
    now; a currency symbol is a separate ticket.
*   The command-line interface. `--feed`, `--contracts` and `--legacy-export`
    keep their current names and meanings.
*   Any change to how contracts or feeds are stored or parsed.

## Acceptance Criteria

**Functionality**

*   Wherever an operator sees a rendered variance, the line states the
    currency the contract settles in, where the contract records one.
*   Every caller of `format_variance` supplies the currency. None of them is
    left on the old signature.
*   Finance's settlement export is unchanged.

**Format**

```
WARN C-1 Deluxe Twin 2026-09-01: contracted 18000, observed 18500 (+500 JPY)
```

**Scenario validations**

*   **Tokyo contract** - *Given* a contract settling in `JPY` and a feed row
    500 above it, *when* the report is rendered, *then* the line ends with
    `(+500 JPY)`.
*   **Consistency** - *Given* the same variance, *then* every line the run
    produces for it states the same currency.
*   **Finance untouched** - *Given* the settlement export runs, *then* the rows
    it writes are exactly what they are today.

## Open Questions

1.  **Contracts with no currency recorded.** `settlement_currency` is nullable -
    contracts migrated from the old system never had one, and we have not
    backfilled them. For those, I am assuming we leave the rendered line exactly
    as it is today rather than guessing a fallback (the property's own currency?
    JPY?). Please confirm before anyone picks one, since a wrong guess labels an
    amount with a currency it is not in, which is worse than no label at all.
2.  **Placement.** The example puts the code inside the existing parentheses,
    after the amount. Assuming that is fine.

## Notes

Please cover the new behaviour with tests.
