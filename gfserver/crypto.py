"""GF1 request/response cipher (client class AC.AuthCode).

A Discuz-authcode variant: RC4 keyed from MD5(sign), no random key prefix,
and the two derived keys swapped relative to stock Discuz. Verified against
GameAssembly.dll (AC.AuthCode$$Authcode @ RVA 0x38B7340).
"""
import base64
import gzip
import hashlib
import time

EXPIRY = 3600


def md5(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.md5(data).hexdigest()


def _rc4(data, key):
    box = list(range(256))
    k = key.encode("utf-8")
    j = 0
    for i in range(256):
        j = (j + box[i] + k[i % len(k)]) % 256
        box[i], box[j] = box[j], box[i]
    out = bytearray(len(data))
    i = j = 0
    for n, b in enumerate(data):
        i = (i + 1) % 256
        j = (j + box[i]) % 256
        box[i], box[j] = box[j], box[i]
        out[n] = b ^ box[(box[i] + box[j]) % 256]
    return bytes(out)


def _keys(sign):
    k = md5(sign)
    key_a = md5(k[16:32])
    key_b = md5(k[0:16])
    return key_a + md5(key_a), key_b


def _b64decode(s):
    s = s.strip()
    return base64.b64decode(s + "=" * (-len(s) % 4))


def _stamp(now, expiry):
    return "0000000000" if expiry == 0 else str(int(now) + expiry)


def encode(text, sign, expiry=EXPIRY, now=None):
    """Encrypt a UTF-8 string (client->server outdatacode, or a plain response)."""
    crypt_key, key_b = _keys(sign)
    now = time.time() if now is None else now
    body = _stamp(now, expiry) + md5(text + key_b)[:16] + text
    return base64.b64encode(_rc4(body.encode("utf-8"), crypt_key)).decode("ascii")


def decode(blob, sign, now=None, check_expiry=True):
    """Decrypt an encode() payload. Returns None when the checksum or expiry fails."""
    crypt_key, key_b = _keys(sign)
    try:
        plain = _rc4(_b64decode(blob), crypt_key).decode("utf-8", "surrogateescape")
        stamp, chk, text = int(plain[:10]), plain[10:26], plain[26:]
    except ValueError:
        return None
    now = time.time() if now is None else now
    if check_expiry and stamp != 0 and stamp - int(now) <= 0:
        return None
    if chk != md5(text.encode("utf-8", "surrogateescape") + key_b.encode())[:16]:
        return None
    return text


def encode_gzip(payload, sign, expiry=EXPIRY, now=None):
    """Build a '#'-prefixed response the client unpacks with DecodeWithGzip + GZip."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    crypt_key, key_b = _keys(sign)
    gz = gzip.compress(payload)
    now = time.time() if now is None else now
    head = (_stamp(now, expiry) + md5(gz + key_b.encode())[:16]).encode("ascii")
    return "#" + base64.b64encode(_rc4(head + gz, crypt_key)).decode("ascii")


def decode_gzip(blob, sign, now=None, check_expiry=True):
    """Inverse of encode_gzip (accepts with or without the leading '#')."""
    crypt_key, key_b = _keys(sign)
    try:
        raw = _rc4(_b64decode(blob.lstrip("#")), crypt_key)
        stamp, chk, gz = int(raw[:10]), raw[10:26].decode("ascii"), raw[26:]
    except ValueError:
        return None
    now = time.time() if now is None else now
    if check_expiry and stamp != 0 and stamp - int(now) <= 0:
        return None
    if chk != md5(gz + key_b.encode())[:16]:
        return None
    return gzip.decompress(gz).decode("utf-8")
