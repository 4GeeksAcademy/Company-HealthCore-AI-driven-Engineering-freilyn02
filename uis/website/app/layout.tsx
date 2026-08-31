import type { Metadata } from "next";
import { Manrope, Space_Grotesk } from "next/font/google";
import "./globals.css";
import Header from "./components/Header";
import Footer from "./components/Footer";

const manrope = Manrope({ subsets: ["latin"], variable: "--font-manrope" });
const spaceGrotesk = Space_Grotesk({ subsets: ["latin"], variable: "--font-space-grotesk" });

export const metadata: Metadata = {
  title: "HealthCore",
  description: "HealthCore — outpatient clinic network across the US and UK",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${manrope.variable} ${spaceGrotesk.variable}`}>
      <body className="font-[family-name:var(--font-manrope)] bg-[radial-gradient(circle_at_top_left,rgba(255,106,61,0.12),transparent_30%),linear-gradient(180deg,#fff8ef_0%,#f3ede5_100%)] text-[#101010] leading-[1.6] m-0">
        <Header />
        <main>{children}</main>
        <Footer />
      </body>
    </html>
  );
}