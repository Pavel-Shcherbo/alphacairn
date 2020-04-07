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


