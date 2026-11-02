"""
Safaricom Daraja: tell M-Pesa where to send each Paybill/Till payment, and test it.

Receiving payments needs no keys: Safaricom posts each payment to the church's
confirmation address, which carries a long secret token. Keys are only needed for the
one-off "register these addresses" call (and, in the sandbox, to simulate a payment).

Each church uses the consumer key and secret of its own Daraja app, typed in on the
link page and used for that one call only; Ecclesia never stores them. A platform-wide
MPESA_CONSUMER_KEY / MPESA_CONSUMER_SECRET in the environment is used when the form
is left blank.
"""

import base64
import json
import urllib.error
import urllib.request

from django.conf import settings

SANDBOX = "sandbox"
SANDBOX_TEST_PHONE = "254708374149"  # Safaricom's published sandbox test number


class DarajaError(Exception):
    pass


def configured():
    return bool(settings.MPESA_CONSUMER_KEY and settings.MPESA_CONSUMER_SECRET)


def base_url(environment=None):
    environment = environment or settings.MPESA_ENVIRONMENT
    return "https://sandbox.safaricom.co.ke" if environment == SANDBOX else "https://api.safaricom.co.ke"


def _request(url, data=None, headers=None, timeout=25):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode() or "{}"
            try:
                return json.loads(text)
            except ValueError:
                return {"raw": text[:300]}
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode() or "{}")
        except ValueError:
            detail = {}
        err = DarajaError(detail.get("errorMessage") or detail.get("ResponseDescription") or detail.get("ResultDesc")
                          or f"Safaricom answered {e.code}.")
        err.status = e.code
        raise err
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise DarajaError(f"Couldn't reach Safaricom: {getattr(e, 'reason', e)}")


def _credentials(key, secret):
    key = (key or "").strip() or settings.MPESA_CONSUMER_KEY
    secret = (secret or "").strip() or settings.MPESA_CONSUMER_SECRET
    if not key or not secret:
        raise DarajaError("Enter the consumer key and consumer secret of your Daraja app.")
    return key, secret


def access_token(key=None, secret=None, environment=None):
    key, secret = _credentials(key, secret)
    basic = base64.b64encode(f"{key}:{secret}".encode()).decode()
    try:
        data = _request(f"{base_url(environment)}/oauth/v1/generate?grant_type=client_credentials",
                        headers={"Authorization": f"Basic {basic}"})
    except DarajaError as e:
        if getattr(e, "status", None) in (400, 401):
            raise DarajaError("Safaricom didn't accept the consumer key and secret. Check them, and that they're for the "
                              f"{'sandbox' if environment == SANDBOX else 'live (production)'} environment.")
        raise
    token = data.get("access_token")
    if not token:
        raise DarajaError("Safaricom didn't return an access token. Check the consumer key and secret.")
    return token


def check_addresses(confirmation_url, validation_url, environment=None):
    for url in (confirmation_url, validation_url):
        lowered = url.lower()
        # Safaricom refuses addresses that mention M-Pesa or Safaricom, and plain http in production.
        if any(word in lowered for word in ("mpesa", "m-pesa", "safaricom")):
            raise DarajaError("The address must not contain the words M-Pesa or Safaricom.")
        if (environment or settings.MPESA_ENVIRONMENT) != SANDBOX and not lowered.startswith("https://"):
            raise DarajaError("Safaricom needs an https:// address. Open Ecclesia Admin through its https address and try again.")
        if "localhost" in lowered or "127.0.0.1" in lowered:
            raise DarajaError("Safaricom can't reach a localhost address. Use the server's public address.")


def register_urls(shortcode, confirmation_url, validation_url, key=None, secret=None, environment=None):
    check_addresses(confirmation_url, validation_url, environment)
    token = access_token(key, secret, environment)
    payload = {"ShortCode": str(shortcode), "ResponseType": "Completed",
               "ConfirmationURL": confirmation_url, "ValidationURL": validation_url}
    data = None
    last_error = None
    # Newer apps use v2 (masked phone numbers); older ones only have v1.
    for version in ("v2", "v1"):
        try:
            data = _request(f"{base_url(environment)}/mpesa/c2b/{version}/registerurl", data=payload,
                            headers={"Authorization": f"Bearer {token}"})
            break
        except DarajaError as e:
            last_error = e
            if getattr(e, "status", None) != 404:
                break
    if data is None:
        raise last_error
    description = str(data.get("ResponseDescription", "") or data.get("ResultDesc", ""))
    if str(data.get("ResponseCode", "")) in {"0", "00000000"} or "success" in description.lower():
        return data
    if "already registered" in description.lower():
        return data  # the addresses are in place; Safaricom only lets them change via its support in production
    raise DarajaError(description or data.get("errorMessage") or "Safaricom didn't accept the addresses.")


def simulate_payment(shortcode, amount, account_reference, key=None, secret=None):
    """Sandbox only: ask Safaricom to make a test payment, which it then sends to the confirmation address."""
    token = access_token(key, secret, SANDBOX)
    data = _request(
        f"{base_url(SANDBOX)}/mpesa/c2b/v1/simulate",
        data={"ShortCode": str(shortcode), "CommandID": "CustomerPayBillOnline", "Amount": int(amount),
              "Msisdn": SANDBOX_TEST_PHONE, "BillRefNumber": account_reference or "TEST"},
        headers={"Authorization": f"Bearer {token}"},
    )
    description = str(data.get("ResponseDescription", ""))
    if str(data.get("ResponseCode", "")) not in {"0", "00000000"} and "accept" not in description.lower():
        raise DarajaError(description or "Safaricom didn't accept the test payment.")
    return data


TEST_TRANSACTION_TYPE = "Ecclesia connection test"


def self_check(confirmation_url):
    """Call our own confirmation address over the internet, the way Safaricom will, with a test notice."""
    try:
        data = _request(confirmation_url, data={"TransactionType": TEST_TRANSACTION_TYPE, "TransID": "ECCLESIA-TEST"}, timeout=40)
    except DarajaError as e:
        status = getattr(e, "status", None)
        if status:
            raise DarajaError(f"The payment address answered with error {status}. Check the server's ALLOWED_HOSTS setting.")
        raise DarajaError(f"The payment address couldn't be reached from the internet: {e}".replace("Couldn't reach Safaricom: ", ""))
    if str(data.get("ResultCode")) != "0":
        raise DarajaError(f"The payment address answered, but not as expected: {data}")
    return True
