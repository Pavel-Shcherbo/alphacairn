def account_spec():
    return {
        "name": "synthetic-research",
        "base_currency": "USD",
        "currencies": {"USD": 2, "EUR": 2},
        "instruments": [
            {
                "id": "equity:demo-us",
                "symbol": "DEMO",
                "venue": "SYNTHETIC-US",
                "kind": "equity",
                "quote_currency": "USD",
                "quantity_step": "1",
                "price_tick": "0.01",
            },
            {
                "id": "equity:demo-eu",
                "symbol": "DEMO",
                "venue": "SYNTHETIC-EU",
                "kind": "equity",
                "quote_currency": "EUR",
                "quantity_step": "1",
                "price_tick": "0.01",
            },
            {
                "id": "crypto:demo",
                "symbol": "DEMO-USD",
                "venue": "SYNTHETIC-SPOT",
                "kind": "crypto_spot",
                "quote_currency": "USD",
                "quantity_step": "0.00000001",
                "price_tick": "0.01",
            },
        ],
    }


def event(name, kind, **values):
    return {"id": name, "timestamp": "2026-01-02T12:00:00Z", "kind": kind, **values}


def trade(name, side, quantity, price, fee="0", instrument="equity:demo-us"):
    return event(
        name,
        "trade",
        instrument=instrument,
        side=side,
        quantity=quantity,
        price=price,
        fee=fee,
    )


def scenario_events():
    return [
        event("fund", "deposit", currency="USD", amount="10000"),
        trade("buy-first", "buy", "10", "100", "2"),
        trade("buy-second", "buy", "5", "120", "1"),
        trade("sell-partial", "sell", "12", "150", "3"),
        event(
            "split", "split", instrument="equity:demo-us", numerator=2, denominator=1
        ),
        event(
            "dividend",
            "dividend",
            instrument="equity:demo-us",
            gross="12",
            withholding="3",
        ),
        event(
            "exchange",
            "fx",
            from_currency="USD",
            to_currency="EUR",
            amount="1000",
            rate="0.9",
            fee="1",
        ),
        trade("buy-europe", "buy", "10", "50", "1", instrument="equity:demo-eu"),
        trade("buy-crypto", "buy", "0.1", "20000", "2", instrument="crypto:demo"),
    ]
