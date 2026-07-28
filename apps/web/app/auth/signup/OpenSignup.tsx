'use client'
import { useFormik } from 'formik'
import { useRouter } from 'next/navigation'
import React, { useEffect } from 'react'
import FormLayout, {
  FormField,
  FormLabelAndMessage,
  Input,
  Textarea,
} from '@components/Objects/StyledElements/Form/Form'
import * as Form from '@radix-ui/react-form'
import { AlertTriangle, Mail, User } from 'lucide-react'
import Link from 'next/link'
import { signup } from '@services/auth/auth'
import { useOrg } from '@components/Contexts/OrgContext'
import { signIn } from '@components/Contexts/AuthContext'
import { getLEARNHOUSE_TOP_DOMAIN_VAL } from '@services/config/config'
import { useTranslation } from 'react-i18next'
import { PasswordStrengthIndicator, validatePasswordStrength } from '@components/Auth/PasswordStrengthIndicator'
import { useLHAnalytics, AnalyticsEvent } from '@services/analytics'

const validate = (values: any, t: any, isBbu: boolean) => {
  const errors: any = {}

  if (!values.email) {
    errors.email = t('validation.required')
  } else if (!/^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$/i.test(values.email)) {
    errors.email = t('validation.invalid_email')
  }

  if (!values.password) {
    errors.password = t('validation.required')
  } else {
    const passwordValidation = validatePasswordStrength(values.password)
    if (!passwordValidation.isValid) {
      errors.password = t('auth.password_requirements_not_met')
    }
  }

  if (!values.username) {
    errors.username = t('validation.required')
  } else if (values.username.length < 4) {
    errors.username = t('validation.username_min_length')
  }

  if (isBbu && !values.bbu_audience) {
    errors.bbu_audience = t('validation.required')
  }

  // Bio is optional - no validation required

  return errors
}

function OpenSignUpComponent() {
  const { t } = useTranslation()
  const { track } = useLHAnalytics('public')
  const [isSubmitting, setIsSubmitting] = React.useState(false)
  const org = useOrg() as any
  const isBbu = org?.id === 1
  const _router = useRouter()
  const [error, setError] = React.useState('')
  const [message, setMessage] = React.useState<{ email_verified: boolean } | null>(null)
  const formik = useFormik({
    initialValues: {
      org_slug: org?.slug,
      org_id: org?.id,
      email: '',
      password: '',
      username: '',
      bio: '',
      first_name: '',
      last_name: '',
      bbu_audience: '',
    },
    validate: (values) => validate(values, t, isBbu),
    enableReinitialize: true,
    onSubmit: async (values) => {
      setError('')
      setMessage(null)
      setIsSubmitting(true)
      track(AnalyticsEvent.SignupSubmitted, { invite_code_present: false, has_bio: !!values.bio })
      const { bbu_audience, ...accountValues } = values
      let res = await signup({
        ...accountValues,
        ...(isBbu && {
          extra_metadata: {
            bbu_audience: bbu_audience as 'family' | 'professional',
          },
        }),
      })
      let message = await res.json()
      if (res.status == 200) {
        track(AnalyticsEvent.SignupSucceeded, { email_verified: message.email_verified })
        setMessage(message)
        setIsSubmitting(false)
      } else if (
        res.status == 401 ||
        res.status == 400 ||
        res.status == 404 ||
        res.status == 409
      ) {
        track(AnalyticsEvent.SignupFailed, { status_code: res.status })
        setError(message.detail)
        setIsSubmitting(false)
      } else {
        track(AnalyticsEvent.SignupFailed, { status_code: res.status })
        setError(t('common.something_went_wrong'))
        setIsSubmitting(false)
      }
    },
  })

  useEffect(() => { }, [org])

  const handleGoogleSignIn = () => {
    if (isBbu && !formik.values.bbu_audience) {
      formik.setFieldTouched('bbu_audience', true)
      setError('Please answer the doula or perinatal professional question before continuing.')
      return
    }
    track(AnalyticsEvent.SignupGoogleClicked)
    // Store org context in cookies before OAuth redirect
    if (org?.slug) {
      const topDomain = getLEARNHOUSE_TOP_DOMAIN_VAL();
      const isSecure = window.location.protocol === 'https:';
      const secureAttr = isSecure ? '; secure' : '';
      const baseAttributes = `; path=/; SameSite=Lax${secureAttr}`;
      const domainAttr = topDomain === 'localhost' ? '' : `; domain=.${topDomain}`;
      document.cookie = `LH_oauth_orgslug=${org.slug}${baseAttributes}${domainAttr}`;
      document.cookie = `LH_oauth_org_id=${org.id}${baseAttributes}${domainAttr}`;
      if (isBbu) {
        document.cookie = `LH_bbu_audience=${formik.values.bbu_audience}${baseAttributes}${domainAttr}`;
      }
    }
    // Use absolute URL with current origin for custom domain support
    signIn('google', { callbackUrl: `${window.location.origin}/redirect_from_auth` });
  };

  return (
    <div className="m-auto w-full max-w-sm px-6 py-8 sm:py-0">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">{t('auth.create_account')}</h1>
        <p className="text-gray-500 mt-1">{t('auth.fill_in_details')}</p>
      </div>

      {/* Error/Success Messages */}
      {error && (
        <div className="flex items-center gap-3 bg-red-100 rounded-xl text-red-900 p-4 mb-6 nice-shadow">
          <AlertTriangle size={18} className="shrink-0" />
          <div className="font-bold text-sm">{error}</div>
        </div>
      )}


      {message && message.email_verified === false && (
        <div className="flex flex-col gap-4 bg-green-100 rounded-xl text-green-900 p-4 mb-6 nice-shadow">
          <div className="flex items-center gap-2">
            <Mail size={18} />
            <div className="font-bold text-sm">{t('auth.check_email_for_verification')}</div>
          </div>
          <p className="text-xs text-green-800">
            {t('auth.verification_email_sent_message')}
          </p>
          <hr className="border-green-200" />
          <Link className="flex items-center gap-2 text-sm font-medium hover:underline" href="/login">
            <User size={14} />
            <span>{t('auth.login')}</span>
          </Link>
        </div>
      )}

      {message && message.email_verified && (
        <div className="flex flex-col gap-4 bg-green-100 rounded-xl text-green-900 p-4 mb-6 nice-shadow">
          <div className="flex items-center gap-2">
            <Mail size={18} />
            <div className="font-bold text-sm">{t('auth.account_created_success')}</div>
          </div>
          <hr className="border-green-200" />
          <Link className="flex items-center gap-2 text-sm font-medium hover:underline" href="/login">
            <User size={14} />
            <span>{t('auth.login')}</span>
          </Link>
        </div>
      )}

      {/* Signup Form Card */}
      <div className="bg-white rounded-xl p-6 nice-shadow">
        <FormLayout onSubmit={formik.handleSubmit}>
          <FormField name="email">
            <FormLabelAndMessage
              label={t('auth.email')}
              message={formik.touched.email ? formik.errors.email : undefined}
            />
            <Form.Control asChild>
              <Input
                onChange={formik.handleChange}
                onBlur={formik.handleBlur}
                value={formik.values.email}
                type="email"
                required
              />
            </Form.Control>
          </FormField>

          <div className="flex flex-row space-x-2">
            <FormField name="first_name">
              <FormLabelAndMessage
                label={t('user.first_name')}
                message={formik.touched.first_name ? formik.errors.first_name : undefined}
              />
              <Form.Control asChild>
                <Input
                  onChange={formik.handleChange}
                  onBlur={formik.handleBlur}
                  value={formik.values.first_name}
                  type="text"
                />
              </Form.Control>
            </FormField>
            <FormField name="last_name">
              <FormLabelAndMessage
                label={t('user.last_name')}
                message={formik.touched.last_name ? formik.errors.last_name : undefined}
              />
              <Form.Control asChild>
                <Input
                  onChange={formik.handleChange}
                  onBlur={formik.handleBlur}
                  value={formik.values.last_name}
                  type="text"
                />
              </Form.Control>
            </FormField>
          </div>

          <FormField name="password">
            <FormLabelAndMessage
              label={t('auth.password')}
              message={formik.touched.password ? formik.errors.password : undefined}
            />
            <Form.Control asChild>
              <Input
                onChange={formik.handleChange}
                onBlur={formik.handleBlur}
                value={formik.values.password}
                type="password"
                autoComplete="new-password"
                required
              />
            </Form.Control>
            <PasswordStrengthIndicator password={formik.values.password} />
          </FormField>

          <FormField name="username">
            <FormLabelAndMessage
              label={t('user.username')}
              message={formik.touched.username ? formik.errors.username : undefined}
            />
            <Form.Control asChild>
              <Input
                onChange={formik.handleChange}
                onBlur={formik.handleBlur}
                value={formik.values.username}
                type="text"
                required
              />
            </Form.Control>
          </FormField>

          {isBbu && (
            <FormField name="bbu_audience">
              <FormLabelAndMessage
                label="Are you wanting to become a doula, or are you already a doula or perinatal professional?"
                message={formik.touched.bbu_audience ? formik.errors.bbu_audience : undefined}
              />
              <Form.Control asChild>
                <select
                  name="bbu_audience"
                  onChange={formik.handleChange}
                  onBlur={formik.handleBlur}
                  value={formik.values.bbu_audience}
                  required
                  className="flex h-10 w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-gray-400"
                >
                  <option value="">Select an answer</option>
                  <option value="professional">Yes</option>
                  <option value="family">No</option>
                </select>
              </Form.Control>
            </FormField>
          )}

          <FormField name="bio">
            <FormLabelAndMessage
              label={`${t('user.bio')} (${t('common.optional')})`}
              message={formik.touched.bio ? formik.errors.bio : undefined}
            />
            <Form.Control asChild>
              <Textarea
                onChange={formik.handleChange}
                onBlur={formik.handleBlur}
                value={formik.values.bio}
                placeholder={t('user.bio_placeholder')}
              />
            </Form.Control>
          </FormField>

          <div className="pt-2">
            <Form.Submit asChild>
              <button className="w-full bg-black text-white font-semibold text-center py-2.5 rounded-lg hover:bg-gray-800 transition-colors">
                {isSubmitting ? t('common.loading') : t('auth.create_account')}
              </button>
            </Form.Submit>
          </div>
        </FormLayout>

        {/* Divider */}
        <div className="relative my-6">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-gray-200"></div>
          </div>
          <div className="relative flex justify-center text-sm">
            <span className="px-3 bg-white text-gray-400">{t('common.or')}</span>
          </div>
        </div>

        {/* Google Sign In */}
        <button
          onClick={handleGoogleSignIn}
          className="flex items-center justify-center gap-2 w-full py-2.5 bg-white border border-gray-200 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors"
        >
          <img src="https://fonts.gstatic.com/s/i/productlogos/googleg/v6/24px.svg" alt="" className="w-4 h-4" />
          <span>{t('auth.sign_in_with_google')}</span>
        </button>
      </div>

      {/* Login Link */}
      <p className="text-center text-gray-600 mt-6">
        {t('auth.already_have_account')}{' '}
        <Link href="/login" className="font-semibold text-gray-900 hover:underline">
          {t('auth.login')}
        </Link>
      </p>
    </div>
  )
}

export default OpenSignUpComponent
