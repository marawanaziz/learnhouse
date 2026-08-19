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
  const isBbu = Number(org?.id) === 1
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
        <FormLayout onSubmit={formik.handleSubmit} noValidate>
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
              />
            </Form.Control>
          </FormField>

          {isBbu && (
            <FormField name="bbu_audience">
              <FormLabelAndMessage
                label="Are you wanting to become a doula, or are you already a doula or perinatal professional?"
                message={formik.touched.bbu_audience ? formik.errors.bbu_audience : undefined}
                labelId="bbu-audience-label"
                messageId="bbu-audience-error"
              />
              <div
                role="radiogroup"
                aria-labelledby="bbu-audience-label"
                aria-describedby={formik.touched.bbu_audience && formik.errors.bbu_audience ? 'bbu-audience-error' : undefined}
                aria-required="true"
                aria-invalid={formik.touched.bbu_audience && !!formik.errors.bbu_audience}
                className="flex gap-4 pt-1"
              >
                {[
                  { value: 'professional', label: 'Yes' },
                  { value: 'family', label: 'No' },
                ].map((option) => (
                  <label
                    key={option.value}
                    className="inline-flex min-h-10 cursor-pointer items-center gap-2 rounded-md border border-gray-200 px-3 py-2 text-sm text-gray-900 transition-colors hover:border-gray-400 focus-within:border-gray-500 focus-within:ring-2 focus-within:ring-gray-400 focus-within:ring-offset-1"
                  >
                    <input
                      type="radio"
                      name="bbu_audience"
                      value={option.value}
                      checked={formik.values.bbu_audience === option.value}
                      onChange={formik.handleChange}
                      onBlur={formik.handleBlur}
                      className="h-4 w-4 accent-black"
                    />
                    <span>{option.label}</span>
                  </label>
                ))}
              </div>
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
