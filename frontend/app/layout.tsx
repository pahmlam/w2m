import type { Metadata } from "next";
import localFont from "next/font/local";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";

const nunito = localFont({ src: "./fonts/Nunito.ttf", variable: "--nunito", weight: "200 1000", display: "swap" });
const baloo = localFont({ src: "./fonts/Baloo2.ttf", variable: "--baloo", weight: "400 800", display: "swap" });

export const metadata: Metadata = {
  title: "W2M — Where to meet",
  description: "Find a meeting spot based on travel times for the whole group.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${nunito.variable} ${baloo.variable}`}>
      <body>{children}</body>
    </html>
  );
}
