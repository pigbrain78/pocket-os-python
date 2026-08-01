import React, { useEffect, useState } from "react";
import { Platform, View, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import * as AppleAuthentication from "expo-apple-authentication";
import { useAuth } from "@/src/lib/auth";
import { radius } from "@/src/theme";

/**
 * Native "Sign in with Apple" button.
 * Gated to iOS — renders null on Android/web (email/password remains available).
 * On success, verifies the identity token server-side and stores the JWT session.
 */
export default function AppleButton({ onError }: { onError?: (msg: string) => void }) {
  const router = useRouter();
  const { loginWithApple } = useAuth();
  const [available, setAvailable] = useState(false);

  useEffect(() => {
    let mounted = true;
    if (Platform.OS !== "ios") return;
    AppleAuthentication.isAvailableAsync().then((ok) => { if (mounted) setAvailable(ok); }).catch(() => {});
    return () => { mounted = false; };
  }, []);

  if (Platform.OS !== "ios" || !available) return null;

  const onPress = async () => {
    try {
      const credential = await AppleAuthentication.signInAsync({
        requestedScopes: [
          AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
          AppleAuthentication.AppleAuthenticationScope.EMAIL,
        ],
      });
      if (!credential.identityToken) {
        onError?.("Apple did not return an identity token.");
        return;
      }
      const fullName = credential.fullName
        ? [credential.fullName.givenName, credential.fullName.familyName].filter(Boolean).join(" ")
        : null;
      await loginWithApple(credential.identityToken, fullName, credential.email);
      router.replace("/(tabs)/console");
    } catch (e: any) {
      if (e?.code === "ERR_REQUEST_CANCELED") return;
      onError?.(e?.message || "Apple sign-in failed");
    }
  };

  return (
    <View testID="apple-signin-wrap" style={styles.wrap}>
      <AppleAuthentication.AppleAuthenticationButton
        buttonType={AppleAuthentication.AppleAuthenticationButtonType.SIGN_IN}
        buttonStyle={AppleAuthentication.AppleAuthenticationButtonStyle.BLACK}
        cornerRadius={radius.md}
        style={styles.button}
        onPress={onPress}
      />
    </View>
  );
}
const styles = StyleSheet.create({
  wrap: { width: "100%" },
  button: { width: "100%", height: 52 },
});
