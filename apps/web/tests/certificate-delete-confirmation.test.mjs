import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

const profileSource = readFileSync(
  fileURLToPath(new URL("../components/Dashboard/Pages/Members/MemberProfile.tsx", import.meta.url)),
  "utf8"
);
const serviceSource = readFileSync(
  fileURLToPath(new URL("../services/admin/certificates.ts", import.meta.url)),
  "utf8"
);

describe("admin certificate deletion", () => {
  test("gates deletion behind an explicit, safely focused confirmation dialog", () => {
    assert.match(profileSource, /setCertificatePendingDelete\(certificate\)/);
    assert.match(profileSource, /role="alertdialog"/);
    assert.match(profileSource, /This removes the issued certificate/);
    assert.match(profileSource, /\n\s+Cancel\n\s+<\/button>/);
    assert.match(profileSource, /deletingCertificateUuid \? 'Deleting…' : 'Delete'/);
    assert.match(profileSource, /autoFocus[\s\S]*>\s*Cancel/);
    const destructiveButton = profileSource.slice(profileSource.lastIndexOf('onClick={confirmCertificateDelete}'));
    assert.doesNotMatch(destructiveButton, /autoFocus/);
  });

  test("cancel closes the prompt without invoking the delete service", () => {
    assert.match(profileSource, /onClick=\{\(\) => setCertificatePendingDelete\(null\)\}/);
    assert.match(profileSource, /const confirmCertificateDelete = async \(\) =>/);
    assert.match(profileSource, /if \(!certificate \|\| deletingCertificateUuid\) return/);
    assert.match(profileSource, /await deleteUserCertificate\(orgSlug, userId, uuid, token\)/);
  });

  test("uses one exact organization-scoped DELETE request and refreshes after success", () => {
    assert.match(serviceSource, /RequestBodyWithAuthHeader\('DELETE', null, null, accessToken\)/);
    assert.match(serviceSource, /admin\/\$\{encodeURIComponent\(orgSlug\)\}\/certifications\/\$\{userId\}\/\$\{encodeURIComponent\(userCertificationUuid\)\}/);
    assert.match(profileSource, /setD\(await loadProfile\(\)\)/);
    assert.match(profileSource, /item\.uuid !== uuid/);
  });

  test("keeps failed deletes visible and reports API errors", () => {
    assert.match(profileSource, /setCertificateError\(error\?\.message \|\| 'Could not delete the certificate\. No changes were made\.'/);
    assert.match(profileSource, /role="alert"/);
    assert.match(profileSource, /await deleteUserCertificate[\s\S]*catch \(error: any\)/);
    assert.doesNotMatch(profileSource, /catch \(error: any\)[\s\S]*setD\(\(previous/);
  });
});
