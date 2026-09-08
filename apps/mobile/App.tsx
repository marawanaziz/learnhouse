import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator, Alert, BackHandler, Image, KeyboardAvoidingView,
  Linking, Platform, Pressable, StyleSheet, Text, View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useNetworkState } from 'expo-network';
import * as WebBrowser from 'expo-web-browser';
import { SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import { classifyNavigation, isMainDocumentFailure, SITE_URL } from './src/navigation';

const BLUE = '#113d5d';
const LOAD_TIMEOUT_MS = 35_000;

function University() {
  const insets = useSafeAreaInsets();
  const network = useNetworkState();
  const offline = network.isConnected === false || network.isInternetReachable === false;
  const webView = useRef<WebView>(null);
  const canGoBack = useRef(false);
  const lastPage = useRef(SITE_URL);
  const currentPage = useRef(SITE_URL);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const failed = useRef(false);
  const externalOpen = useRef(false);
  const [source, setSource] = useState({ uri: SITE_URL });
  const [instance, setInstance] = useState(0);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  function clearTimer() {
    clearTimeout(timer.current);
    timer.current = undefined;
  }

  function showError() {
    clearTimer();
    failed.current = true;
    setLoading(false);
    setError(true);
  }

  function beginLoad(url: string) {
    clearTimer();
    if (classifyNavigation(url) === 'internal') currentPage.current = url;
    failed.current = false;
    setError(false);
    setLoading(true);
    timer.current = setTimeout(() => {
      webView.current?.stopLoading();
      showError();
    }, LOAD_TIMEOUT_MS);
  }

  function restart() {
    // Explicit recovery makes a fresh GET to the last successful page; never replay a form POST.
    clearTimer();
    failed.current = false;
    canGoBack.current = false;
    setError(false);
    setReady(false);
    setLoading(true);
    setSource({ uri: lastPage.current });
    setInstance((value) => value + 1);
  }

  async function openExternal(url: string) {
    const action = classifyNavigation(url);
    if (externalOpen.current || (action !== 'browser' && action !== 'device')) return;
    externalOpen.current = true;
    try {
      if (action === 'browser') {
        await WebBrowser.openBrowserAsync(url, {
          toolbarColor: BLUE, controlsColor: '#ffffff',
          presentationStyle: WebBrowser.WebBrowserPresentationStyle.FULL_SCREEN,
        });
      } else {
        await Linking.openURL(url);
      }
    } catch {
      Alert.alert('Unable to open link', 'Please try again when a browser, phone, or mail app is available.');
    } finally {
      externalOpen.current = false;
    }
  }

  useEffect(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      if (!canGoBack.current) return false;
      webView.current?.goBack();
      return true;
    });
    return () => {
      subscription.remove();
      clearTimeout(timer.current);
    };
  }, []);

  return (
    <View style={styles.app}>
      <StatusBar style="light" />
      <View style={{ height: insets.top, backgroundColor: BLUE }} />
      <KeyboardAvoidingView style={styles.content} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={[styles.content, { marginLeft: insets.left, marginRight: insets.right }]}>
          {offline && ready && !error && (
            <View style={styles.offline} accessibilityLiveRegion="polite">
              <Text style={styles.offlineText}>You’re offline. Reconnect to continue learning.</Text>
            </View>
          )}
          <View style={styles.content}>
            <WebView
              key={instance}
              ref={webView}
              source={source}
              style={styles.webView}
              applicationNameForUserAgent="BBUWrapper/1.0"
              originWhitelist={['*']}
              onShouldStartLoadWithRequest={(request) => {
                const action = classifyNavigation(request.url, request.isTopFrame);
                if (action === 'internal' || action === 'frame') return true;
                if (action === 'browser' || action === 'device') void openExternal(request.url);
                return false;
              }}
              onOpenWindow={({ nativeEvent: { targetUrl } }) => {
                if (classifyNavigation(targetUrl) === 'internal') setSource({ uri: targetUrl });
                else void openExternal(targetUrl);
              }}
              onNavigationStateChange={(state) => {
                canGoBack.current = state.canGoBack;
                if (classifyNavigation(state.url) === 'internal') {
                  currentPage.current = state.url;
                  if (!state.loading && !failed.current) lastPage.current = state.url;
                }
              }}
              onLoadStart={({ nativeEvent }) => beginLoad(nativeEvent.url)}
              onLoad={() => {
                if (failed.current) return;
                lastPage.current = currentPage.current;
                setReady(true);
              }}
              onLoadEnd={() => { clearTimer(); setLoading(false); }}
              onError={showError}
              onHttpError={({ nativeEvent }) => {
                if (isMainDocumentFailure(nativeEvent.url, currentPage.current, nativeEvent.statusCode)) showError();
              }}
              onContentProcessDidTerminate={showError}
              onRenderProcessGone={showError}
              renderError={() => <View style={styles.content} />}
              allowsBackForwardNavigationGestures
              allowsInlineMediaPlayback
              allowsFullscreenVideo
              mediaPlaybackRequiresUserAction
              sharedCookiesEnabled
              thirdPartyCookiesEnabled
              domStorageEnabled
              incognito={false}
              cacheEnabled
              mixedContentMode="never"
              allowFileAccess={false}
              allowFileAccessFromFileURLs={false}
              allowUniversalAccessFromFileURLs={false}
              javaScriptCanOpenWindowsAutomatically={false}
              setSupportMultipleWindows
              webviewDebuggingEnabled={__DEV__}
              automaticallyAdjustContentInsets={false}
              contentInsetAdjustmentBehavior="never"
            />
            {ready && loading && !error && (
              <View pointerEvents="none" style={styles.progress}>
                <ActivityIndicator size="small" color={BLUE} accessibilityLabel="Loading page" />
              </View>
            )}
            {(!ready || error) && (
              <View style={styles.cover} accessibilityViewIsModal>
                <Image source={require('./assets/bbu-icon.png')} style={styles.logo} accessibilityIgnoresInvertColors accessibilityLabel="Birth & Baby University" />
                {error ? (
                  <>
                    <Text style={styles.title} accessibilityRole="header">{offline ? 'You’re offline' : 'Let’s reconnect'}</Text>
                    <Text style={styles.message}>{offline ? 'Connect to Wi-Fi or mobile data, then try again.' : 'We couldn’t load your page. Please try again.'}</Text>
                    <Pressable accessibilityRole="button" onPress={restart} style={({ pressed }) => [styles.button, pressed && styles.pressed]}>
                      <Text style={styles.buttonText}>Try again</Text>
                    </Pressable>
                  </>
                ) : (
                  <>
                    <ActivityIndicator color={BLUE} size="large" accessibilityLabel="Loading Birth & Baby University" />
                    <Text style={styles.message}>Your learning, wherever you are.</Text>
                  </>
                )}
              </View>
            )}
          </View>
        </View>
      </KeyboardAvoidingView>
      <View style={{ height: insets.bottom, backgroundColor: '#ffffff' }} />
    </View>
  );
}

export default function App() {
  return <SafeAreaProvider><University /></SafeAreaProvider>;
}

const styles = StyleSheet.create({
  app: { flex: 1, backgroundColor: BLUE },
  content: { flex: 1, backgroundColor: '#ffffff' },
  webView: { flex: 1, backgroundColor: '#ffffff' },
  cover: { ...StyleSheet.absoluteFill, backgroundColor: '#ffffff', alignItems: 'center', justifyContent: 'center', padding: 28 },
  logo: { width: 180, height: 180, resizeMode: 'contain', marginBottom: 28 },
  title: { fontSize: 25, fontWeight: '600', color: BLUE, textAlign: 'center', marginBottom: 12 },
  message: { fontSize: 16, lineHeight: 24, color: '#566575', textAlign: 'center', marginTop: 14, maxWidth: 320 },
  button: { marginTop: 28, backgroundColor: BLUE, paddingHorizontal: 32, paddingVertical: 15, borderRadius: 14, minHeight: 48 },
  buttonText: { fontSize: 16, fontWeight: '600', color: '#ffffff' },
  pressed: { opacity: 0.75 },
  progress: { position: 'absolute', top: 6, right: 8, borderRadius: 20, backgroundColor: '#ffffff', padding: 6 },
  offline: { backgroundColor: '#fff4db', paddingHorizontal: 16, paddingVertical: 8 },
  offlineText: { color: '#624819', textAlign: 'center', fontSize: 13 },
});
