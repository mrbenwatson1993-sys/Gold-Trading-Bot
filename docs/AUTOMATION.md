# Alerts and automation

The strategy emits a JSON payload on every entry and exit, so it can drive a broker
bridge instead of you clicking.

## Setting the alert up

1. Add the strategy to a **1-minute** chart and configure it.
2. Click the **alarm clock** → **Create Alert**.
3. **Condition**: the strategy name.
4. **Trigger**: `alert() function calls only`.
5. **Message**: leave it as `{{strategy.order.alert_message}}` — or empty; the bot
   builds the whole payload itself.
6. Add your **Webhook URL** under Notifications.

TradingView alerts expire (a few weeks to a few months depending on plan). Put a
reminder in your calendar to re-arm them, because a silently dead alert looks exactly
like a quiet market.

## Payload

```json
{
  "strategy": "P50_MORNING",
  "action":   "entry",
  "side":     "long",
  "symbol":   "XAUUSD",
  "qty":      0.33,
  "price":    2412.55,
  "sl":       2409.10,
  "tp":       2426.35,
  "rr":       4,
  "time":     "2026-09-10 13:42:00"
}
```

| Field | Notes |
|---|---|
| `action` | `entry` or `exit` |
| `side` | `long` / `short` |
| `symbol` | Chart ticker, or whatever you put in *Symbol override* — set this when your broker's symbol differs from TradingView's |
| `qty` | Already rounded to your configured size step |
| `price` | Actual fill price for an entry |
| `sl` / `tp` | Absolute prices. `null` on exits |
| `rr` | Target R on an entry; **realised R** on an exit |

Log the `rr` field on exits. It is the only number the method actually cares about.

## Before you wire it to real money

The stop and target are enforced **by the strategy on bar close**, not by a resting
order at your broker. If your bridge only forwards entries, a dropped webhook leaves an
unprotected position open.

Make the bridge place the **stop and target as real broker orders** from the `sl` and
`tp` fields at entry time, and treat the exit webhook as a reconciliation signal rather
than the primary exit. Then a lost message costs you a suboptimal exit instead of an
uncapped loss.

Other things to handle on your side, none of which TradingView does for you:

- **Duplicate delivery.** Webhooks can arrive twice. Deduplicate on `time` + `action`.
- **Rejected orders.** Insufficient margin, symbol closed, size below broker minimum.
  The bot has no idea the order failed and will keep managing a position that does not
  exist.
- **Symbol and size mapping.** TradingView's `qty` is in the chart symbol's units. Your
  broker may want lots, contracts, or notional.
- **Reconciliation.** Compare broker positions against the strategy's expected state on
  a schedule, and alert yourself on any mismatch.

Run it on a demo account until the fills, the sizes and the R log all match what the
backtest said they would.
