// Render the actual auth screens and follow the links and submit callbacks.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const React = require('react');
const { act, create } = require('react-test-renderer');
const ts = require('typescript');
global.IS_REACT_ACT_ENVIRONMENT = true;
const root = path.resolve(__dirname, '..');
let params, form, resetRequest, signedIn, location;
const noop = () => {};
const wrapper = ({ children, ...props }) => React.createElement('div', props, children);
const link = ({ children, ...props }) => React.createElement('a', props, children);
const stubs = {
  react: React, 'next/link': link,
  'next/navigation': { useRouter: () => ({ push: noop }), useSearchParams: () => params },
  formik: { useFormik: config => { form = config; return { values: config.initialValues, errors: {}, touched: {}, handleSubmit: noop, handleChange: noop, handleBlur: noop }; } },
  '@components/Objects/StyledElements/Form/Form': { __esModule: true, default: wrapper, FormField: wrapper, FormLabelAndMessage: wrapper, Input: wrapper, Textarea: wrapper },
  '@radix-ui/react-form': { Control: wrapper, Submit: wrapper },
  'lucide-react': new Proxy({}, { get: () => noop }),
  '@components/Contexts/OrgContext': { useOrg: () => ({ id: 1, slug: 'test' }) },
  '@components/Contexts/AuthContext': { useAuth: () => ({ signIn: async (_, values) => { signedIn = values; return {}; } }) },
  '@components/Contexts/LHSessionContext': { useLHSession: () => ({}) },
  'react-i18next': { useTranslation: () => ({ t: key => key }) },
  '@services/config/config': { getDeploymentMode: () => 'oss' },
  '@services/analytics': { useLHAnalytics: () => ({ track: noop }), AnalyticsEvent: {} },
  '@services/auth/sso': {},
  '@services/auth/auth': { sendResetLink: async (...args) => { resetRequest = args; return { status: 200, data: 'sent' }; }, resetPassword: async () => ({status:200,data:'changed'}) },
  '@components/Auth/AuthLayout': wrapper,
  '@components/Auth/PasswordStrengthIndicator': { PasswordStrengthIndicator: noop, validatePasswordStrength: () => ({ isValid: true }) },
};
function compile(file) {
  const mod = { exports: {} };
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(root, file), 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText, {
    module: mod, exports: mod.exports, require: name => {
      if (name in stubs) return stubs[name];
      if (name.startsWith('@/lib/auth/')) return compile(name.replace('@/', '') + '.ts');
      throw Error('Missing stub: ' + name);
    }, console, URL, URLSearchParams, window: { location }, setTimeout: noop, clearTimeout: noop,
  });
  return mod.exports;
}
let renderer;
async function screen(file, url, props = {}) {
  if (renderer) await act(async () => renderer.unmount());
  const parsed = new URL(url, 'https://app.test');
  params = parsed.searchParams;
  location = { search: parsed.search, origin: parsed.origin, href: parsed.href };
  const Component = compile(file).default;
  await act(async () => { renderer = create(React.createElement(Component, {org:{id:1,slug:'test'},...props})); });
}
function href(text) { return renderer.root.findAllByType('a').find(el => el.children.includes(text)).props.href; }
async function submit(values) { await act(async () => form.onSubmit(values, {validateForm:async()=>({}),setErrors:noop,setSubmitting:noop})); }
(async () => {
  const target = '/signup?inviteCode=qgLDnuoX';
  await screen('app/auth/signup/InviteOnlySignUp.tsx', target, {inviteCode:'qgLDnuoX'});
  const login = href('auth.login');
  assert.equal(new URL(login, 'https://app.test').searchParams.get('returnTo'), target, 'existing learner login must retain the invitation');
  await screen('app/auth/login/login.tsx', login);
  await submit({email:'qa@example.com',password:'TestPass123!'});
  assert.equal(signedIn.callbackUrl, 'https://app.test' + target);
  assert.equal(location.href, signedIn.callbackUrl);
  const forgot = href('auth.forgot_password');
  await screen('app/auth/forgot/forgot.tsx', forgot);
  await submit({email:'qa@example.com'});
  assert.deepEqual(resetRequest, ['qa@example.com',1,target], 'reset request must carry the invite into its email link');
  assert.equal(href('auth.back_to_login'), login);
  await screen('app/auth/reset/reset.tsx', '/reset?email=qa%40example.com&resetCode=code&returnTo=' + encodeURIComponent(target));
  assert.equal(href('auth.login'), login);
  await submit({email:'qa@example.com',new_password:'NewPass123!',reset_code:'code'});
  assert.equal(href('auth.proceed_to_login'), login);
  await screen('app/auth/login/login.tsx', '/login?redirect=' + encodeURIComponent('/store/offers/offer_17'));
  await submit({email:'qa@example.com',password:'TestPass123!'});
  assert.equal(signedIn.callbackUrl, 'https://app.test/store/offers/offer_17');
  for (const unsafe of ['https://evil.test','//evil.test','/\\evil.test','/\nevil.test']) {
    await screen('app/auth/login/login.tsx', '/login?returnTo=' + encodeURIComponent(unsafe));
    await submit({email:'qa@example.com',password:'TestPass123!'});
    assert.equal(signedIn.callbackUrl, 'https://app.test/redirect_from_auth');
  }
  await act(async () => renderer.unmount());
  console.log('PASS: invitation → login → password reset → login retains destination; legacy checkout and unsafe destinations covered');
})().catch(error => {console.error(error);process.exitCode=1;});
