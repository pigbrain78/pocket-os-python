import React, { useState } from "react";
import { View, Text, TextInput, Pressable, StyleSheet, KeyboardAvoidingView, Platform, ScrollView, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";
import { Ionicons } from "@expo/vector-icons";
import AppleButton from "@/src/components/AppleButton";

export default function Login() {
  const router = useRouter();
  const { login } = useAuth();
  const [email, setEmail] = useState("demo@pocketos.app");
  const [password, setPassword] = useState("pocketos123");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setErr(""); setBusy(true);
    try {
      await login(email.trim(), password);
      router.replace("/(tabs)/console");
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={styles.c} testID="login-screen">
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.s}>
          <Pressable onPress={() => router.back()} testID="back-btn" hitSlop={12}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Welcome back.</Text>
          <Text style={styles.sub}>Continue building your Genome.</Text>
          <View style={styles.form}>
            <Text style={styles.lab}>Email</Text>
            <TextInput
              testID="login-email"
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
              keyboardType="email-address"
              style={styles.input}
              placeholder="you@domain.com"
              placeholderTextColor={colors.muted}
            />
            <Text style={styles.lab}>Password</Text>
            <TextInput
              testID="login-password"
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              style={styles.input}
              placeholder="••••••••"
              placeholderTextColor={colors.muted}
            />
            {err ? <Text style={styles.err} testID="login-error">{err}</Text> : null}
            <Pressable testID="login-submit" style={styles.btn} onPress={submit} disabled={busy}>
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnT}>Sign in</Text>}
            </Pressable>
            <View style={styles.divider}><View style={styles.dLine} /><Text style={styles.dT}>or</Text><View style={styles.dLine} /></View>
            <AppleButton onError={(m) => setErr(m)} />
            <Pressable onPress={() => router.replace("/auth/register")} testID="switch-to-register">
              <Text style={styles.switch}>Don't have an account? Create one</Text>
            </Pressable>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  s: { padding: spacing.xl, gap: spacing.md },
  h1: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface, marginTop: spacing.lg },
  sub: { color: colors.muted, fontSize: fs.lg, marginBottom: spacing.xl },
  form: { gap: spacing.sm },
  lab: { fontSize: fs.sm, color: colors.muted, marginTop: spacing.md, textTransform: "uppercase", letterSpacing: 0.5 },
  input: { backgroundColor: colors.surfaceSecondary, padding: spacing.lg, borderRadius: radius.md, fontSize: fs.lg, color: colors.onSurface },
  btn: { backgroundColor: colors.onSurface, padding: spacing.lg, borderRadius: radius.md, alignItems: "center", marginTop: spacing.lg },
  btnT: { color: "#fff", fontSize: fs.lg, fontWeight: "700" },
  switch: { color: colors.muted, textAlign: "center", marginTop: spacing.lg, fontSize: fs.base },
  err: { color: colors.error, marginTop: spacing.sm },
  divider: { flexDirection: "row", alignItems: "center", marginVertical: spacing.md, gap: spacing.md },
  dLine: { flex: 1, height: 1, backgroundColor: colors.border },
  dT: { color: colors.muted, fontSize: fs.sm },
});
