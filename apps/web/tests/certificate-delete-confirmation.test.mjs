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
const operationsSource = readFileSync(
  fileURLToPath(new URL("../../api/src/bbu_admin/console.py", import.meta.url)),
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
    const trainingDialog = profileSource.slice(
      profileSource.lastIndexOf('{certificatePendingDelete &&'),
      profileSource.indexOf('{credentialPendingDelete &&')
    );
    const destructiveButton = trainingDialog.slice(trainingDialog.lastIndexOf('onClick={confirmCertificateDelete}'));
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

  test("renders professional credential rows with preserved verification actions and a named delete dialog", () => {
    assert.match(profileSource, /d\?\.credential_issuances/);
    assert.match(profileSource, /professionalCredentialLabel\(c\.credential_type\)/);
    assert.match(profileSource, /deleteUserCredentialIssuance\(orgSlug, userId, issuanceId, token\)/);
    assert.match(profileSource, /Delete professional credential\?/);
    assert.match(profileSource, /delete-professional-credential-description/);
    assert.match(profileSource, /Verify <ExternalLink/);
    assert.match(profileSource, /Download PDF <Download/);
    assert.match(profileSource, /onClick=\{\(\) => setCredentialPendingDelete\(null\)\}/);
    assert.match(profileSource, /onClick=\{confirmCredentialDelete\}/);
  });

  test("adds the same guarded action to Operations member training certificates only", () => {
    assert.match(operationsSource, /certificate-delete-trigger/);
    assert.match(operationsSource, /data-certificate-uuid=/);
    assert.match(operationsSource, /requestCertificateDelete\(this\)/);
    assert.match(operationsSource, /Delete issued certificate\?/);
    assert.match(operationsSource, /This removes the issued certificate for/);
    assert.match(operationsSource, /id=certificate-delete-cancel[^>]*>Cancel/);
    assert.match(operationsSource, /id=certificate-delete-confirm[^>]*>Delete/);
    assert.match(operationsSource, /method:'DELETE'/);
    assert.match(operationsSource, /CERTIFICATE_ORG_SLUG='bbu'/);
    assert.match(operationsSource, /openCredentialMember\(pending\.userId\)/);
    assert.match(operationsSource, /closeCertificateDelete\(true\)/);
  });

  test("Operations cancel path closes the dialog without issuing DELETE", () => {
    assert.match(operationsSource, /document\.getElementById\('certificate-delete-cancel'\)\.onclick=closeCertificateDelete/);
    assert.match(operationsSource, /function closeCertificateDelete\(force=false\)/);
    assert.match(operationsSource, /if\(!pending\|\|CERTIFICATE_DELETE_BUSY\)return/);
    assert.match(operationsSource, /error\.textContent=errorValue&&errorValue\.message/);
  });
});
