from app.crypto import Crypto
from cryptography.fernet import Fernet


def test_round_trip():
    c = Crypto([Fernet.generate_key().decode()])
    ct, ver = c.encrypt("refresh-token-value")
    assert ver == 0
    assert ct != b"refresh-token-value"
    assert c.decrypt(ct, ver) == "refresh-token-value"


def test_rotation_keeps_old_versions_decryptable():
    k0 = Fernet.generate_key().decode()
    c_old = Crypto([k0])
    ct0, ver0 = c_old.encrypt("old-secret")
    assert ver0 == 0

    k1 = Fernet.generate_key().decode()
    c_new = Crypto([k0, k1])           # appended; current is now index 1
    ct1, ver1 = c_new.encrypt("new-secret")
    assert ver1 == 1
    assert c_new.decrypt(ct0, ver0) == "old-secret"   # old version still decrypts
    assert c_new.decrypt(ct1, ver1) == "new-secret"
