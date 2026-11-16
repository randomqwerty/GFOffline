"""Account SDK (MTSDKApi) endpoints, normally https://gf-passport.sunborngame.com/passport/*.

Requests are JSON POSTs (MTSDKBaseApi.Http.PostJson, header v: 3). Responses are JSON
objects; HttpRequestHelper treats a top-level "errorReport" {"error_msg": ...} as failure
and passes anything else to the caller.

Login itself is bypassed by client_patch/offline_login.lua; the SDK only has to
initialise (passport/steamGetConfigs), which happens at launch before Lua loads.
"""
import json
import logging

log = logging.getLogger("gfserver.passport")


def steam_get_configs(body):
    # Fields read by ConfigsHelper$$AnalysisAndSaveConfigsJson; each is checked with
    # ContainsKey, so only switches that matter offline are sent (all off).
    return {
        "notice_switch": "0",
        "real_switch": "0",
        "anti_addiction_switch": "0",
    }


def user_protocol(body):
    # Agreement/privacy text the SDK may show; nothing to agree to offline.
    return {}


ROUTES = {
    "passport/steamGetConfigs": steam_get_configs,
    "passport/userProtocol": user_protocol,
}


def handle(path, raw_body):
    function = path.strip("/")
    try:
        body = json.loads(raw_body) if raw_body else {}
    except ValueError:
        body = raw_body
    fn = ROUTES.get(function)
    if fn is None:
        log.warning("UNHANDLED passport %s body=%s", function, json.dumps(body, ensure_ascii=False)[:300])
        return {}
    log.info("passport %s", function)
    return fn(body)
