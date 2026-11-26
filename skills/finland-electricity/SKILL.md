---
name: finland-electricity
description: Plan household electricity use in Finland with real prices (spot price + VAT + margin + transfer fee + tax). Use when the user asks what electricity costs now, today or tomorrow, or when to run the sauna, EV charging, laundry, dishwasher, dryer or water heater cheaply. Also for Finnish terms like pörssisähkö, sähkön hinta, siirtomaksu, halvin aika.
---

# Finnish household electricity

Answer with real numbers from the `finland-energy` MCP tools, never from memory or guesses:

| Tool | Use for |
|---|---|
| `get_price_now` | "What does electricity cost now?", "Is it cheap right now?" |
| `get_prices` | Today's or tomorrow's prices, cheapest and dearest times |
| `find_cheapest_time` | When to run a job of a given length, and what it costs |

## 1. If the tools are missing

Don't look prices up elsewhere. Tell the user how to add the server (needs
[uv](https://docs.astral.sh/uv/)):

```sh
claude mcp add finland-energy -s user -- uvx finland-energy-mcp
```

Other assistants: a local (stdio) MCP server with command `uvx` and argument `finland-energy-mcp`.

## 2. The user's contract: ask once, then reuse

Two numbers differ per household. Both are c/kWh including VAT:

- **Margin** (*marginaali*): from the electricity retailer's contract or invoice.
- **Transfer fee** (*siirtomaksu*, the energy part of *sähkönsiirto*): from the network company's
  invoice (for example Caruna, Elenia or the local grid company).

Monthly fees (*perusmaksu*, €/month) don't depend on timing, so leave them out.

- If the user hasn't given these, answer anyway with the defaults, say they are example values,
  and offer once to recalculate with theirs.
- Once given, pass `margin_c_per_kwh` and `transfer_c_per_kwh` in **every** later call.
- **Night or seasonal transfer** (*yösiirto*, *kausisiirto*): the tools take one transfer fee.
  Use the rate that applies during the planned time and say so.
- **Fixed-price contract** (*kiinteä hinta*): timing doesn't change what they pay (except a
  night-transfer discount). Say so instead of planning around spot prices.

## 3. Turn everyday jobs into tool inputs

`duration_minutes` must be a multiple of 15. Prefer the user's own figures; otherwise use these
typical values and say they are estimates. Energy (kWh) = power (kW) × hours.

| Job | `duration_minutes` | `energy_kwh` | Notes |
|---|---|---|---|
| Sauna, electric 6–9 kW heater | 120 | 8–12 | About 1 h to heat plus bathing. Ask when they want to bathe and set `finish_by` |
| EV charging | energy ÷ charger kW, rounded up | km × 0.18 + 10 % | Chargers: 11 kW (3-phase), 3.7 kW (16 A), 2.3 kW (wall socket) |
| Washing machine, 40–60 °C | 120 | 0.5–1.2 | |
| Dishwasher, eco | 180 | 0.8–1.2 | |
| Tumble dryer, heat pump | 150 | 1.5–2 | |
| Water heater, 300 L, 3 kW | 240–300 | 12–15 | Often already on a night relay; ask first |

- Times without an offset are Finnish time: "before 7 tomorrow" → `finish_by` = tomorrow 07:00.
- The tool assumes even power over the whole window. For appliances that heat mostly at the start,
  the cost is approximate.

## 4. Limits: say them, don't work around them

- Prices exist for **today**, and for **tomorrow after about 14:00** Finnish time.
- For a job ending tomorrow before 14:00, plan within the known prices, or suggest asking again
  after 14:00.
- Past days and later dates are not available. Say so; don't estimate them.

## 5. How to answer

- Lead with the answer: the time window, average c/kWh and cost in €, then the saving compared
  with starting now (`if_started_now`).
- c/kWh including VAT, Finnish time in 24-hour format (22:00–24:00).
- Mention briefly whether margin and transfer fee are the user's or example values.
- Use hourly prices for overviews; 15-minute prices only when asked.
- Reply in the user's language (Finnish or English).
- These are estimates, not financial advice. Never suggest remote-starting a sauna heater unless the
  user says it is approved for remote start.

## Example

> **User:** When should I heat the sauna tonight? We want to bathe before 22.
>
> **You:** call `find_cheapest_time` with `duration_minutes=120`, `earliest_start=today 17:00`,
> `finish_by=today 22:00`, `energy_kwh=10`, plus the user's margin and transfer fee if known.
>
> **Answer:** "Cheapest is 20:00–22:00: about 14.2 c/kWh, roughly €1.42 for 10 kWh. Starting now
> would cost €1.95. (Margin and transfer fee are example values; tell me yours and I'll
> recalculate.)"
