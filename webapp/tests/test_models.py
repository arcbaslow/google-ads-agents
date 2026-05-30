from app.models import User, Connection


def test_user_and_connection_roundtrip(session):
    u = User(email="m@example.com")
    session.add(u)
    session.flush()
    assert u.id  # uuid populated

    c = Connection(
        user_id=u.id,
        google_email="m@gmail.com",
        refresh_token=b"\x01\x02",
        token_version=0,
        customer_id="1234567890",
        accessible_customers=["1234567890", "2222222222"],
        scopes="adwords",
    )
    session.add(c)
    session.flush()
    got = session.get(Connection, c.id)
    assert got.user_id == u.id
    assert got.accessible_customers == ["1234567890", "2222222222"]
    assert got.refresh_token == b"\x01\x02"
