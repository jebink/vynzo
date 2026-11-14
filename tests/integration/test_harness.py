def test_baseline_migrations_apply(fresh_db, migrate):
    import psycopg

    applied = migrate(fresh_db, until="20261108000005")
    assert len(applied) == 5
    with psycopg.connect(fresh_db) as conn:
        assert conn.execute("select to_regclass('public.ohlcv_1d')").fetchone()[0] is not None


def test_after_and_until_select_a_slice(fresh_db, migrate):
    assert migrate(fresh_db, until="20261108000002") == ["20261108000001", "20261108000002"]
    assert migrate(fresh_db, after="20261108000002", until="20261108000003") == ["20261108000003"]
