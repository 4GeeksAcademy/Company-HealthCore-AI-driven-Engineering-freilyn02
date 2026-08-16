import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
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
    <html lang="en">
      <body className="min-h-screen bg-[#faf9f7] text-[#101010]">
        <header className="flex items-center gap-6 border-b border-[rgba(16,16,16,0.06)] bg-white px-6 py-4">
          <h1 className="font-[family-name:var(--font-space-grotesk)] text-lg tracking-[-0.03em] text-[#ff6a3d]">
            HealthCore Backoffice
          </h1>
          <nav className="flex gap-4 text-sm">
            <Link href="/suppliers" className="font-semibold text-[#5f5a54] hover:text-[#ff6a3d]">
              Supplier Directory
            </Link>
            <Link href="/incidents" className="font-semibold text-[#5f5a54] hover:text-[#ff6a3d]">
              Incident Manager
            </Link>
          </nav> 
        </header>
        <main className="p-6">{children}</main>
      </body>
    </html>
  );
}