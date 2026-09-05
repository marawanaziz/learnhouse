import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

const courseEndSource = readFileSync(
  fileURLToPath(
    new URL("../components/Pages/Activity/CourseEndView.tsx", import.meta.url)
  ),
  "utf8"
);
const certificatePreviewSource = readFileSync(
  fileURLToPath(
    new URL("../components/Dashboard/Pages/Course/EditCourseCertification/CertificatePreview.tsx", import.meta.url)
  ),
  "utf8"
);

describe("BBU course-end certificate export", () => {
  test("captures only the branded certificate surface", () => {
    assert.match(courseEndSource, /const BBU_COURSE_END_SURFACE_ID = 'bbu-course-end-certificate-surface'/);
    assert.match(courseEndSource, /document\.getElementById\(BBU_COURSE_END_SURFACE_ID\)/);
    assert.match(courseEndSource, /html2canvas\(certificateSurface as HTMLElement/);
    assert.match(
      courseEndSource,
      /certificate_pattern === 'bbu'[\s\S]*await downloadBBUCertificate\(\)[\s\S]*return;/
    );
    assert.doesNotMatch(
      courseEndSource,
      /html2canvas\(\s*document\.getElementById\(['"]certificate-(?:preview|content)['"]\)/
    );
  });

  test("renders the same BBU inputs used by the verified certificate surface", () => {
    assert.match(courseEndSource, /bbuTemplate=\{userCertificate\.certification\.config\.bbu_template\}/);
    assert.match(courseEndSource, /bbuLayout=\{userCertificate\.certification\.config\.bbu_layout\}/);
    assert.match(courseEndSource, /recipientName=\{userCertificate\.recipient_name\}/);
    assert.match(courseEndSource, /issueDate=\{formatCertificateDate\(/);
    assert.match(courseEndSource, /expirationDate=\{bbuExpirationDate\(/);
    assert.match(courseEndSource, /surfaceId=\{BBU_COURSE_END_SURFACE_ID\}/);
  });

  test("reuses the approved Anna Rodney signature on completion certificates", () => {
    assert.match(
      certificatePreviewSource,
      /BBU_INSTRUCTOR_SIGNATURE_TEMPLATE = '\/api\/v1\/bbu\/cert-template\/bbu_cert-01\.png'/
    );
    assert.match(certificatePreviewSource, /data-bbu-instructor-signature="anna-rodney"/);
    assert.match(certificatePreviewSource, /clipPath: 'inset\(77% 31% 17\.7% 51%\)'/);
  });
});
