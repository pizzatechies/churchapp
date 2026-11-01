"""
Safaricom Daraja: register where M-Pesa should send each Paybill/Till payment.

The church (or its Ecclesia provider) creates an app on https://developer.safaricom.co.ke,
gets it approved for the production Paybill or Till, and sets two settings on the admin
app's server:

    MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET   (and MPESA_ENVIRONMENT=sandbox to test)

Receiving payments needs no keys at all: Safaricom posts each payment to the
confirmation address, which carries a long secret token. The keys are only used for
the one-off "register these addresses" call, which can also be done from the Daraja
portal by hand.
"""

import base64
import json
import urllib.error
import urllib.request

from django.conf import settings


class DarajaError(Exception):
    pass


def configured():
    return bool(settings.MPESA_CONSUMER_KEY and settings.MPESA_CONSUMER_SECRET)


def base_url():
    return "https://sandbox.safaricom.co.ke" if settings.MPESA_ENVIRONMENT == "sandbox" else "https://api.safaricom.co.ke"


def _request(url, data=None, headers=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode() or "{}")
        except ValueError:
            detail = {}
        raise DarajaError(detail.get("errorMessage") or detail.get("ResponseDescription") or f"Safaricom answered {e.code}.")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise DarajaError(f"Couldn't reach Safaricom: {e}")


def access_token():
    if not configured():
        raise DarajaError("MPESA_CONSUMER_KEY and MPESA_CONSUMER_SECRET aren't set on the server.")
    basic = base64.b64encode(f"{settings.MPESA_CONSUMER_KEY}:{settings.MPESA_CONSUMER_SECRET}".encode()).decode()
    data = _request(f"{base_url()}/oauth/v1/generate?grant_type=client_credentials", headers={"Authorization": f"Basic {basic}"})
    token = data.get("access_token")
    if not token:
        raise DarajaError("Safaricom didn't return an access token. Check the consumer key and secret.")
    return token


def register_urls(shortcode, confirmation_url, validation_url):
    for url in (confirmation_url, validation_url):
        lowered = url.lower()
        # Safaricom refuses addresses that mention M-Pesa or Safaricom, and plain http in production.
        if any(word in lowered for word in ("mpesa", "m-pesa", "safaricom")):
            raise DarajaError("The address must not contain the words M-Pesa or Safaricom.")
        if settings.MPESA_ENVIRONMENT != "sandbox" and not lowered.startswith("https://"):
            raise DarajaError("Safaricom needs an https:// address. Open Ecclesia Admin through its https address and try again.")
    data = _request(
        f"{base_url()}/mpesa/c2b/v2/registerurl",
        data={"ShortCode": str(shortcode), "ResponseType": "Completed",
              "ConfirmationURL": confirmation_url, "ValidationURL": validation_url},
        headers={"Authorization": f"Bearer {access_token()}"},
    )
    if str(data.get("ResponseCode", "")) not in {"0", "00000000"} and "success" not in str(data.get("ResponseDescription", "")).lower():
        raise DarajaError(data.get("ResponseDescription") or data.get("errorMessage") or "Safaricom didn't accept the addresses.")
    return data
