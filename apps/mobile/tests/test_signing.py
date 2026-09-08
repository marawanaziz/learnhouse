import copy
import datetime
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("check_signing", Path(__file__).parents[1] / "scripts/check-signing.py")
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)


class SigningValidation(unittest.TestCase):
    def setUp(self):
        self.now = datetime.datetime(2026, 9, 8)
        self.ios = signing.TARGETS["ios"]
        self.cert = b"test-public-certificate"
        self.profile = {
            "ExpirationDate": datetime.datetime(2027, 1, 1),
            "TeamIdentifier": [self.ios["appleTeamId"]],
            "Entitlements": {
                "application-identifier": self.ios["appleTeamId"] + "." + self.ios["bundleIdentifier"],
                "com.apple.developer.team-identifier": self.ios["appleTeamId"],
                "get-task-allow": False,
            },
            "DeveloperCertificates": [self.cert],
        }

    def test_existing_app_profile_passes(self):
        signing.validate_profile(self.profile, self.cert, self.ios, self.now)

    def test_wrong_app_team_expired_profile_and_wrong_certificate_fail(self):
        invalid_profiles = [
            {"ExpirationDate": datetime.datetime(2025, 1, 1)},
            {"TeamIdentifier": ["OTHERTEAM12"]},
            {"DeveloperCertificates": [b"different-certificate"]},
        ]
        for invalid in invalid_profiles:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                signing.validate_profile({**self.profile, **invalid}, self.cert, self.ios, self.now)
        profile = copy.deepcopy(self.profile)
        profile["Entitlements"]["application-identifier"] = "2V6MAB58ZP.com.wrong.app"
        with self.assertRaises(ValueError):
            signing.validate_profile(profile, self.cert, self.ios, self.now)

    def test_non_store_profiles_fail(self):
        for change in [{"ProvisionedDevices": []}, {"ProvisionedDevices": ["device"]}, {"ProvisionsAllDevices": True}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                signing.validate_profile({**self.profile, **change}, self.cert, self.ios, self.now)
        profile = copy.deepcopy(self.profile)
        profile["Entitlements"]["get-task-allow"] = True
        with self.assertRaises(ValueError):
            signing.validate_profile(profile, self.cert, self.ios, self.now)

    def test_upload_certificate_must_match_play_not_debug_or_app_signing_key(self):
        expected = signing.TARGETS["android"]["uploadCertificateSha256"]
        signing.validate_upload_fingerprint(expected.lower().replace(":", ""), expected)
        for wrong in ["00" * 32, "invalid", signing.TARGETS["android"]["appSigningCertificateSha256"]]:
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                signing.validate_upload_fingerprint(wrong, expected)


if __name__ == "__main__":
    unittest.main()
