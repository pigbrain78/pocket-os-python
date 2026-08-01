import React, { useState } from "react";
import { View, Text, TextInput, Pressable, StyleSheet, KeyboardAvoidingView, Platform, ScrollView } from "react-native";
import { Stack, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";
import { Ionicons } from "@expo/vector-icons";

export default function Welcome() {
  const router = useRouter();
  return (
    <SafeAreaView style={styles.c} testID="welcome-screen">
      <Stack.Screen options={{ headerShown: false }} />
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.top}>
          <View style={styles.badge}><Ionicons name="pulse" size={18} color="#fff" /></View>
          <Text style={styles.brand}>Pocket OS</Text>
          <Text style={styles.tag}>A cognitive operating system.</Text>
        </View>
        <View style={styles.hero}>
          <Text style={styles.h1}>Everything you capture</Text>
          <Text style={[styles.h1, { color: colors.muted }]}>becomes connected.</Text>
        </View>
        <View style={styles.pointers}>
          {[
            ["radio-outline", "Cognitive Timeline replays your thinking"],
            ["git-network-outline", "Living Knowledge Graph grows in real time"],
            ["people-outline", "A council of 5 AI agents reviews your ideas"],
            ["speedometer-outline", "Memory Health, Gravity & Knowledge ROI"],
          ].map(([ic, t]) => (
            <View key={t} style={styles.row}>
              <Ionicons name={ic as any} size={18} color={colors.onSurface} />
              <Text style={styles.rowT}>{t}</Text>
            </View>
          ))}
        </View>
        <View style={styles.actions}>
          <Pressable testID="cta-signup" style={styles.primary} onPress={() => router.push("/auth/register")}>
            <Text style={styles.primaryT}>Create your Genome</Text>
          </Pressable>
          <Pressable testID="cta-login" style={styles.secondary} onPress={() => router.push("/auth/login")}>
            <Text style={styles.secondaryT}>I already have an account</Text>
          </Pressable>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, paddingBottom: spacing["2xl"] },
  top: { alignItems: "flex-start", marginTop: spacing.lg },
  badge: { width: 40, height: 40, borderRadius: 12, backgroundColor: colors.onSurface, alignItems: "center", justifyContent: "center" },
  brand: { fontSize: fs["2xl"], fontWeight: "700", marginTop: spacing.md, color: colors.onSurface },
  tag: { fontSize: fs.base, color: colors.muted, marginTop: 4 },
  hero: { marginTop: spacing["3xl"] },
  h1: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface, lineHeight: 40 },
  pointers: { marginTop: spacing["2xl"], gap: spacing.md },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surfaceSecondary, padding: spacing.lg, borderRadius: radius.md },
  rowT: { fontSize: fs.base, color: colors.onSurface, flex: 1 },
  actions: { marginTop: spacing["2xl"], gap: spacing.md },
  primary: { backgroundColor: colors.onSurface, padding: spacing.lg, borderRadius: radius.md, alignItems: "center" },
  primaryT: { color: colors.surface, fontSize: fs.lg, fontWeight: "700" },
  secondary: { padding: spacing.lg, borderRadius: radius.md, alignItems: "center", borderWidth: 1, borderColor: colors.border },
  secondaryT: { color: colors.onSurface, fontSize: fs.lg, fontWeight: "600" },
});
