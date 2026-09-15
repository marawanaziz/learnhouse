// Exercise the actual server action: browser cookies are not forwarded by fetch.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const source = fs.readFileSync(process.env.OFFERS_TEST_SOURCE || path.join(__dirname, '../services/payments/offers.ts'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;

async function check(referral) {
  let outgoing;
  const mod = { exports: {} };
  const stubs = {
    'next/headers': { cookies: async () => ({ get: name => name === 'bbu_ref' && referral ? { value: referral } : undefined }) },
    '@services/config/config': { getAPIUrl: () => 'https://api.example.test/' },
    '@services/utils/ts/requests': {
      RequestBodyWithAuthHeader: (method, body, unused, token) => ({ method, body: JSON.stringify(body), token }),
      secureFetch: async (url, options) => { outgoing = { url, ...options }; return { success: true }; },
      getResponseMetadata: result => result,
    },
  };
  vm.runInNewContext(compiled, { module: mod, exports: mod.exports, URLSearchParams,
    require: name => { if (!(name in stubs)) throw Error('Missing stub: ' + name); return stubs[name]; } });
  await mod.exports.getOfferCheckoutSession(1, 'offer_6', 'https://store.example.test/success', 'buyer-token', ['offer_8']);
  assert.deepEqual(JSON.parse(outgoing.body), { bumps: ['offer_8'], affiliate_ref: referral || '' });
  assert.equal(outgoing.token, 'buyer-token');
  assert.equal(outgoing.method, 'POST');
  assert.equal(new URL(outgoing.url).searchParams.get('redirect_uri'), 'https://store.example.test/success');
}

(async () => {
  await check('mbfmama');
  await check(undefined);
  console.log('PASS: native checkout carries referral cookie; ordinary checkout, bumps, authentication and return URL preserved');
})().catch(error => { console.error(error); process.exitCode = 1; });
