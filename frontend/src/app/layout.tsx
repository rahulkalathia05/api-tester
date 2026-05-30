import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ToasterClient } from "@/components/ui/toaster-client";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "API Tester — AI-Powered API Testing",
  description: "Test, debug, and analyze your APIs with AI-powered insights.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        {children}
        <ToasterClient />
      </body>
    </html>
  );
}
