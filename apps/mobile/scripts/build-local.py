"""Build with this Mac's Gradle/Xcode. Never upload, log in to EAS, or submit review."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(args, *, cwd=ROOT, capture=False, env=None):
    result = subprocess.run(args, cwd=cwd, env=env or os.environ,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if result.returncode:
        # Captured commands handle signing passwords; never echo their arguments/output.
        raise RuntimeError(f'{Path(args[0]).name} failed (exit {result.returncode})')
    return result.stdout if capture else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('platform', choices=['android', 'ios'])
    parser.add_argument('variant', choices=['preview', 'production'])
    args = parser.parse_args()
    os.environ.update(APP_VARIANT=args.variant, EXPO_NO_CAPABILITY_SYNC='1', NODE_ENV='production')
    production = args.variant == 'production'
    credentials = None
    if args.platform == 'ios':
        version = run(['xcodebuild', '-version'], capture=True).decode()
        match = re.search(r'Xcode (\d+)\.(\d+)', version)
        if not match or tuple(map(int, match.groups())) < (26, 2):
            raise RuntimeError('Install Xcode 26.2 or newer for SDK 55')
    if production:
        run([sys.executable, 'scripts/check-signing.py', args.platform])
        credentials = json.loads((ROOT / 'credentials.json').read_text())
        if args.platform == 'ios':
            profile_path = (ROOT / credentials['ios']['provisioningProfilePath']).resolve()
            profile = plistlib.loads(run(['security', 'cms', '-D', '-i', str(profile_path)], capture=True))
            os.environ['BBU_IOS_PROFILE_UUID'] = profile['UUID']
    run(['npx', '--no-install', 'expo', 'prebuild', '--clean', '--no-install', '--platform', args.platform])
    if args.platform == 'android':
        if production:
            key = credentials['android']['keystore']
            os.environ.update(BBU_UPLOAD_STORE=str((ROOT / key['keystorePath']).resolve()),
                              BBU_UPLOAD_STORE_PASSWORD=key['keystorePassword'],
                              BBU_UPLOAD_ALIAS=key['keyAlias'], BBU_UPLOAD_KEY_PASSWORD=key['keyPassword'])
        task = ':app:bundleRelease' if production else ':app:assembleRelease'
        run(['./gradlew', task, '--no-daemon', '--max-workers=2'], cwd=ROOT / 'android')
        suffix = 'bundle/release/app-release.aab' if production else 'apk/release/app-release.apk'
        source = ROOT / 'android/app/build/outputs' / suffix
        output = ROOT / 'artifacts' / f'android-{args.variant}{source.suffix}'
        output.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, output)
        print(f'Local build saved: {output}')
        return
    run(['pod', 'install'], cwd=ROOT / 'ios')
    workspace = next((ROOT / 'ios').glob('*.xcworkspace'))
    scheme = workspace.stem
    output = ROOT / 'artifacts'
    output.mkdir(exist_ok=True)
    common = ['xcodebuild', '-workspace', str(workspace), '-scheme', scheme, '-configuration', 'Release']
    if not production:
        run(common + ['-sdk', 'iphonesimulator', '-destination', 'generic/platform=iOS Simulator',
                      '-derivedDataPath', str(output / 'ios-preview'), 'CODE_SIGNING_ALLOWED=NO', 'build'])
        return
    ios = credentials['ios']
    profile_path = (ROOT / ios['provisioningProfilePath']).resolve()
    profile = plistlib.loads(run(['security', 'cms', '-D', '-i', str(profile_path)], capture=True))
    profiles = Path.home() / 'Library/Developer/Xcode/UserData/Provisioning Profiles'
    profiles.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(profile_path, profiles / (profile['UUID'] + '.mobileprovision'))
    old_search = shlex.split(run(['security', 'list-keychains', '-d', 'user'], capture=True).decode())
    with tempfile.TemporaryDirectory(prefix='bbu-signing-') as temporary:
        keychain = str(Path(temporary) / 'build.keychain-db')
        password = secrets.token_urlsafe(32)
        try:
            run(['security', 'create-keychain', '-p', password, keychain], capture=True)
            run(['security', 'set-keychain-settings', '-lut', '21600', keychain], capture=True)
            run(['security', 'unlock-keychain', '-p', password, keychain], capture=True)
            certificate = ios['distributionCertificate']
            run(['security', 'import', str((ROOT / certificate['path']).resolve()), '-k', keychain,
                 '-P', certificate['password'], '-T', '/usr/bin/codesign', '-T', '/usr/bin/security'], capture=True)
            run(['security', 'set-key-partition-list', '-S', 'apple-tool:,apple:,codesign:', '-s', '-k', password, keychain], capture=True)
            run(['security', 'list-keychains', '-d', 'user', '-s', keychain, *old_search], capture=True)
            archive = output / 'BBU.xcarchive'
            run(common + ['-destination', 'generic/platform=iOS', '-archivePath', str(archive), 'archive'])
            options = Path(temporary) / 'ExportOptions.plist'
            bundle = profile['Entitlements']['application-identifier'].split('.', 1)[1]
            options.write_bytes(plistlib.dumps({'method': 'app-store-connect', 'destination': 'export',
                'signingStyle': 'manual', 'teamID': profile['TeamIdentifier'][0],
                'provisioningProfiles': {bundle: profile['UUID']}, 'manageAppVersionAndBuildNumber': False}))
            run(['xcodebuild', '-exportArchive', '-archivePath', str(archive),
                 '-exportOptionsPlist', str(options), '-exportPath', str(output / 'ios-production')])
        finally:
            run(['security', 'list-keychains', '-d', 'user', '-s', *old_search], capture=True)
            subprocess.run(['security', 'delete-keychain', keychain], capture_output=True)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, KeyError, StopIteration) as error:
        print(f'Local build stopped: {error}', file=sys.stderr)
        sys.exit(1)
