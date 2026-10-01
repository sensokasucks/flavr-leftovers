from core.market import CooldownGate, MarketTape


def test_cooldown_zero_always_allows():
    g = CooldownGate()
    assert g.try_acquire("death|FACT", 0) is True
    assert g.try_acquire("death|FACT", 0) is True
    assert g.try_acquire("death|FACT", None) is True


def test_cooldown_blocks_same_key():
    g = CooldownGate()
    assert g.try_acquire("death|FACT", 30) is True
    assert g.try_acquire("death|FACT", 30) is False
    assert g.remaining("death|FACT", 30) > 0
    assert g.try_acquire("death|STEVE", 30) is True


def test_signal_scope_and_death_dip():
    tape = MarketTape({})
    first = tape.try_signal(name="player_death", symbol="FACTORIO", cooldown_sec=20, scope="symbol")
    assert first["ok"] is True
    again = tape.try_signal(name="player_death", symbol="FACTORIO", cooldown_sec=20, scope="symbol")
    assert again["blocked"] is True
    other = tape.try_signal(name="player_death", symbol="MINECRAF", cooldown_sec=20, scope="symbol")
    assert other["ok"] is True
    before = tape.snapshot(symbols=["FACTORIO"])["instruments"][0]["price"]
    tape.apply_return("FACTORIO", -0.08, reason="player_death")
    after = tape.snapshot(symbols=["FACTORIO"])["instruments"][0]["price"]
    assert after < before
    hist = tape.history("FACTORIO", points=10)
    assert hist["points"]


def test_add_ticker_with_steam_appid(tmp_path):
    path = tmp_path / "listings.json"
    tape = MarketTape({}, listings_path=path)
    tape.upsert(
        symbol="ER",
        name="Elden Ring",
        book="core",
        price=10,
        steam_appid=1245620,
        feed="steam",
        persist=True,
    )
    assert tape.quote("ER")["steam_appid"] == 1245620
    tape.apply_steam_ccu(1245620, 80000)
    assert tape.quote("ER")["steam_baseline"] == 80000
    tape.apply_steam_ccu(1245620, 160000)
    assert tape.quote("ER")["steam_factor"] > 1
    saved = MarketTape({}, listings_path=path)
    assert saved.quote("ER")["steam_appid"] == 1245620
