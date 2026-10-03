from app.crypto import decrypt, encrypt


def test_roundtrip() -> None:
    token = encrypt('{"access_token":"shpat_xyz"}')
    assert token != "shpat_xyz"
    assert decrypt(token) == '{"access_token":"shpat_xyz"}'
