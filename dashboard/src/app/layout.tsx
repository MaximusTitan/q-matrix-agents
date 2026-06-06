import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import "./globals.css";

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "Q-Matrix Pipeline Dashboard",
  description: "Live dashboard for the Q-Matrix curriculum generation pipeline",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`dark ${jetbrainsMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col font-mono text-[13px]">{children}</body>
    </html>
  );
}
