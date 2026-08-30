import type { Metadata } from "next";
import Link from "next/link";
import { Manrope, Space_Grotesk } from "next/font/google";
import "./globals.css";

const manrope = Manrope({ subsets: ["latin"], variable: "--font-manrope" });
const spaceGrotesk = Space_Grotesk({ subsets: ["latin"], variable: "--font-space-grotesk" });

export const metadata: Metadata = {
  title: "HealthCore Backoffice",
  description: "Internal tools for HealthCore Digital staff",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${manrope.variable} ${spaceGrotesk.variable}`}>
      <body className="min-h-screen bg-[radial-gradient(circle_at_top_left,rgba(255,106,61,0.10),transparent_30%),linear-gradient(180deg,#fff8ef_0%,#f3ede5_100%)] font-[family-name:var(--font-manrope)] text-[#101010]">
        <header className="sticky top-0 z-[100] flex items-center gap-6 border-b border-[rgba(16,16,16,0.06)] bg-[rgba(255,250,243,0.82)] px-[5%] py-[18px] backdrop-blur-[14px] md:px-[8%]">
          <h1 className="font-[family-name:var(--font-space-grotesk)] text-[1.35rem] font-bold tracking-[-0.04em]">
            Health<span className="text-[#ff6a3d]">Core</span> Backoffice
          </h1>
          <nav className="text-sm">
            <Link href="/suppliers" className="font-semibold text-[#5f5a54] hover:text-[#ff6a3d]">
              Supplier Directory
            </Link>
          </nav>
        </header>
        <main className="px-[5%] py-10 md:px-[8%]">{children}</main>
      </body>
    </html>
  );
}