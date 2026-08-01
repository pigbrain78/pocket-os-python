import React from "react";
import { Tabs } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { BlurView } from "expo-blur";
import { Platform, StyleSheet, View } from "react-native";
import { colors } from "@/src/theme";

export default function TabsLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.onSurface,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: {
          position: "absolute",
          borderTopColor: colors.border,
          backgroundColor: Platform.OS === "ios" ? "rgba(255,255,255,0.75)" : "#FFFFFF",
          height: 84,
          paddingTop: 8,
        },
        tabBarBackground: () => (
          Platform.OS === "ios" ? (
            <BlurView intensity={80} tint="light" style={StyleSheet.absoluteFill} />
          ) : <View style={[StyleSheet.absoluteFill, { backgroundColor: "#FFFFFF" }]} />
        ),
        tabBarLabelStyle: { fontSize: 11, fontWeight: "600" },
      }}
    >
      <Tabs.Screen
        name="console"
        options={{
          title: "Console",
          tabBarIcon: ({ color, size }) => <Ionicons name="pulse-outline" size={size} color={color} />,
          tabBarButtonTestID: "tab-console",
        }}
      />
      <Tabs.Screen
        name="timeline"
        options={{
          title: "Timeline",
          tabBarIcon: ({ color, size }) => <Ionicons name="time-outline" size={size} color={color} />,
          tabBarButtonTestID: "tab-timeline",
        }}
      />
      <Tabs.Screen
        name="graph"
        options={{
          title: "Graph",
          tabBarIcon: ({ color, size }) => <Ionicons name="git-network-outline" size={size} color={color} />,
          tabBarButtonTestID: "tab-graph",
        }}
      />
      <Tabs.Screen
        name="health"
        options={{
          title: "Health",
          tabBarIcon: ({ color, size }) => <Ionicons name="fitness-outline" size={size} color={color} />,
          tabBarButtonTestID: "tab-health",
        }}
      />
      <Tabs.Screen
        name="genome"
        options={{
          title: "Genome",
          tabBarIcon: ({ color, size }) => <Ionicons name="planet-outline" size={size} color={color} />,
          tabBarButtonTestID: "tab-genome",
        }}
      />
    </Tabs>
  );
}
