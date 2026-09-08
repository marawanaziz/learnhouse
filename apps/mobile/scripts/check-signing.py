"""Check local signing material against the existing store apps; never upload or mutate it."""

import datetime
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TARGETS = json.loads((ROOT / "release/store-targets.json").read_text())


def run(command, *, data=None, env=None):
    try:
        result = subprocess.run(command, input=data, capture_output=True, env=env)
    except FileNotFoundError as error:
        raise ValueError(f"Required signing tool is missing: {command[0]}") from error
    if result.returncode:
        # Tool output may contain credential details. Keep it out of logs.
        raise ValueError(f"{command[0]} could not validate the supplied signing material")
    return result.stdout


def local_file(value):
    if not value:
        raise ValueError("A signing file path is missing in credentials.json")
    path = (ROOT / value).resolve()
    if not path.is_file():
        raise ValueError(f"Signing file not found: {path}")
    return str(path)


def normalize_fingerprint(value):
    result = value.replace(":", "").strip().upper()
    if not re.fullmatch(r"[0-9A-F]{64}", result):
        raise ValueError("Expected a SHA-256 certificate fingerprint")
    return result


def validate_upload_fingerprint(actual, expected):
    if normalize_fingerprint(actual) != normalize_fingerprint(expected):
        raise ValueError("Android key does not match the existing Play upload certificate; do not upload or reset it automatically")


def check_android(credentials):
    store = credentials["android"]["keystore"]
    for field in ["keystorePassword", "keyAlias", "keyPassword"]:
        if not store.get(field) or store[field] == "REPLACE_LOCALLY":
            raise ValueError(f"Android {field} is missing in credentials.json")
    env = {**os.environ, "BBU_CHECK_STORE_PASSWORD": store["keystorePassword"]}
    output = run([
        "keytool", "-J-Duser.language=en", "-list", "-v", "-keystore", local_file(store.get("keystorePath")),
        "-alias", store["keyAlias"], "-storepass:env", "BBU_CHECK_STORE_PASSWORD",
    ], env=env).decode()
    if "PrivateKeyEntry" not in output:
        raise ValueError("The Android keystore entry does not contain a private signing key")
    match = re.search(r"SHA256:\s*([0-9A-Fa-f:]+)", output)
    if not match:
        raise ValueError("Could not read the Android upload certificate fingerprint")
    validate_upload_fingerprint(match.group(1), TARGETS["android"]["uploadCertificateSha256"])
    print("Android: private-key entry and upload certificate match the existing Play app. Key password is also checked by the native build.")


def validate_profile(profile, certificate_der, ios, now):
    if profile.get("ExpirationDate", datetime.datetime.min) <= now:
        raise ValueError("The iOS provisioning profile has expired")
    if profile.get("TeamIdentifier") != [ios["appleTeamId"]]:
        raise ValueError("The iOS provisioning profile belongs to a different Apple team")
    entitlements = profile.get("Entitlements", {})
    expected_id = ios["appleTeamId"] + "." + ios["bundleIdentifier"]
    if entitlements.get("application-identifier") != expected_id:
        raise ValueError("The iOS provisioning profile targets a different app")
    if entitlements.get("com.apple.developer.team-identifier") != ios["appleTeamId"]:
        raise ValueError("The iOS signing entitlement belongs to a different Apple team")
    if entitlements.get("get-task-allow") or profile.get("ProvisionedDevices") is not None or profile.get("ProvisionsAllDevices"):
        raise ValueError("Use an App Store distribution profile, not a development, ad hoc, or enterprise profile")
    if certificate_der not in profile.get("DeveloperCertificates", []):
        raise ValueError("The iOS certificate is not included in this provisioning profile")


def check_ios(credentials):
    ios = credentials["ios"]
    certificate = ios["distributionCertificate"]
    if "password" not in certificate or certificate["password"] == "REPLACE_LOCALLY":
        raise ValueError("The iOS certificate password is missing in credentials.json")
    profile = plistlib.loads(run(["security", "cms", "-D", "-i", local_file(ios.get("provisioningProfilePath"))]))
    env = {**os.environ, "BBU_CHECK_CERT_PASSWORD": certificate["password"]}
    p12 = ["openssl", "pkcs12", "-in", local_file(certificate.get("path")), "-passin", "env:BBU_CHECK_CERT_PASSWORD"]
    cert_pem = run(p12 + ["-clcerts", "-nokeys"], env=env)
    cert_der = run(["openssl", "x509", "-outform", "DER"], data=cert_pem)
    run(["openssl", "x509", "-checkend", "0", "-noout"], data=cert_pem)
    # Decrypt only in process memory and compare public keys; never write or print private key material.
    private_pem = run(p12 + ["-nocerts", "-nodes"], env=env)
    private_public_key = run(["openssl", "pkey", "-pubout"], data=private_pem)
    del private_pem
    certificate_public_key = run(["openssl", "x509", "-pubkey", "-noout"], data=cert_pem)
    if private_public_key != certificate_public_key:
        raise ValueError("The iOS distribution certificate and private key do not match")
    validate_profile(profile, cert_der, TARGETS["ios"], datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
    print("iOS: private key, valid distribution certificate, App Store profile, existing Bundle ID, and Apple team match.")


def main():
    platforms = sys.argv[1:] or ["android", "ios"]
    if any(platform not in ["android", "ios"] for platform in platforms):
        raise ValueError("Usage: python3 scripts/check-signing.py [android|ios]")
    path = ROOT / "credentials.json"
    if not path.is_file():
        raise ValueError("Production signing is not configured. Copy credentials.example.json to credentials.json and supply the existing signing materials locally.")
    credentials = json.loads(path.read_text())
    for platform in platforms:
        (check_android if platform == "android" else check_ios)(credentials)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, plistlib.InvalidFileException) as error:
        print(f"Signing check stopped: {error}", file=sys.stderr)
        sys.exit(1)
