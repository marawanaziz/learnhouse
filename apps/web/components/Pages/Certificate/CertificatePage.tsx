'use client';

import React, { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import { useLHSession } from '@components/Contexts/LHSessionContext';
import { useOrg } from '@components/Contexts/OrgContext';
import { getUserCertificates } from '@services/courses/certifications';
import CertificatePreview from '@components/Dashboard/Pages/Course/EditCourseCertification/CertificatePreview';
import { ArrowLeft, Download, Copy, Check } from 'lucide-react';
import Link from 'next/link';
import { getUriWithOrg } from '@services/config/config';
import { useLHAnalytics, useTrackView, AnalyticsEvent } from '@services/analytics';

interface CertificatePageProps {
  orgslug: string;
  courseid: string;
  qrCodeLink: string;
}

// Format an ISO/date string as "Month D, YYYY" (falls back to raw on parse fail)
function fmtDate(raw?: string): string {
  if (!raw) return '';
  const d = new Date(raw);
  if (isNaN(d.getTime())) return raw;
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
}

// Expiration = issue date + bbu_validity_years (0 / missing => no expiration)
function bbuExpiration(userCertificate: any): string {
  const years = Number(userCertificate?.certification?.config?.bbu_validity_years || 0);
  if (!years) return '';
  const d = new Date(userCertificate?.certificate_user?.created_at);
  if (isNaN(d.getTime())) return '';
  d.setFullYear(d.getFullYear() + years);
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
}

const CertificatePage: React.FC<CertificatePageProps> = ({ orgslug, courseid, qrCodeLink }) => {
  const session = useLHSession() as any;
  const org = useOrg() as any;
  const [userCertificate, setUserCertificate] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [linkCopied, setLinkCopied] = useState(false);
  const { track } = useLHAnalytics('learner');

  useTrackView(AnalyticsEvent.CertificateViewed, {}, !!userCertificate);

  // Fetch user certificate
  useEffect(() => {
    const fetchCertificate = async () => {
      if (!session?.data?.tokens?.access_token) {
        setError('Authentication required to view certificate');
        setIsLoading(false);
        return;
      }

      if (!org?.id) {
        return; // Wait for org to be available
      }

      try {
        const cleanCourseId = courseid.replace('course_', '');
        const result = await getUserCertificates(
          `course_${cleanCourseId}`,
          org.id,
          session.data.tokens.access_token
        );

        if (result.success && result.data && result.data.length > 0) {
          setUserCertificate(result.data[0]);
        } else {
          setError('No certificate found for this course');
        }
      } catch (error) {
        console.error('Error fetching certificate:', error);
        setError('Failed to load certificate. Please try again later.');
      } finally {
        setIsLoading(false);
      }
    };

    fetchCertificate();
  }, [courseid, session?.data?.tokens?.access_token, org?.id]);



  // BBU certs: capture the exact on-screen BBU surface (WYSIWYG) → landscape PDF.
  const downloadBBUCertificate = async () => {
    const [{ default: html2canvas }, { default: jsPDF }] = await Promise.all([
      import('html2canvas'), import('jspdf'),
    ]);
    const el = document.getElementById('bbu-certificate-surface');
    if (!el) throw new Error('certificate surface not found');
    const canvas = await html2canvas(el as HTMLElement, {
      scale: 3, useCORS: true, allowTaint: true, backgroundColor: '#ffffff',
    });
    const pdf = new jsPDF('landscape', 'mm', [279.4, 215.9]); // US Letter landscape
    const w = pdf.internal.pageSize.getWidth();
    const h = pdf.internal.pageSize.getHeight();
    pdf.addImage(canvas.toDataURL('image/png'), 'PNG', 0, 0, w, h);
    const nm = (userCertificate.certification.config.certification_name || 'certificate')
      .replace(/[^a-zA-Z0-9]/g, '_');
    pdf.save(`${nm}_Certificate.pdf`);
    track(AnalyticsEvent.CertificateDownloaded, {
      certification_type: userCertificate.certification.config.certification_type,
    });
  };

  // Generate PDF using canvas
  const downloadCertificate = async () => {
    if (!userCertificate) return;

    // BBU-branded certificates render from their own artwork — capture directly.
    if (userCertificate.certification.config.certificate_pattern === 'bbu') {
      try {
        await downloadBBUCertificate();
      } catch (error) {
        console.error('Error generating BBU PDF:', error);
        toast.error('Failed to generate PDF. Please try again.');
      }
      return;
    }

    try {
      const [{ default: html2canvas }, { default: jsPDF }, QRCode] = await Promise.all([
        import('html2canvas'),
        import('jspdf'),
        import('qrcode'),
      ]);
      // Create a temporary div for the certificate
      const certificateDiv = document.createElement('div');
      certificateDiv.style.position = 'absolute';
      certificateDiv.style.left = '-9999px';
      certificateDiv.style.top = '0';
      certificateDiv.style.width = '800px';
      certificateDiv.style.height = '600px';
      certificateDiv.style.background = 'white';
      certificateDiv.style.padding = '40px';
      certificateDiv.style.fontFamily = 'Arial, sans-serif';
      certificateDiv.style.textAlign = 'center';
      certificateDiv.style.display = 'flex';
      certificateDiv.style.flexDirection = 'column';
      certificateDiv.style.justifyContent = 'center';
      certificateDiv.style.alignItems = 'center';
      certificateDiv.style.position = 'relative';
      certificateDiv.style.overflow = 'hidden';

      // Get theme colors based on pattern
      const getPatternTheme = (pattern: string) => {
        switch (pattern) {
          case 'royal':
            return { primary: '#b45309', secondary: '#d97706', icon: '#d97706' };
          case 'tech':
            return { primary: '#0e7490', secondary: '#0891b2', icon: '#0891b2' };
          case 'nature':
            return { primary: '#15803d', secondary: '#16a34a', icon: '#16a34a' };
          case 'geometric':
            return { primary: '#7c3aed', secondary: '#9333ea', icon: '#9333ea' };
          case 'vintage':
            return { primary: '#c2410c', secondary: '#ea580c', icon: '#ea580c' };
          case 'waves':
            return { primary: '#1d4ed8', secondary: '#2563eb', icon: '#2563eb' };
          case 'minimal':
            return { primary: '#374151', secondary: '#4b5563', icon: '#4b5563' };
          case 'professional':
            return { primary: '#334155', secondary: '#475569', icon: '#475569' };
          case 'academic':
            return { primary: '#3730a3', secondary: '#4338ca', icon: '#4338ca' };
          case 'modern':
            return { primary: '#1d4ed8', secondary: '#2563eb', icon: '#2563eb' };
          default:
            return { primary: '#374151', secondary: '#4b5563', icon: '#4b5563' };
        }
      };

      const theme = getPatternTheme(userCertificate.certification.config.certificate_pattern);
      const certificateId = userCertificate.certificate_user.user_certification_uuid;
      const qrCodeData = qrCodeLink ;

      // Generate QR code
      const qrCodeDataUrl = await QRCode.toDataURL(qrCodeData, {
        width: 120,
        margin: 2,
        color: {
          dark: '#000000',
          light: '#FFFFFF'
        },
        errorCorrectionLevel: 'M',
        type: 'image/png'
      });

      // Create certificate content
      certificateDiv.innerHTML = `
        <div style="
          position: absolute;
          top: 20px;
          left: 20px;
          font-size: 12px;
          color: ${theme.secondary};
          font-weight: 500;
        ">ID: ${certificateId}</div>
        
        <div style="
          position: absolute;
          top: 20px;
          right: 20px;
          width: 80px;
          height: 80px;
          border: 2px solid ${theme.secondary};
          border-radius: 8px;
          background: white;
          display: flex;
          align-items: center;
          justify-content: center;
        ">
          <img src="${qrCodeDataUrl}" alt="QR Code" style="width: 100%; height: 100%; object-fit: contain;" />
        </div>
        
        <div style="
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          margin-bottom: 30px;
          font-size: 14px;
          color: ${theme.secondary};
          font-weight: 500;
          text-transform: uppercase;
          letter-spacing: 1px;
        ">
          <div style="width: 24px; height: 1px; background: linear-gradient(90deg, transparent, ${theme.secondary}, transparent);"></div>
          Certificate
          <div style="width: 24px; height: 1px; background: linear-gradient(90deg, transparent, ${theme.secondary}, transparent);"></div>
        </div>
        
        <div style="
          width: 80px;
          height: 80px;
          background: linear-gradient(135deg, ${theme.icon}20 0%, ${theme.icon}40 100%);
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          margin: 0 auto 30px;
          font-size: 40px;
          line-height: 1;
        ">🏆</div>
        
        <div style="
          font-size: 32px;
          font-weight: bold;
          color: ${theme.primary};
          margin-bottom: 20px;
          line-height: 1.2;
          max-width: 600px;
        ">${userCertificate.certification.config.certification_name}</div>
        
        <div style="
          font-size: 18px;
          color: #6b7280;
          margin-bottom: 30px;
          line-height: 1.5;
          max-width: 500px;
        ">${userCertificate.certification.config.certification_description || 'This is to certify that the course has been successfully completed.'}</div>
        
        <div style="
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 4px;
          margin: 20px 0;
        ">
          <div style="width: 8px; height: 1px; background: ${theme.secondary}; opacity: 0.5;"></div>
          <div style="width: 4px; height: 4px; background: ${theme.primary}; border-radius: 50%; opacity: 0.6;"></div>
          <div style="width: 8px; height: 1px; background: ${theme.secondary}; opacity: 0.5;"></div>
        </div>
        
        <div style="
          display: inline-flex;
          align-items: center;
          gap: 8px;
          font-size: 16px;
          color: ${theme.primary};
          background: ${theme.icon}10;
          padding: 12px 24px;
          border-radius: 20px;
          border: 1px solid ${theme.icon}20;
          font-weight: 500;
          margin-bottom: 30px;
          white-space: nowrap;
        ">
          <span style="font-weight: bold; font-size: 18px;">✓</span>
          <span>${userCertificate.certification.config.certification_type === 'completion' ? 'Course Completion' :
            userCertificate.certification.config.certification_type === 'achievement' ? 'Achievement Based' :
            userCertificate.certification.config.certification_type === 'assessment' ? 'Assessment Based' :
            userCertificate.certification.config.certification_type === 'participation' ? 'Participation' :
            userCertificate.certification.config.certification_type === 'mastery' ? 'Skill Mastery' :
            userCertificate.certification.config.certification_type === 'professional' ? 'Professional Development' :
            userCertificate.certification.config.certification_type === 'continuing' ? 'Continuing Education' :
            userCertificate.certification.config.certification_type === 'workshop' ? 'Workshop Attendance' :
            userCertificate.certification.config.certification_type === 'specialization' ? 'Specialization' : 'Course Completion'}</span>
        </div>
        
        <div style="
          margin-top: 30px;
          padding: 24px;
          background: #f8fafc;
          border-radius: 8px;
          border: 1px solid #e2e8f0;
          max-width: 400px;
        ">
          <div style="margin: 8px 0; font-size: 14px; color: #374151;">
            <strong style="color: ${theme.primary};">Certificate ID:</strong> ${certificateId}
          </div>
          <div style="margin: 8px 0; font-size: 14px; color: #374151;">
            <strong style="color: ${theme.primary};">Awarded:</strong> ${new Date(userCertificate.certificate_user.created_at).toLocaleDateString('en-US', {
              year: 'numeric',
              month: 'long',
              day: 'numeric'
            })}
          </div>
          ${userCertificate.certification.config.certificate_instructor ? 
            `<div style="margin: 8px 0; font-size: 14px; color: #374151;">
              <strong style="color: ${theme.primary};">Instructor:</strong> ${userCertificate.certification.config.certificate_instructor}
            </div>` : ''
          }
        </div>
        
        <div style="
          margin-top: 20px;
          font-size: 12px;
          color: #6b7280;
        ">
          This certificate can be verified at ${qrCodeData.replace('https://', '').replace('http://', '')}
        </div>
      `;

      // Add to document temporarily
      document.body.appendChild(certificateDiv);

      // Convert to canvas
      const canvas = await html2canvas(certificateDiv, {
        width: 800,
        height: 600,
        scale: 2, // Higher resolution
        useCORS: true,
        allowTaint: true,
        backgroundColor: '#ffffff'
      });

      // Remove temporary div
      document.body.removeChild(certificateDiv);

      // Create PDF
      const imgData = canvas.toDataURL('image/png');
      const pdf = new jsPDF('landscape', 'mm', 'a4');
      
      // Calculate dimensions to center the certificate
      const pdfWidth = pdf.internal.pageSize.getWidth();
      const pdfHeight = pdf.internal.pageSize.getHeight();
      const imgWidth = 280; // mm
      const imgHeight = 210; // mm
      
      // Center the image
      const x = (pdfWidth - imgWidth) / 2;
      const y = (pdfHeight - imgHeight) / 2;
      
      pdf.addImage(imgData, 'PNG', x, y, imgWidth, imgHeight);
      
      // Save the PDF
      const fileName = `${userCertificate.certification.config.certification_name.replace(/[^a-zA-Z0-9]/g, '_')}_Certificate.pdf`;
      pdf.save(fileName);

      track(AnalyticsEvent.CertificateDownloaded, {
        certification_type: userCertificate.certification.config.certification_type,
      });

    } catch (error) {
      console.error('Error generating PDF:', error);
      toast.error('Failed to generate PDF. Please try again.');
    }
  };

  // Open LinkedIn's "Add to Profile" flow, pre-filled with the certificate details
  const shareToLinkedIn = () => {
    if (!userCertificate) return;

    const config = userCertificate.certification.config;
    const awardedAt = new Date(userCertificate.certificate_user.created_at);

    const params = new URLSearchParams({
      startTask: 'CERTIFICATION_NAME',
      name: config.certification_name,
      organizationName: org?.name || '',
      issueYear: String(awardedAt.getFullYear()),
      issueMonth: String(awardedAt.getMonth() + 1),
      certId: userCertificate.certificate_user.user_certification_uuid,
      certUrl: qrCodeLink,
    });

    window.open(
      `https://www.linkedin.com/profile/add?${params.toString()}`,
      '_blank',
      'noopener,noreferrer'
    );

    track(AnalyticsEvent.CertificateSharedLinkedin, {
      certification_name: config.certification_name,
    });
  };

  // Generic social share to the public verification link (X / Twitter, Facebook)
  const shareToSocial = (network: 'x' | 'facebook') => {
    if (!qrCodeLink) return;
    const certName = userCertificate?.certification?.config?.certification_name || 'my certification';
    const text = `I earned ${certName} from ${org?.name || 'Birth & Baby University'}! 🎉`;
    const url =
      network === 'x'
        ? `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(qrCodeLink)}`
        : `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(qrCodeLink)}&quote=${encodeURIComponent(text)}`;
    window.open(url, '_blank', 'noopener,noreferrer,width=600,height=600');
  };

  // Copy the public certificate verification link to the clipboard
  const copyVerificationLink = async () => {
    if (!qrCodeLink) return;

    try {
      await navigator.clipboard.writeText(qrCodeLink);
      setLinkCopied(true);
      toast.success('Verification link copied to clipboard');
      setTimeout(() => setLinkCopied(false), 2000);
    } catch (error) {
      console.error('Error copying verification link:', error);
      toast.error('Failed to copy link. Please try again.');
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading certificate...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center max-w-md mx-auto p-6">
          <div className="bg-red-50 border border-red-200 rounded-lg p-6">
            <h2 className="text-xl font-semibold text-red-800 mb-2">Certificate Not Available</h2>
            <p className="text-red-600 mb-4">{error}</p>
            <Link
              href={getUriWithOrg(orgslug, '') + `/course/${courseid}`}
              className="inline-flex items-center space-x-2 bg-blue-600 text-white px-6 py-3 rounded-full hover:bg-blue-700 transition duration-200"
            >
              <ArrowLeft className="w-5 h-5" />
              <span>Back to Course</span>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (!userCertificate) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center max-w-md mx-auto p-6">
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6">
            <h2 className="text-xl font-semibold text-yellow-800 mb-2">No Certificate Found</h2>
            <p className="text-yellow-600 mb-4">
              No certificate is available for this course. Please contact your instructor for more information.
            </p>
            <Link
              href={getUriWithOrg(orgslug, '') + `/course/${courseid}`}
              className="inline-flex items-center space-x-2 bg-blue-600 text-white px-6 py-3 rounded-full hover:bg-blue-700 transition duration-200"
            >
              <ArrowLeft className="w-5 h-5" />
              <span>Back to Course</span>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 py-8">
      <div className="max-w-4xl mx-auto px-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <Link
            href={getUriWithOrg(orgslug, '') + `/course/${courseid}`}
            className="inline-flex items-center space-x-2 text-gray-600 hover:text-gray-900 transition duration-200"
          >
            <ArrowLeft className="w-5 h-5" />
            <span>Back to Course</span>
          </Link>
          
          <div className="flex items-center space-x-3">
            <button
              onClick={copyVerificationLink}
              aria-label="Copy certificate verification link"
              className="inline-flex items-center space-x-2 bg-gray-100 text-gray-700 px-5 py-3 rounded-full hover:bg-gray-200 transition duration-200"
            >
              {linkCopied ? <Check className="w-5 h-5" /> : <Copy className="w-5 h-5" />}
              <span>{linkCopied ? 'Copied' : 'Copy link'}</span>
            </button>
            <span className="text-sm text-gray-500 hidden sm:inline">Share:</span>
            <button
              onClick={shareToLinkedIn}
              aria-label="Add this certificate to your LinkedIn profile"
              title="Share on LinkedIn"
              className="inline-flex items-center justify-center w-11 h-11 bg-[#0a66c2] text-white rounded-full hover:bg-[#004182] transition duration-200"
            >
              <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.13 1.44-2.13 2.94v5.67H9.35V9h3.42v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.55V9h3.57v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.72v20.56C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.72V1.72C24 .77 23.2 0 22.22 0z"/></svg>
            </button>
            <button
              onClick={() => shareToSocial('x')}
              aria-label="Share this certificate on X"
              title="Share on X"
              className="inline-flex items-center justify-center w-11 h-11 bg-black text-white rounded-full hover:bg-neutral-800 transition duration-200"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M18.9 1.15h3.68l-8.04 9.19L24 22.85h-7.41l-5.8-7.58-6.64 7.58H.46l8.6-9.83L0 1.15h7.6l5.24 6.93 6.06-6.93zm-1.29 19.5h2.04L6.49 3.24H4.3L17.61 20.65z"/></svg>
            </button>
            <button
              onClick={() => shareToSocial('facebook')}
              aria-label="Share this certificate on Facebook"
              title="Share on Facebook"
              className="inline-flex items-center justify-center w-11 h-11 bg-[#1877f2] text-white rounded-full hover:bg-[#0d5fd4] transition duration-200"
            >
              <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M24 12.07C24 5.4 18.63 0 12 0S0 5.4 0 12.07C0 18.1 4.39 23.1 10.13 24v-8.44H7.08v-3.49h3.05V9.41c0-3.02 1.79-4.69 4.53-4.69 1.31 0 2.68.24 2.68.24v2.97h-1.51c-1.49 0-1.96.93-1.96 1.89v2.25h3.33l-.53 3.49h-2.8V24C19.61 23.1 24 18.1 24 12.07z"/></svg>
            </button>
            <button
              onClick={downloadCertificate}
              aria-label="Download certificate as PDF"
              className="inline-flex items-center space-x-2 bg-green-600 text-white px-6 py-3 rounded-full hover:bg-green-700 transition duration-200"
            >
              <Download className="w-5 h-5" />
              <span>Download PDF</span>
            </button>
          </div>
        </div>

        {/* Certificate Display */}
        <div className="bg-white rounded-2xl shadow-lg p-8">
          <div className="max-w-2xl mx-auto">
            <CertificatePreview
              certificationName={userCertificate.certification.config.certification_name}
              certificationDescription={userCertificate.certification.config.certification_description}
              certificationType={userCertificate.certification.config.certification_type}
              certificatePattern={userCertificate.certification.config.certificate_pattern}
              certificateInstructor={userCertificate.certification.config.certificate_instructor}
              certificateId={userCertificate.certificate_user.user_certification_uuid}
              awardedDate={fmtDate(userCertificate.certificate_user.created_at)}
              qrCodeLink={qrCodeLink}
              bbuTemplate={userCertificate.certification.config.bbu_template}
              bbuLayout={userCertificate.certification.config.bbu_layout}
              recipientName={userCertificate.recipient_name || (session?.data?.user ? `${session.data.user.first_name || ''} ${session.data.user.last_name || ''}`.trim() : '')}
              issueDate={fmtDate(userCertificate.certificate_user.created_at)}
              expirationDate={bbuExpiration(userCertificate)}
              surfaceId="bbu-certificate-surface"
            />
          </div>
        </div>

        {/* Instructions */}
        <div className="mt-8 text-center text-gray-600">
          <p className="mb-2">
            Click "Download PDF" to generate and download a high-quality certificate PDF.
          </p>
          <p className="text-sm">
            The PDF includes a scannable QR code for certificate verification.
          </p>
        </div>
      </div>
    </div>
  );
};

export default CertificatePage; 