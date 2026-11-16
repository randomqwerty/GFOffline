"""Import recorded game responses from a packet log as canned replies.

  python tools/import_packet_log.py <packet.log> [--force]

The log is JSON objects back to back ({"timestamp","ID","URL","Request","Response"}, with
decrypted Request/Response), as written by the gf_alarm packet logger.

For every game endpoint (/<Module>/<action>) with a JSON response, the most complete
(largest) response is anonymized and written to data/responses/<Module>/<action>.json,
where the server serves it for calls that have no dedicated handler.

Anonymization:
  - the recording player's uid in user_id / uid / f_userid fields -> placeholder
    (data/responses are personalized with the requesting account's uid when served)
  - Friend/dormInfo.in_mydorm_list (other players visiting the dorm) -> []
  - Index/home.index_getmaillist (the account's mailbox, may hold gift codes) -> []
Every file is then checked for the recording account's uid, sign, openid and sid; a file
that still contains any of them is not written. Identifying values are never printed.

Skipped: endpoints with dedicated handlers (Index/version, Index/getUid*, Index/index),
root-path calls (heartbeat, banners), and responses that were not recorded.
Existing files are kept unless --force.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "responses"
PLACEHOLDER_UID = 100000
UID_KEYS = {"user_id", "uid", "f_userid"}
SKIP = re.compile(r"^/Index/(version|getUid\w*|index)$")
CLEAR = {"/Friend/dormInfo": ["in_mydorm_list"], "/Index/home": ["index_getmaillist"]}


def read_log(path):
    raw = Path(path).read_bytes().decode("utf-8", "replace")
    dec, i, out = json.JSONDecoder(), 0, []
    while i < len(raw):
        while i < len(raw) and raw[i] in " \r\n\t":
            i += 1
        if i >= len(raw):
            break
        obj, i = dec.raw_decode(raw, i)
        out.append(obj)
    return out


def recording_identity(entries):
    """uid/sign from the recorded login response, openid/sid from its request."""
    ident = {}
    for e in entries:
        r = e.get("Response")
        if isinstance(r, dict) and "uid" in r and "sign" in r:
            ident.update(uid=str(r["uid"]), sign=str(r["sign"]))
        req = e.get("Request")
        if isinstance(req, str) and "getUid" in e.get("URL", ""):
            for k in ("openid", "sid"):
                m = re.search(k + r"=([^&]+)", req)
                if m:
                    ident[k] = m.group(1)
    if "uid" not in ident:
        raise SystemExit("no recorded login response in the log; cannot tell which uid to remove")
    return ident


def anonymize(url, resp, uid):
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in UID_KEYS and str(v) == uid:
                    o[k] = PLACEHOLDER_UID if isinstance(v, int) else str(PLACEHOLDER_UID)
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(resp)
    for key in CLEAR.get(url, []):
        if isinstance(resp, dict) and key in resp:
            resp[key] = []
    return resp


def leaked(resp, ident):
    found = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if str(k) == ident["uid"]:
                    found.append("uid(key)")
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
        else:
            s = str(o)
            for name, val in ident.items():
                if val and (s == val or (len(val) > 6 and val in s)):
                    found.append(name)
    walk(resp)
    return sorted(set(found))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    entries = read_log(args[0])
    ident = recording_identity(entries)

    best = {}
    for e in entries:
        url, resp = e.get("URL", ""), e.get("Response")
        if not url.startswith("/") or SKIP.match(url) or not isinstance(resp, (dict, list)):
            continue
        size = len(json.dumps(resp, ensure_ascii=False))
        if url not in best or size > best[url][0]:
            best[url] = (size, resp)

    written = kept = refused = 0
    for url, (size, resp) in sorted(best.items()):
        target = OUT.joinpath(*url.strip("/").split("/")).with_suffix(".json")
        if target.exists() and not force:
            print(f"  keep     {url} (exists; --force to replace)")
            kept += 1
            continue
        resp = anonymize(url, resp, ident["uid"])
        bad = leaked(resp, ident)
        if bad:
            print(f"  REFUSED  {url}: still contains {', '.join(bad)}")
            refused += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(resp, ensure_ascii=False, separators=(",", ":")), "utf-8")
        print(f"  wrote    {url} ({len(target.read_bytes())} bytes)")
        written += 1
    print(f"{len(entries)} log entries; {written} written, {kept} kept, {refused} refused")


if __name__ == "__main__":
    main()
